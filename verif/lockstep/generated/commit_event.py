#!/usr/bin/env python3
"""Generated commit-event types and structural validator."""

from __future__ import annotations

from dataclasses import dataclass, field


SOURCE_SHA256 = '773da171de8caad77c354b70d8a03af949548307a71203bc8ada37530e8d0fe9'
COMMIT_SLOTS = 2
MAX_CSR_EFFECTS = 4
SLOT_FIELD_WIDTHS = {'valid': 1, 'order': 64, 'instruction': 32, 'privilege': 2, 'pc_before': 32, 'pc_after': 32, 'rs1_addr': 5, 'rs1_value': 32, 'rs2_addr': 5, 'rs2_value': 32, 'rd_addr': 5, 'rd_value': 32, 'rd_write_mask': 32, 'trap': 1, 'trap_cause': 32, 'trap_value': 32, 'retired': 1, 'mem_valid': 1, 'mem_address': 32, 'mem_read_mask': 4, 'mem_write_mask': 4, 'mem_read_data': 32, 'mem_write_data': 32}
CSR_FIELD_WIDTHS = {'valid': 1, 'address': 12, 'old_value': 32, 'new_value': 32, 'read_mask': 32, 'write_mask': 32, 'mask_reason': 3}
CSR_MASK_REASONS = {'none': 0, 'instruction': 1, 'trap_entry': 2, 'mret': 3}
TRAP_ENTRY_CSRS = (768, 833, 834, 835)


class EventValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CsrEffect:
    valid: int = 0
    address: int = 0
    old_value: int = 0
    new_value: int = 0
    read_mask: int = 0
    write_mask: int = 0
    mask_reason: int = 0


@dataclass(frozen=True)
class CommitEvent:
    valid: int = 0
    order: int = 0
    instruction: int = 0
    privilege: int = 0
    pc_before: int = 0
    pc_after: int = 0
    rs1_addr: int = 0
    rs1_value: int = 0
    rs2_addr: int = 0
    rs2_value: int = 0
    rd_addr: int = 0
    rd_value: int = 0
    rd_write_mask: int = 0
    trap: int = 0
    trap_cause: int = 0
    trap_value: int = 0
    retired: int = 0
    mem_valid: int = 0
    mem_address: int = 0
    mem_read_mask: int = 0
    mem_write_mask: int = 0
    mem_read_data: int = 0
    mem_write_data: int = 0
    csr_effects: tuple[CsrEffect, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CommitPacket:
    slots: tuple[CommitEvent, ...]


def _known(data: dict, allowed: set[str], context: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise EventValidationError(f"{context} has unknown fields: {sorted(unknown)}")


def _bounded(value: object, width: int, context: str) -> int:
    if type(value) not in (int, bool):
        raise EventValidationError(f"{context} must be an integer")
    result = int(value)
    if result < 0 or result >= 1 << width:
        raise EventValidationError(f"{context} exceeds {width} bits")
    return result


def csr_from_dict(data: dict) -> CsrEffect:
    _known(data, set(CSR_FIELD_WIDTHS), "CSR effect")
    values = {name: _bounded(data.get(name, 0), width, f"CSR {name}")
               for name, width in CSR_FIELD_WIDTHS.items() if name != "mask_reason"}
    values["valid"] = _bounded(data.get("valid", 1), 1, "CSR valid")
    reason = data.get("mask_reason", 0)
    if isinstance(reason, str):
        if reason not in CSR_MASK_REASONS:
            raise EventValidationError(f"unknown CSR mask reason: {reason}")
        values["mask_reason"] = CSR_MASK_REASONS[reason]
    else:
        values["mask_reason"] = _bounded(reason, CSR_FIELD_WIDTHS["mask_reason"], "CSR mask_reason")
    if values["mask_reason"] not in CSR_MASK_REASONS.values():
        raise EventValidationError(f"unknown CSR mask reason: {values['mask_reason']}")
    return CsrEffect(**values)


def event_from_dict(data: dict) -> CommitEvent:
    _known(data, set(SLOT_FIELD_WIDTHS) | {"csr_effects"}, "event")
    values = {name: _bounded(data.get(name, 0), width, f"event {name}")
               for name, width in SLOT_FIELD_WIDTHS.items()}
    raw_effects = data.get("csr_effects", [])
    if not isinstance(raw_effects, list) or len(raw_effects) > MAX_CSR_EFFECTS:
        raise EventValidationError("CSR effects exceed the event capacity")
    values["csr_effects"] = tuple(csr_from_dict(item) for item in raw_effects)
    return CommitEvent(**values)


def packet_from_dict(data: dict) -> CommitPacket:
    _known(data, {"slots"}, "packet")
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
            _bounded(getattr(effect, name), width, f"CSR {name}")
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
    allowed = {1 << lane}
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
        _bounded(getattr(event, name), width, f"event {name}")
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
