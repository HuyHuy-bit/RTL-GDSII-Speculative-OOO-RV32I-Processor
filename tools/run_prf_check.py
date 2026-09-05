#!/usr/bin/env python3
"""Lint and exercise the standalone PRF under Verilator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out/prf"


def run(command: list[str], log: str, *, expected_failure: str | None = None) -> str:
    result = subprocess.run(
        command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=180,
    )
    (OUT / log).write_text(result.stdout, encoding="utf-8")
    if expected_failure:
        passed = result.returncode != 0 and expected_failure in result.stdout
    else:
        passed = result.returncode == 0
    if not passed:
        raise RuntimeError(f"command failed: {' '.join(command)}\n{result.stdout}")
    return result.stdout


def build(rtl: str, directory: Path, log: str) -> str:
    run([
        "verilator", "--cc", "--exe", "--build", "--build-jobs", "2", "--Wall", "--assert",
        "--x-initial", "unique", "--top-module", "prf_4r2w", "--Mdir", str(directory),
        "-CFLAGS", "-std=c++17 -Wall -Wextra -Werror", rtl,
        str(ROOT / "verif/unit/prf_4r2w_tb.cpp"), "-o", "prf_check",
    ], log)
    return str(directory / "prf_check")


def check_mutations(rtl: Path) -> None:
    source = rtl.read_text(encoding="utf-8")
    mutations = {
        "bypass_lane1": (
            "value = wdata_i[32 +: 32];", "value = payload_q[address];", "bypass mismatch",
        ),
        "reset_gate": (
            "if (write_en[0] && waddr_i[0 +: 6] == 6'(entry))",
            "if (wb_accept_i[0] && waddr_i[0 +: 6] == 6'(entry))",
            "stored mismatch",
        ),
    }
    for name, (old, new, failure) in mutations.items():
        if source.count(old) != 1:
            raise RuntimeError(f"mutation {name} no longer matches its source")
        directory = OUT / "mutations" / name
        directory.mkdir(parents=True, exist_ok=True)
        changed = directory / rtl.name
        changed.write_text(source.replace(old, new), encoding="utf-8")
        executable = build(str(changed), directory / "obj_dir", f"{name}_build.log")
        run([executable, "1"], f"{name}.log", expected_failure=failure)
        print(f"PRF mutation {name}: PASS (fault detected)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mutations", action="store_true")
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    OUT.mkdir(parents=True, exist_ok=True)
    lock = json.loads((ROOT / "config/toolchain.lock").read_text(encoding="utf-8"))
    tool = next(item for item in lock["tools"] if item["name"] == "verilator")
    version = run(["verilator", "--version"], "version.log").strip()
    if version != tool["expected_first_line"]:
        raise RuntimeError("Verilator does not match config/toolchain.lock")

    rtl = "rtl/backend/prf_4r2w.sv"
    run(["verilator", "--lint-only", "--Wall", "--assert", rtl], "lint.log")
    executable = build(rtl, OUT / "obj_dir", "build.log")
    for seed in (1, 42, 20260905):
        output = run([
            executable, str(seed), "+verilator+rand+reset+2", f"+verilator+seed+{seed}",
        ], f"seed_{seed}.log")
        if "PRF PASS" not in output:
            raise RuntimeError("PRF simulation exited without its completion marker")
        print(output.strip())
    run([executable, "--duplicate-write"], "duplicate_write.log",
        expected_failure="PRF_DUPLICATE_WRITE")
    print("PRF duplicate-write assertion: PASS (injected collision rejected)")
    if args.mutations:
        check_mutations(ROOT / rtl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
