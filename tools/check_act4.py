#!/usr/bin/env python3
"""Check the pinned ACT4 harness and its platform-facing values."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def integer(value: str | int) -> int:
    return value if isinstance(value, int) else int(value, 0)


def simple_yaml(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def reference(lock: dict, name: str) -> dict:
    return next(item for item in lock["references"] if item["name"] == name)


def csr(platform: dict, name: str) -> dict:
    return next(item for item in platform["csrs"] if item["name"] == name)


def region_view(item: dict) -> tuple[int, int, bool, bool, bool, bool, bool]:
    attributes = item["attributes"]
    return (
        integer(item["base"]["value"]),
        integer(item["size"]["value"]),
        attributes["readable"],
        attributes["writable"],
        attributes["executable"],
        attributes["cacheable"],
        attributes["read_idempotent"] and attributes["write_idempotent"],
    )


def check_harness() -> tuple[dict, dict]:
    refs = json.loads((ROOT / "config/references.lock").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "config/act4.lock").read_text(encoding="utf-8"))
    platform = json.loads((ROOT / "config/platform.yaml").read_text(encoding="utf-8"))
    suite = reference(refs, lock["suite"]["reference"])
    require(lock["schema"] == 1 and suite["version"] == lock["suite"]["version"], "ACT4 lock mismatch")
    require(suite["revision"] == lock["suite"]["ctp_revision"], "ACT and CTP revisions differ")

    harness = ROOT / lock["harness"]["directory"]
    required = set(lock["harness"]["required_files"])
    require(all((harness / name).is_file() for name in required), "ACT4 harness is incomplete")
    legacy = {"config.ini", "riscof.ini", "riscof"}
    require(not (legacy & {path.name for path in harness.iterdir()}), "legacy ACT file found")

    top = simple_yaml(harness / lock["harness"]["config"])
    require(top["name"] == platform["name"], "ACT config name differs from platform")
    require(top["udb_config"] == "spec_ooo_rv32i.yaml", "ACT UDB path is unexpected")
    require(top["linker_script"] == "link.ld" and top["dut_include_dir"] == ".", "ACT input paths are unexpected")
    require(
        top["ref_model_type"] == "sail" and top["include_priv_tests"] == "true",
        "ACT model or privilege selection differs",
    )

    udb = json.loads((harness / top["udb_config"]).read_text(encoding="utf-8"))
    params = udb["params"]
    extensions = {item["name"] for item in udb["implemented_extensions"]}
    expected_udb_extensions = {platform["isa"]["base"][4:], *platform["isa"]["extensions"], "Sm"}
    require(extensions == expected_udb_extensions, "UDB extension set differs")
    require(
        params["MXLEN"] == platform["xlen"]
        and params["M_MODE_ENDIANNESS"] == platform["isa"]["endianness"],
        "UDB base differs",
    )
    require(params["ARCH_ID_VALUE"] == integer(csr(platform, "marchid")["reset"]), "UDB marchid differs")
    require(params["IMP_ID_VALUE"] == integer(csr(platform, "mimpid")["reset"]), "UDB mimpid differs")
    require(
        params["VENDOR_ID_BANK"] == 0
        and params["VENDOR_ID_OFFSET"] == 0
        and integer(csr(platform, "mvendorid")["reset"]) == 0,
        "UDB vendor ID differs",
    )
    inhibit_mask = integer(csr(platform, "mcountinhibit")["write_mask"])
    expected_inhibit = [bool(inhibit_mask & (1 << bit)) for bit in range(32)]
    require(params["COUNTINHIBIT_EN"] == expected_inhibit, "UDB counter inhibit differs")
    require(params["MTVEC_MODES"] == [0] and params["MTVEC_BASE_ALIGNMENT_DIRECT"] == 4, "UDB mtvec policy differs")
    require(params["NUM_PMP_ENTRIES"] == 0 and not params["MISALIGNED_LDST"], "UDB memory policy differs")

    sail = json.loads((harness / "sail.json").read_text(encoding="utf-8"))
    require(sail["base"]["xlen"] == platform["xlen"] and not sail["base"]["writable_misa"], "Sail base differs")
    enabled = {name for name, settings in sail["extensions"].items() if settings.get("supported") is True}
    require(enabled == set(platform["isa"]["extensions"]), "Sail extension set differs")
    line_size_exp = integer(platform["memory"]["line_bytes"]).bit_length() - 1
    require(sail["platform"]["cache_block_size_exp"] == line_size_exp, "Sail line size differs")
    expected_regions = [
        (
            integer(item["base"]),
            integer(item["size"]),
            item["read"],
            item["write"],
            item["execute"],
            item["cacheable"],
            item["idempotent"],
        )
        for item in platform["memory"]["regions"]
    ]
    require([region_view(item) for item in sail["memory"]["regions"]] == expected_regions, "Sail memory map differs")

    linker = (harness / "link.ld").read_text(encoding="utf-8")
    bram = next(item for item in platform["memory"]["regions"] if item["name"] == "bram")
    bram_base = integer(bram["base"])
    bram_end = bram_base + integer(bram["size"])
    require("ENTRY(rvtest_entry_point)" in linker and f". = 0x{bram_base:08x};" in linker, "ACT linker entry differs")
    require(f"_end <= 0x{bram_end:08x}" in linker and "*(.tohost)" in linker, "ACT linker BRAM or tohost differs")
    macros = (harness / "rvmodel_macros.h").read_text(encoding="utf-8")
    require(
        "RVMODEL_HALT_PASS" in macros and "RVMODEL_HALT_FAIL" in macros and "tohost" in macros,
        "ACT termination macros differ",
    )
    require(
        "RVMODEL_SET_MEXT_INT" not in macros and "RVMODEL_MTIME_ADDRESS" not in macros,
        "disabled interrupt feature is present",
    )
    svh = (harness / "rvtest_config.svh").read_text(encoding="utf-8")
    require(f"`define XLEN{platform['xlen']}" in svh, "ACT coverage XLEN differs")
    require("RVMODEL_NUM_PMPS 0" in (harness / "rvtest_config.h").read_text(encoding="utf-8"), "ACT PMP count differs")
    return lock, suite


def git_value(checkout: Path, expression: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", expression], cwd=checkout, check=True, text=True, capture_output=True
    ).stdout.strip()


def check_upstream(checkout: Path, lock: dict, suite: dict) -> None:
    require(git_value(checkout, "HEAD") == suite["revision"], "ACT4 checkout revision differs")
    require(git_value(checkout, "HEAD^{tree}") == suite["tree"], "ACT4 checkout tree differs")
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=checkout, check=True, text=True, capture_output=True
    ).stdout
    require(not status, "ACT4 checkout is modified")
    upstream_files = [
        "README.md",
        "Makefile",
        ".mise.toml",
        "uv.lock",
        "framework/pyproject.toml",
        "framework/src/act/data/Gemfile.lock",
    ]
    example = checkout / lock["harness"]["upstream_example"]
    require(all((checkout / name).is_file() for name in upstream_files), "ACT4 upstream inputs are incomplete")
    example_config = simple_yaml(example / "test_config.yaml")
    example_files = {
        "test_config.yaml",
        example_config["udb_config"],
        "rvmodel_macros.h",
        "link.ld",
        "sail.json",
        "rvtest_config.svh",
        "rvtest_config.h",
    }
    require(all((example / name).is_file() for name in example_files), "ACT4 upstream harness shape differs")
    uv_hash = hashlib.sha256((checkout / "uv.lock").read_bytes()).hexdigest()
    require(uv_hash == lock["tools"]["uv_lock_sha256"], "ACT4 uv lock differs")
    gem_lock = checkout / "framework/src/act/data/Gemfile.lock"
    gem_hash = hashlib.sha256(gem_lock.read_bytes()).hexdigest()
    require(gem_hash == lock["tools"]["udb_lock_sha256"], "ACT4 UDB lock differs")
    require(f"udb ({lock['tools']['udb_gem']})" in gem_lock.read_text(encoding="utf-8"), "ACT4 UDB version differs")
    readme = (checkout / "README.md").read_text(encoding="utf-8")
    makefile = (checkout / "Makefile").read_text(encoding="utf-8")
    require("ACT4 Framework" in readme and "replaces the deprecated riscof tool" in readme, "ACT4 generation differs")
    require("act $(CONFIG_FILES)" in makefile and ".DEFAULT_GOAL := elfs" in makefile, "ACT4 runner shape differs")


def check_sail(executable: Path, lock: dict) -> None:
    version = subprocess.run([executable, "--version"], check=True, text=True, capture_output=True).stdout.strip()
    require(version == lock["tools"]["sail_riscv"], "Sail version differs")
    subprocess.run(
        [executable, "--config", ROOT / lock["harness"]["directory"] / "sail.json", "--validate-config"],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path)
    parser.add_argument("--sail", type=Path)
    args = parser.parse_args()
    lock, suite = check_harness()
    if args.checkout:
        check_upstream(args.checkout.resolve(), lock, suite)
    if args.sail:
        check_sail(args.sail.resolve(), lock)
    print("ACT4 harness: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
