#!/usr/bin/env python3
"""Check the tools pinned by a named host profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    if lock["profile"] != args.profile:
        print(f"profile mismatch: requested {args.profile}, lock is {lock['profile']}")
        return 1

    failed = False
    for tool in lock["tools"]:
        executable = shutil.which(tool["command"])
        if executable is None:
            state = "FAIL" if tool["required"] else "OPTIONAL"
            print(f"{state:8} {tool['name']}: not found")
            failed |= tool["required"]
            continue
        result = subprocess.run(
            [executable, *tool["args"]],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            check=False,
        )
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        observed = lines[0] if lines else "no version output"
        expected = tool.get("expected_first_line")
        matches = result.returncode == 0 and (expected is None or observed == expected)
        state = "PASS" if matches else ("FAIL" if tool["required"] else "OPTIONAL")
        print(f"{state:8} {tool['name']}: {observed}")
        failed |= tool["required"] and not matches
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
