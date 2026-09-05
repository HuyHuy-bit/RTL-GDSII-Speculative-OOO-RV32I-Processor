#!/usr/bin/env python3
"""Fetch the pinned timing package and library into ignored local storage."""

import json
from pathlib import Path
import subprocess
from urllib.request import urlopen

from run_a1_probe import ROOT, digest


DEPS = ROOT / "out/deps/a1_timing"


def verify() -> dict:
    lock = json.loads((ROOT / "config/a1_timing.lock").read_text())
    expected = {name: item["sha256"] for name, item in lock["downloads"].items()}
    expected.update(lock["installed_sha256"])
    for name, sha256 in expected.items():
        if not (DEPS / name).is_file() or digest(DEPS / name) != sha256:
            raise RuntimeError(f"timing dependency missing or mismatched: {name}; run make a1-timing-fetch")
    return lock


def main() -> None:
    lock = json.loads((ROOT / "config/a1_timing.lock").read_text())
    DEPS.mkdir(parents=True, exist_ok=True)
    for name, item in lock["downloads"].items():
        path = DEPS / name
        if path.is_file() and digest(path) == item["sha256"]:
            continue
        temporary = path.with_suffix(path.suffix + ".part")
        with urlopen(item["url"], timeout=60) as response:
            temporary.write_bytes(response.read())
        if digest(temporary) != item["sha256"]:
            temporary.unlink()
            raise RuntimeError(f"download hash mismatch: {name}")
        temporary.replace(path)
    subprocess.run(["dpkg-deb", "-x", str(DEPS / "opensta.deb"), str(DEPS / "opensta")], check=True)
    verify()
    print("A1 timing dependencies: PASS")


if __name__ == "__main__":
    main()
