#!/usr/bin/env python3
"""Check the A1 allocation/issue experiment and optionally map generic gates."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out/a1"
TOP = "a1_backend_probe"
SOURCES = [
    "rtl/backend/prf_4r2w.sv",
    "synth/experiments/a1_select_probe.sv",
    "synth/experiments/a1_backend_probe.sv",
]
SEEDS = (1, 42, 20260905)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], log: Path, failure: str | None = None) -> str:
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=300)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout, encoding="utf-8")
    passed = result.returncode != 0 and failure in result.stdout if failure else result.returncode == 0
    if not passed:
        raise RuntimeError(f"command failed; see {log.relative_to(ROOT)}\n{result.stdout[-5000:]}")
    return result.stdout


def build(sources: list[str], directory: Path, *, mapped: bool = False) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    flags = ["-Wno-UNUSEDSIGNAL", "-Wno-DECLFILENAME"] if mapped else []
    run([
        "verilator", "--cc", "--exe", "--build", "--build-jobs", "2", "--Wall", "--assert",
        "--x-initial", "unique", "--top-module", TOP, "--Mdir", str(directory / "obj_dir"),
        *flags, "-CFLAGS", "-std=c++17 -Wall -Wextra -Werror", *sources,
        str(ROOT / "verif/unit/a1_backend_probe_tb.cpp"), "-o", "probe_check",
    ], directory / "build.log")
    return directory / "obj_dir/probe_check"


def simulate(executable: Path) -> list[dict]:
    results = []
    for seed in SEEDS:
        output = run([str(executable), str(seed), "+verilator+rand+reset+2",
                      f"+verilator+seed+{seed}"], executable.parent.parent / f"seed_{seed}.log")
        match = re.search(rf"A1 PROBE PASS seed={seed} cases=(\d+)", output)
        if not match:
            raise RuntimeError("simulation did not reach its completion marker")
        results.append({"seed": seed, "cases": int(match[1])})
        print(output.strip(), flush=True)
    return results


def mutations() -> None:
    source = (ROOT / SOURCES[1]).read_text(encoding="utf-8")
    changes = {
        "duplicate_issue": ("& ~chosen0;", "& 16'hffff;"),
        "unaccepted_wakeup": ("wb_accept_i[1] && wb_addr_i", "(|wb_accept_i) && wb_addr_i"),
    }
    for name, (old, new) in changes.items():
        if source.count(old) != 1:
            raise RuntimeError(f"mutation {name} no longer matches")
        directory = OUT / "mutations" / name
        directory.mkdir(parents=True, exist_ok=True)
        changed = directory / "a1_select_probe.sv"
        changed.write_text(source.replace(old, new), encoding="utf-8")
        executable = build([SOURCES[0], str(changed), SOURCES[2]], directory)
        run([str(executable), "1"], directory / "check.log", failure="grant mismatch")
        print(f"A1 mutation {name}: PASS (fault detected)", flush=True)


def verify_synthesis_suite(suite: Path) -> str:
    lock = json.loads((ROOT / "config/synthesis.lock").read_text(encoding="utf-8"))
    for filename, expected in lock["sha256"].items():
        if digest(suite / filename) != expected:
            raise RuntimeError(f"synthesis tool mismatch: {filename}")
    yosys = str(suite / "bin/yosys")
    version = run([yosys, "--version"], OUT / "synthesis_version.log").strip()
    if version != lock["yosys_version"]:
        raise RuntimeError("Yosys does not match config/synthesis.lock")
    return yosys


def synthesize(suite: Path) -> dict:
    yosys = verify_synthesis_suite(suite)
    metrics = {}
    for top, sources, expected_bits in (
        ("prf_4r2w", SOURCES[:1], 2016),
        ("a1_select_probe", SOURCES[1:2], 0),
        (TOP, SOURCES, 2016),
    ):
        directory = OUT / top
        directory.mkdir(parents=True, exist_ok=True)
        prefix = directory.relative_to(ROOT)
        script = (
            f"read_slang --top {top} -D SYNTHESIS {' '.join(sources)}; "
            f"synth -top {top} -flatten; clean -purge; check -assert; ltp -noff; "
            f"write_json {prefix}/mapped.json; write_verilog -noattr {prefix}/mapped.v"
        )
        (directory / "synth.ys").write_text(script + "\n", encoding="utf-8")
        output = run([yosys, "-Q", "-T", "-m", "slang", "-s", str(directory / "synth.ys")],
                     directory / "synth.log")
        module = json.loads((directory / "mapped.json").read_text())["modules"][top]
        counts = Counter(cell["type"] for cell in module["cells"].values())
        supported = {"$_NOT_", "$_AND_", "$_OR_", "$_XOR_", "$_XNOR_", "$_ANDNOT_",
                     "$_ORNOT_", "$_NAND_", "$_NOR_", "$_MUX_", "$_DFFE_PP_", "$_DFF_P_"}
        if set(counts) - supported or module.get("memories"):
            raise RuntimeError(f"unexpected mapped cells in {top}: {counts}")
        bits = counts["$_DFFE_PP_"] + counts["$_DFF_P_"]
        if bits != expected_bits:
            raise RuntimeError(f"unexpected stored bits in {top}: {bits}")
        match = re.search(r"Longest topological path .*?\(length=(\d+)\)", output)
        if not match:
            raise RuntimeError(f"missing logic depth in {top}")
        metrics[top] = {"cells": dict(sorted(counts.items())), "total_cells": sum(counts.values()),
                        "stored_bits": bits, "logic_depth_levels": int(match[1]),
                        "netlist_sha256": digest(directory / "mapped.v")}
        print(f"A1 synthesis {top}: {sum(counts.values())} generic cells, "
              f"{bits} stored bits, {match[1]} logic levels", flush=True)
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--synth", action="store_true")
    parser.add_argument("--mutations", action="store_true")
    parser.add_argument("--suite", type=Path,
                        default=Path.home() / "tools/oss-cad-suite-20260905/oss-cad-suite")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    receipt_path = OUT / ("synthesis_receipt.json" if args.synth else "rtl_receipt.json")
    if args.mutations:
        receipt_path = receipt_path.with_name(receipt_path.stem + "_mutations.json")
    receipt_path.unlink(missing_ok=True)
    lock = json.loads((ROOT / "config/toolchain.lock").read_text())
    expected = next(tool["expected_first_line"] for tool in lock["tools"] if tool["name"] == "verilator")
    if run(["verilator", "--version"], OUT / "verilator_version.log").strip() != expected:
        raise RuntimeError("Verilator does not match config/toolchain.lock")
    inputs = SOURCES + ["verif/unit/a1_backend_probe_tb.cpp", "tools/run_a1_probe.py",
                       "config/toolchain.lock", "config/synthesis.lock", "config/prf_contract.json"]
    receipt = {"schema": 1, "inputs_sha256": {path: digest(ROOT / path) for path in inputs},
               "timing_evaluated": False, "cell_library": None,
               "scope": "Combinational candidate allocation and age-ordered greedy issue with PRF",
               "exclusions": ["free-list ownership and recovery", "IQ storage and age ordering",
                              "register-ready state", "rename and ROB", "placement and routing",
                              "clock constraints and cell-library timing"]}
    if args.synth:
        receipt["synthesis"] = synthesize(args.suite.resolve())
        executable = build([str(OUT / TOP / "mapped.v")], OUT / "mapped_sim", mapped=True)
        receipt["mapped_simulation"] = simulate(executable)
    else:
        executable = build(SOURCES, OUT / "rtl_sim")
        receipt["rtl_simulation"] = simulate(executable)
    if args.mutations:
        mutations()
        receipt["mutations_detected"] = ["duplicate_issue", "unaccepted_wakeup"]
    simulation_dir = OUT / ("mapped_sim" if args.synth else "rtl_sim")
    artifacts = [simulation_dir / f"seed_{seed}.log" for seed in SEEDS]
    if args.synth:
        artifacts += [OUT / top / "mapped.json" for top in receipt["synthesis"]]
        artifacts += [OUT / top / "mapped.v" for top in receipt["synthesis"]]
    if args.mutations:
        artifacts += [OUT / "mutations" / name / "check.log" for name in receipt["mutations_detected"]]
    receipt["artifacts_sha256"] = {str(path.relative_to(ROOT)): digest(path) for path in artifacts}
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
