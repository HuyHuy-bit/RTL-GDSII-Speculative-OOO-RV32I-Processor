#!/usr/bin/env python3
"""Validate the tracked S0 bootstrap contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SHA1 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def main() -> int:
    references = json.loads((ROOT / "config/references.lock").read_text(encoding="utf-8"))
    toolchain = json.loads((ROOT / "config/toolchain.lock").read_text(encoding="utf-8"))
    assert references["schema"] == 1
    assert toolchain["schema"] == 1

    upstream = references["references"][0]
    assert SHA1.fullmatch(upstream["revision"])
    assert SHA1.fullmatch(upstream["tree"])
    assert SHA256.fullmatch(upstream["license_sha256"])
    license_hash = hashlib.sha256((ROOT / "LICENSE").read_bytes()).hexdigest()
    assert license_hash == upstream["license_sha256"]

    private_plan = references["references"][1]
    assert SHA256.fullmatch(private_plan["sha256"])
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "docs_plan/README.md"], cwd=ROOT, check=False
    )
    assert ignored.returncode == 0
    print("S0 contracts: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
