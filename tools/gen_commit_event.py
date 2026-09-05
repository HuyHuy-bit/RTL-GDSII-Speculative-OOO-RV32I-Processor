#!/usr/bin/env python3
"""Validate the commit-event source and render its consumed types."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import textwrap


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = (
    "rtl/generated/commit_event_pkg.sv",
    "verif/lockstep/generated/commit_event.py",
)
SHA1 = re.compile(r"[0-9a-f]{40}\Z")
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*\Z")


def integer(value: str | int) -> int:
    return value if isinstance(value, int) else int(value, 0)


def validate(config: dict) -> None:
    if config["schema"] != 1 or config["name"] != "commit_event_v0":
        raise ValueError("event schema identity must be commit_event_v0 schema 1")
    if config["slots"] != 2 or config["max_csr_effects"] != 4:
        raise ValueError("baseline requires two slots and four CSR effects")

    expected_slot = {
        "valid": 1, "order": 64, "instruction": 32, "privilege": 2,
        "pc_before": 32, "pc_after": 32, "rs1_addr": 5, "rs1_value": 32,
        "rs2_addr": 5, "rs2_value": 32, "rd_addr": 5, "rd_value": 32,
        "rd_write_mask": 32, "trap": 1, "trap_cause": 32, "trap_value": 32,
        "retired": 1, "mem_valid": 1, "mem_address": 32,
        "mem_read_mask": 4, "mem_write_mask": 4, "mem_read_data": 32,
        "mem_write_data": 32,
    }
    expected_csr = {
        "valid": 1, "address": 12, "old_value": 32, "new_value": 32,
        "read_mask": 32, "write_mask": 32, "mask_reason": 3,
    }
    for key, expected in (("slot_fields", expected_slot), ("csr_fields", expected_csr)):
        fields = config[key]
        actual = {field["name"]: field["width"] for field in fields}
        if len(actual) != len(fields) or actual != expected:
            raise ValueError(f"{key} names and widths do not match event v0")
        if any(not IDENTIFIER.fullmatch(field["name"]) for field in fields):
            raise ValueError(f"{key} contains an invalid identifier")

    reasons = config["csr_mask_reasons"]
    if reasons != {"none": 0, "instruction": 1, "trap_entry": 2, "mret": 3}:
        raise ValueError("CSR mask reasons do not match event v0")
    trap_csrs = [integer(address) for address in config["trap_entry_csrs"]]
    if trap_csrs != [0x300, 0x341, 0x342, 0x343]:
        raise ValueError("trap-entry CSR order does not match event v0")

    lane_text = "Mask bit n selects byte n of the aligned 32-bit word; selected data byte n occupies bits 8*n+7:8*n."
    if config["memory_lane_convention"] != lane_text:
        raise ValueError("memory lane convention does not match event v0")

    rvfi = config["rvfi"]
    if rvfi["repository"] != "https://github.com/YosysHQ/riscv-formal.git":
        raise ValueError("RVFI repository is not canonical")
    if not SHA1.fullmatch(rvfi["revision"]):
        raise ValueError("RVFI revision must be a full Git commit")
    if rvfi["document"] != "docs/source/rvfi.rst":
        raise ValueError("RVFI document path does not match the pinned interface")
    expected_mapping = {
        "valid": "rvfi_valid", "order": "rvfi_order", "instruction": "rvfi_insn",
        "trap": "rvfi_trap", "privilege": "rvfi_mode", "pc_before": "rvfi_pc_rdata",
        "pc_after": "rvfi_pc_wdata", "rs1_addr": "rvfi_rs1_addr",
        "rs1_value": "rvfi_rs1_rdata", "rs2_addr": "rvfi_rs2_addr",
        "rs2_value": "rvfi_rs2_rdata", "rd_addr": "rvfi_rd_addr",
        "rd_value": "rvfi_rd_wdata", "mem_address": "rvfi_mem_addr",
        "mem_read_mask": "rvfi_mem_rmask", "mem_write_mask": "rvfi_mem_wmask",
        "mem_read_data": "rvfi_mem_rdata", "mem_write_data": "rvfi_mem_wdata",
    }
    if rvfi["mapping"] != expected_mapping:
        raise ValueError("RVFI mapping does not match event v0")
    if len(rvfi["deviations"]) < 8 or any(not item.strip() for item in rvfi["deviations"]):
        raise ValueError("RVFI deviations must be explicit")


def validate_dependencies(config: dict) -> None:
    references = json.loads((ROOT / "config/references.lock").read_text(encoding="utf-8"))
    matches = [item for item in references["references"] if item["name"] == "riscv-formal-rvfi"]
    rvfi = config["rvfi"]
    if (len(matches) != 1 or matches[0]["url"] != rvfi["repository"]
            or matches[0]["revision"] != rvfi["revision"]
            or matches[0]["document"] != rvfi["document"]):
        raise ValueError("event schema and locked RVFI reference disagree")

    platform = json.loads((ROOT / "config/platform.yaml").read_text(encoding="utf-8"))
    csr_addresses = {integer(csr["address"]) for csr in platform["csrs"]}
    if any(integer(address) not in csr_addresses for address in config["trap_entry_csrs"]):
        raise ValueError("event schema names a CSR absent from the platform")


def sv_field(name: str, width: int) -> str:
    kind = "logic" if width == 1 else f"logic [{width - 1}:0]"
    return f"    {kind} {name};"


def render_sv(config: dict, digest: str) -> str:
    reason_width = next(field["width"] for field in config["csr_fields"] if field["name"] == "mask_reason")
    lines = [
        "`default_nettype none",
        "package commit_event_pkg;",
        f'  localparam string COMMIT_EVENT_SHA256 = "{digest}";',
        f"  localparam int unsigned COMMIT_SLOTS = {config['slots']};",
        f"  localparam int unsigned COMMIT_CSR_EFFECTS = {config['max_csr_effects']};",
        f"  typedef enum logic [{reason_width - 1}:0] {{",
    ]
    reasons = list(config["csr_mask_reasons"].items())
    for index, (name, value) in enumerate(reasons):
        comma = "," if index + 1 < len(reasons) else ""
        lines.append(f"    CSR_MASK_{name.upper()} = {reason_width}'d{value}{comma}")
    lines.extend(["  } csr_mask_reason_e;", "  typedef struct packed {"])
    for field in config["csr_fields"]:
        if field["name"] == "mask_reason":
            lines.append("    csr_mask_reason_e mask_reason;")
        else:
            lines.append(sv_field(field["name"], field["width"]))
    lines.extend(["  } commit_csr_effect_t;", "  typedef struct packed {"])
    lines.extend(sv_field(field["name"], field["width"]) for field in config["slot_fields"])
    lines.append("    commit_csr_effect_t [COMMIT_CSR_EFFECTS-1:0] csr_effects;")
    lines.extend([
        "  } commit_event_t;",
        "  typedef struct packed {",
        "    commit_event_t [COMMIT_SLOTS-1:0] slots;",
        "  } commit_packet_t;",
        "endpackage",
        "`default_nettype wire",
        "",
    ])
    return "\n".join(lines)


def render_python(config: dict, digest: str) -> str:
    slot_widths = {field["name"]: field["width"] for field in config["slot_fields"]}
    csr_widths = {field["name"]: field["width"] for field in config["csr_fields"]}
    slot_members = "\n".join(f"    {name}: int = 0" for name in slot_widths)
    csr_members = "\n".join(f"    {name}: int = 0" for name in csr_widths)
    body = f'''\
#!/usr/bin/env python3
"""Generated commit-event types and structural validator."""

from __future__ import annotations

from dataclasses import dataclass, field


SOURCE_SHA256 = {digest!r}
COMMIT_SLOTS = {config['slots']}
MAX_CSR_EFFECTS = {config['max_csr_effects']}
SLOT_FIELD_WIDTHS = {slot_widths!r}
CSR_FIELD_WIDTHS = {csr_widths!r}
CSR_MASK_REASONS = {config['csr_mask_reasons']!r}
TRAP_ENTRY_CSRS = {tuple(integer(value) for value in config['trap_entry_csrs'])!r}


class EventValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CsrEffect:
{csr_members}


@dataclass(frozen=True)
class CommitEvent:
{slot_members}
    csr_effects: tuple[CsrEffect, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CommitPacket:
    slots: tuple[CommitEvent, ...]


def _known(data: dict, allowed: set[str], context: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise EventValidationError(f"{{context}} has unknown fields: {{sorted(unknown)}}")


def _bounded(value: object, width: int, context: str) -> int:
    if type(value) not in (int, bool):
        raise EventValidationError(f"{{context}} must be an integer")
    result = int(value)
    if result < 0 or result >= 1 << width:
        raise EventValidationError(f"{{context}} exceeds {{width}} bits")
    return result


def csr_from_dict(data: dict) -> CsrEffect:
    _known(data, set(CSR_FIELD_WIDTHS), "CSR effect")
    values = {{name: _bounded(data.get(name, 0), width, f"CSR {{name}}")
               for name, width in CSR_FIELD_WIDTHS.items() if name != "mask_reason"}}
    values["valid"] = _bounded(data.get("valid", 1), 1, "CSR valid")
    reason = data.get("mask_reason", 0)
    if isinstance(reason, str):
        if reason not in CSR_MASK_REASONS:
            raise EventValidationError(f"unknown CSR mask reason: {{reason}}")
        values["mask_reason"] = CSR_MASK_REASONS[reason]
    else:
        values["mask_reason"] = _bounded(reason, CSR_FIELD_WIDTHS["mask_reason"], "CSR mask_reason")
    if values["mask_reason"] not in CSR_MASK_REASONS.values():
        raise EventValidationError(f"unknown CSR mask reason: {{values['mask_reason']}}")
    return CsrEffect(**values)


def event_from_dict(data: dict) -> CommitEvent:
    _known(data, set(SLOT_FIELD_WIDTHS) | {{"csr_effects"}}, "event")
    values = {{name: _bounded(data.get(name, 0), width, f"event {{name}}")
               for name, width in SLOT_FIELD_WIDTHS.items()}}
    raw_effects = data.get("csr_effects", [])
    if not isinstance(raw_effects, list) or len(raw_effects) > MAX_CSR_EFFECTS:
        raise EventValidationError("CSR effects exceed the event capacity")
    values["csr_effects"] = tuple(csr_from_dict(item) for item in raw_effects)
    return CommitEvent(**values)


def packet_from_dict(data: dict) -> CommitPacket:
    _known(data, {{"slots"}}, "packet")
    slots = data.get("slots")
    if not isinstance(slots, list) or len(slots) != COMMIT_SLOTS:
        raise EventValidationError("packet must contain exactly two slots")
    return CommitPacket(tuple(event_from_dict(item) for item in slots))


def _byte_bits(mask: int) -> int:
    result = 0
    for lane in range(4):
        if mask & (1 << lane):
            result |= 0xff << (8 * lane)
    return result


def _validate_csr_effects(event: CommitEvent) -> None:
    if len(event.csr_effects) > MAX_CSR_EFFECTS:
        raise EventValidationError("CSR effects exceed the event capacity")
    addresses = []
    for effect in event.csr_effects:
        for name, width in CSR_FIELD_WIDTHS.items():
            _bounded(getattr(effect, name), width, f"CSR {{name}}")
        if effect.valid != 1:
            raise EventValidationError("listed CSR effects must be valid")
        if effect.mask_reason == CSR_MASK_REASONS["none"]:
            raise EventValidationError("valid CSR effect requires a mask reason")
        if effect.read_mask == 0:
            raise EventValidationError("valid CSR effect requires a read mask")
        if (effect.old_value | effect.new_value) & ~effect.read_mask:
            raise EventValidationError("CSR values contain unimplemented bits")
        if (effect.old_value ^ effect.new_value) & ~effect.write_mask:
            raise EventValidationError("CSR change falls outside its write mask")
        addresses.append(effect.address)
    if len(addresses) != len(set(addresses)):
        raise EventValidationError("CSR effect addresses must be unique")
    if event.trap:
        if tuple(addresses) != TRAP_ENTRY_CSRS:
            raise EventValidationError("trap event must carry ordered trap-entry CSR effects")
        if any(effect.mask_reason != CSR_MASK_REASONS["trap_entry"] for effect in event.csr_effects):
            raise EventValidationError("trap CSR effects require trap_entry masks")
    elif any(effect.mask_reason == CSR_MASK_REASONS["trap_entry"] for effect in event.csr_effects):
        raise EventValidationError("non-trap event cannot carry trap-entry masks")


def _validate_memory(event: CommitEvent) -> None:
    fields = (event.mem_address, event.mem_read_mask, event.mem_write_mask,
              event.mem_read_data, event.mem_write_data)
    if not event.mem_valid:
        if any(fields):
            raise EventValidationError("inactive memory effect must be zero")
        return
    if event.trap or not event.retired:
        raise EventValidationError("memory effects require a retired event")
    if bool(event.mem_read_mask) == bool(event.mem_write_mask):
        raise EventValidationError("memory effect must be exactly one read or write")
    mask = event.mem_read_mask or event.mem_write_mask
    lane = event.mem_address & 3
    allowed = {{1 << lane}}
    if lane in (0, 2):
        allowed.add(3 << lane)
    if lane == 0:
        allowed.add(15)
    if mask not in allowed:
        raise EventValidationError("memory mask violates address lane convention")
    selected = _byte_bits(mask)
    data = event.mem_read_data if event.mem_read_mask else event.mem_write_data
    other = event.mem_write_data if event.mem_read_mask else event.mem_read_data
    if data & ~selected or other:
        raise EventValidationError("memory data violates byte-mask lanes")


def _validate_event(event: CommitEvent) -> None:
    for name, width in SLOT_FIELD_WIDTHS.items():
        _bounded(getattr(event, name), width, f"event {{name}}")
    if event.privilege != 3:
        raise EventValidationError("baseline event privilege must be M-mode")
    if event.trap + event.retired != 1:
        raise EventValidationError("valid event must be either retired or trapped")
    if event.pc_before & 3 or event.pc_after & 3:
        raise EventValidationError("event PCs must satisfy IALIGN=32")
    if event.rs1_addr == 0 and event.rs1_value != 0:
        raise EventValidationError("x0 source value must be zero")
    if event.rs2_addr == 0 and event.rs2_value != 0:
        raise EventValidationError("x0 source value must be zero")
    if event.rd_write_mask not in (0, 0xffffffff):
        raise EventValidationError("GPR destination mask must be zero or full-width")
    if event.rd_write_mask:
        if event.rd_addr == 0 or not event.retired:
            raise EventValidationError("GPR write requires a retired non-x0 destination")
    elif event.rd_addr or event.rd_value:
        raise EventValidationError("inactive GPR destination must be zero")
    if event.trap:
        if event.rd_write_mask or event.mem_valid:
            raise EventValidationError("trap event cannot carry partial architectural effects")
    elif event.trap_cause or event.trap_value:
        raise EventValidationError("non-trap metadata must be zero")
    _validate_memory(event)
    _validate_csr_effects(event)


def validate_packet(data: CommitPacket | dict, expected_order: int | None) -> int | None:
    packet = data if isinstance(data, CommitPacket) else packet_from_dict(data)
    if len(packet.slots) != COMMIT_SLOTS:
        raise EventValidationError("packet must contain exactly two slots")
    if packet.slots[1].valid and not packet.slots[0].valid:
        raise EventValidationError("slot 1 cannot be valid when slot 0 is empty")
    next_order = expected_order
    for event in packet.slots:
        if not event.valid:
            scalar_values = [getattr(event, name) for name in SLOT_FIELD_WIDTHS if name != "valid"]
            if any(scalar_values) or event.csr_effects:
                raise EventValidationError("invalid slot must be canonical zero")
            continue
        if next_order is None:
            next_order = event.order
        if event.order != next_order:
            raise EventValidationError("event order is not globally contiguous")
        _validate_event(event)
        next_order += 1
    return next_order
'''
    return textwrap.dedent(body)


def render(config: dict, digest: str) -> dict[str, str]:
    return {
        OUTPUTS[0]: render_sv(config, digest),
        OUTPUTS[1]: render_python(config, digest),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = args.input.read_bytes()
    config = json.loads(source)
    validate(config)
    validate_dependencies(config)
    outputs = render(config, hashlib.sha256(source).hexdigest())
    stale = False
    for relative, content in outputs.items():
        path = ROOT / relative
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        elif not path.is_file() or path.read_text(encoding="utf-8") != content:
            print(f"stale generated file: {relative}")
            stale = True
    if not stale:
        print("commit-event views: PASS")
    return int(stale)


if __name__ == "__main__":
    raise SystemExit(main())
