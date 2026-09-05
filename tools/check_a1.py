#!/usr/bin/env python3
"""Check current A1 evidence against the selected PRF integration contract."""

import argparse
import copy
import json
import math
from pathlib import Path

from run_a1_probe import ROOT, SOURCES, TOP, digest


RECEIPTS = {
    "prf": "out/prf/mutation_receipt.json",
    "rtl": "out/a1/rtl_receipt_mutations.json",
    "generic": "out/a1/synthesis_receipt.json",
    "timing": "out/a1_timing/receipt.json",
}
TOPS = {"prf_4r2w": 2016, "a1_select_probe": 0, TOP: 2016}
BASE = {"config/prf_contract.json", "config/toolchain.lock"}
PROBE = BASE | set(SOURCES) | {"tools/run_a1_probe.py", "verif/unit/a1_backend_probe_tb.cpp", "config/synthesis.lock"}
INPUTS = {
    "prf": BASE | {SOURCES[0], "tools/run_prf_check.py", "verif/unit/prf_4r2w_tb.cpp"},
    "rtl": PROBE,
    "generic": PROBE,
    "timing": PROBE | {"config/a1_timing.json", "config/a1_timing.lock", "synth/a1_timing.tcl",
                       "tools/run_a1_timing.py", "tools/fetch_a1_timing.py"},
}


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def fingerprints(hashes: dict, required: set[str], kind: str) -> None:
    require(required <= hashes.keys(), f"missing {kind} fingerprints")
    for name, expected in hashes.items():
        path = ROOT / name
        require(not Path(name).is_absolute() and path.resolve().is_relative_to(ROOT), "invalid artifact path")
        require(path.is_file() and digest(path) == expected, f"stale {kind}: {name}")


def evaluate(data: dict, contract: dict) -> None:
    shape = tuple(contract[k] for k in ("registers", "data_bits", "read_ports", "write_ports", "read_latency_cycles"))
    require(shape == (64, 32, 4, 2, 0), "unsupported PRF contract")
    semantics = {"schema": 1, "profile": "a1-flop-mux-combinational", "write_edge": "rising",
                 "lane_order": "lane_zero_in_low_slice", "zero_register": "p0_has_no_storage_and_reads_zero",
                 "payload_reset": "uninitialized_at_startup_preserved_on_reset",
                 "writeback": "accepted_only_same_cycle_read_bypass", "duplicate_nonzero_write": "illegal_asserted",
                 "reset": "suppress_writes_and_bypass"}
    require(all(contract[k] == v for k, v in semantics.items()), "unsupported PRF semantics")
    require(contract["physical_gate"] == "PHY0", "missing physical gate disposition")
    acceptance = contract["acceptance"]
    for name, receipt in data.items():
        require(receipt["schema"] == 1, "unsupported receipt schema")
        fingerprints(receipt["inputs_sha256"], INPUTS[name], "input")
        key = "simulation" if name == "prf" else "rtl_simulation" if name == "rtl" else "mapped_simulation"
        runs = receipt[key]
        require([r["seed"] for r in runs] == acceptance["seeds"], f"missing simulation seed: {name}")
        metric = "cycles" if name == "prf" else "cases"
        minimum = acceptance["minimum_prf_cycles_per_seed" if name == "prf" else "minimum_probe_cases_per_seed"]
        require(all(r[metric] >= minimum for r in runs), f"incomplete simulation: {name}")
        directories = {"prf": "out/prf", "rtl": "out/a1/rtl_sim", "generic": "out/a1/mapped_sim", "timing": "out/a1_timing/mapped_sim"}
        logs = {f"{directories[name]}/seed_{seed}.log" for seed in acceptance["seeds"]}
        fingerprints(receipt["artifacts_sha256"], logs, "artifact")
        for result in runs:
            output = (ROOT / directories[name] / f"seed_{result['seed']}.log").read_text()
            marker = (f"PRF PASS seed={result['seed']} cycles={result['cycles']} reads={result['reads']} bypass_pairs=8/8"
                      if name == "prf" else f"A1 PROBE PASS seed={result['seed']} cases={result['cases']}")
            require(marker in output, "simulation receipt does not match its log")
    require(data["prf"]["duplicate_write_rejected"], "missing duplicate-write check")
    require(set(data["prf"].get("mutations_detected", [])) == {"bypass_lane1", "reset_gate"}, "missing PRF mutations")
    require(set(data["rtl"].get("mutations_detected", [])) == {"duplicate_issue", "unaccepted_wakeup"}, "missing issue mutations")
    for name, group in (("generic", "synthesis"), ("timing", "tops")):
        receipt = data[name]
        require(receipt[group].keys() == TOPS.keys(), "missing synthesis top")
        for top, bits in TOPS.items():
            result = receipt[group][top]
            require(result["stored_bits"] == bits, "wrong storage size")
            prefix = "out/a1" if name == "generic" else "out/a1_timing"
            path = f"{prefix}/{top}/mapped.v"
            fingerprints({path: result["netlist_sha256"]}, {path}, "netlist")
    generic = data["generic"]
    mapped_json = "out/a1/prf_4r2w/mapped.json"
    fingerprints(generic["artifacts_sha256"], {mapped_json}, "artifact")
    ports = json.loads((ROOT / mapped_json).read_text())["modules"]["prf_4r2w"]["ports"]
    expected_ports = {"clk_i": ("input", 1), "rst_i": ("input", 1), "raddr_i": ("input", 24),
                      "rdata_o": ("output", 128), "wb_accept_i": ("input", 2),
                      "waddr_i": ("input", 12), "wdata_i": ("input", 64)}
    require({p: (v["direction"], len(v["bits"])) for p, v in ports.items()} == expected_ports, "PRF port mismatch")
    timing = data["timing"]
    intent = json.loads((ROOT / acceptance["timing_intent"]).read_text())
    require(timing["intent"] == intent, "timing intent mismatch")
    require(0 < intent["period_ns"] <= acceptance["maximum_exploratory_period_ns"], "timing budget relaxed")
    require(timing["library"]["corner"] == acceptance["corner"], "timing corner mismatch")
    require(timing["physical_implementation"] is False, "unsupported physical claim")
    require(set(timing["checks_not_reported_by_tool"]) == {"max_capacitance", "max_fanout"}, "electrical-check scope mismatch")
    require(set(timing["checks_not_reported_by_tool"]) <= set(contract["physical_work_remaining"]), "unassigned electrical checks")
    require(set(timing["controls_detected"]) == {"missing_output_delay", "tight_clock", "tight_slew"}, "missing timing controls")
    for top, result in timing["tops"].items():
        required = {f"out/a1_timing/{top}/{name}.rpt" for name in ("coverage", "setup", "hold", "setup_hold_violations", "slew_violations")}
        fingerprints(timing["artifacts_sha256"], required, "artifact")
        require(result["setup_hold_met"] is True, "timing failed")
        metrics = ["setup_worst_slack_ns", "hold_worst_slack_ns"]
        if top == TOP:
            metrics += ["read_data_worst_slack_ns", "wakeup_read_worst_slack_ns"]
        require(all(math.isfinite(result[k]) and result[k] >= 0 for k in metrics), "negative or invalid timing slack")
        require(all(result[k] == 0 for k in ("setup_tns_ns", "unconstrained_endpoints", "setup_hold_violation_count", "slew_violation_count")), "timing violations or unconstrained endpoints")


def self_test(data: dict, contract: dict) -> None:
    mutations = [
        ("stale source", lambda d: d["rtl"]["inputs_sha256"].update({SOURCES[0]: "0" * 64})),
        ("missing fingerprint", lambda d: d["rtl"]["inputs_sha256"].pop(SOURCES[0])),
        ("missing seed", lambda d: d["timing"]["mapped_simulation"].pop()),
        ("missing simulation log", lambda d: d["timing"]["artifacts_sha256"].pop("out/a1_timing/mapped_sim/seed_1.log")),
        ("inflated simulation count", lambda d: d["timing"]["mapped_simulation"][0].update(cases=999999)),
        ("missing mutation", lambda d: d["prf"]["mutations_detected"].pop()),
        ("negative slack", lambda d: d["timing"]["tops"][TOP].update(setup_worst_slack_ns=-1.0)),
        ("nonfinite slack", lambda d: d["timing"]["tops"][TOP].update(setup_worst_slack_ns=float("nan"))),
        ("unconstrained path", lambda d: d["timing"]["tops"][TOP].update(unconstrained_endpoints=1)),
        ("slew violation", lambda d: d["timing"]["tops"][TOP].update(slew_violation_count=1)),
        ("missing report", lambda d: d["timing"]["artifacts_sha256"].pop(f"out/a1_timing/{TOP}/coverage.rpt")),
        ("stale netlist", lambda d: d["timing"]["tops"][TOP].update(netlist_sha256="0" * 64)),
        ("unassigned electrical check", lambda d: d["timing"]["checks_not_reported_by_tool"].append("unknown")),
    ]
    for name, mutate in mutations:
        changed = copy.deepcopy(data)
        mutate(changed)
        try:
            evaluate(changed, contract)
        except ValueError:
            continue
        raise RuntimeError(f"A1 checker missed {name}")
    for field, value in (("read_latency_cycles", 1), ("write_edge", "falling"), ("physical_gate", "closed")):
        changed = copy.deepcopy(contract)
        changed[field] = value
        try:
            evaluate(data, changed)
        except ValueError:
            continue
        raise RuntimeError(f"A1 checker missed contract change: {field}")
    count = len(mutations) + 3
    print(f"A1 evidence controls: PASS ({count}/{count} rejected)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    output = ROOT / "out/a1/acceptance.json"
    output.unlink(missing_ok=True)
    contract = json.loads((ROOT / "config/prf_contract.json").read_text())
    data = {name: json.loads((ROOT / path).read_text()) for name, path in RECEIPTS.items()}
    evaluate(data, contract)
    if args.self_test:
        self_test(data, contract)
    result = {"schema": 1, "gate": "A1", "status": "pass", "scope": "backend_architecture_feasibility",
              "inputs_sha256": {p: digest(ROOT / p) for p in ["config/prf_contract.json", "tools/check_a1.py", *RECEIPTS.values()]},
              "physical_gate": contract["physical_gate"], "physical_work_remaining": contract["physical_work_remaining"]}
    output.write_text(json.dumps(result, indent=2) + "\n")
    print("A1 feasibility: PASS (combinational PRF reads with accepted-writeback bypass; PHY0 remains open)")


if __name__ == "__main__":
    main()
