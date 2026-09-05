#!/usr/bin/env python3
"""Run the pinned Spike and Verilator lockstep smoke fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out/lockstep"
sys.path.insert(0, str(ROOT))

from model.iss.spike_log import parse_spike_log
from verif.lockstep.comparator import compare_traces, parse_verilator_trace, verify_required_mutations


def run(command: list[str]) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}")
    return result.stdout


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_spike(spike: Path) -> str:
    references = json.loads((ROOT / "config/references.lock").read_text(encoding="utf-8"))
    matches = [item for item in references["references"] if item["name"] == "riscv-isa-sim"]
    if len(matches) != 1:
        raise RuntimeError("references.lock must contain one riscv-isa-sim entry")
    locked = matches[0]
    if not spike.is_file() or file_sha256(spike) != locked["binary_sha256"]:
        raise RuntimeError("Spike executable is missing or does not match its locked hash")
    source = spike.parent.parent
    revision = run(["git", "-C", str(source), "rev-parse", "HEAD"]).strip()
    tree = run(["git", "-C", str(source), "rev-parse", "HEAD^{tree}"]).strip()
    if revision != locked["revision"] or tree != locked["tree"]:
        raise RuntimeError("Spike source checkout does not match references.lock")
    return revision


def platform_bram() -> tuple[int, int]:
    platform = json.loads((ROOT / "config/platform.yaml").read_text(encoding="utf-8"))
    bram = next(region for region in platform["memory"]["regions"] if region["name"] == "bram")
    base = int(bram["base"], 0)
    size = int(bram["size"], 0)
    if base != 0 or int(platform["reset"]["pc"], 0) != base:
        raise RuntimeError("lockstep smoke relocation expects BRAM and reset at zero")
    return base, size


def smoke_config() -> dict:
    config = json.loads((ROOT / "config/lockstep_smoke.yaml").read_text(encoding="utf-8"))
    expected = {
        "schema": 1,
        "name": "spike_verilator_lockstep_smoke_v0",
        "program": "sw/tests/lockstep_hello.S",
        "target_events": 5,
        "spike_boot_events": 5,
        "spike_memory_base": "0x80000000",
        "address_mapping": "Subtract spike_memory_base from program PCs before comparison.",
        "scope": "Toolchain, adapter, event packing, comparator, and mutation smoke only.",
        "limitation": "The pinned stock Spike reserves low addresses, so this smoke relocates BRAM without claiming full platform lockstep.",
    }
    if config != expected:
        raise RuntimeError("lockstep smoke configuration does not match v0")
    return config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spike", type=Path, required=True)
    parser.add_argument("--compiler", default="riscv64-unknown-elf-gcc")
    parser.add_argument("--objcopy", default="riscv64-unknown-elf-objcopy")
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    spike = args.spike.resolve()
    revision = verify_spike(spike)
    _, bram_size = platform_bram()
    smoke = smoke_config()
    spike_base = int(smoke["spike_memory_base"], 0)
    OUT.mkdir(parents=True, exist_ok=True)

    platform_elf = OUT / "lockstep_hello.elf"
    spike_elf = OUT / "lockstep_hello_spike.elf"
    run([
        args.compiler,
        "-march=rv32i",
        "-mabi=ilp32",
        "-nostdlib",
        "-nostartfiles",
        "-Wl,--no-relax,--build-id=none",
        "-T",
        "sw/link/platform.ld",
        smoke["program"],
        "-o",
        str(platform_elf),
    ])
    run([
        args.objcopy,
        f"--change-addresses=0x{spike_base:08x}",
        str(platform_elf),
        str(spike_elf),
    ])
    spike_output = run([
        str(spike),
        "--isa=rv32i_zicsr_zifencei",
        "--priv=m",
        "--pmpregions=0",
        f"--instructions={smoke['spike_boot_events'] + smoke['target_events']}",
        "-l",
        "--log-commits",
        f"-m0x{spike_base:08x}:0x{bram_size:x}",
        str(spike_elf),
    ])
    expected = parse_spike_log(spike_output, spike_base, bram_size)
    event_count = len([event for packet in expected for event in packet["slots"] if event])
    if event_count != smoke["target_events"]:
        raise RuntimeError(f"Spike smoke produced {event_count} program events")

    object_dir = OUT / "obj_dir"
    run([
        args.verilator,
        "--binary",
        "--build-jobs",
        "0",
        "--Mdir",
        str(object_dir),
        "--top-module",
        "lockstep_smoke",
        "rtl/generated/commit_event_pkg.sv",
        "verif/lockstep/rtl/lockstep_smoke.sv",
        "-o",
        "lockstep_smoke",
    ])
    actual = parse_verilator_trace(run([str(object_dir / "lockstep_smoke")]))
    compare_traces(expected, actual)
    caught = verify_required_mutations(
        expected,
        ROOT / "verif/lockstep/vectors/commit_event_cases.json",
    )
    print(
        f"lockstep smoke: PASS ({event_count} events, "
        f"{len(caught)}/{len(caught)} mutations, Spike {revision[:12]})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
