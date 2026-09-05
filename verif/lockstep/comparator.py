#!/usr/bin/env python3
"""Compare normalized architectural-event traces by commit order."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from verif.lockstep.generated import commit_event as schema


class ComparisonError(AssertionError):
    pass


def validate_trace(packets: list[dict]) -> tuple[schema.CommitEvent, ...]:
    events = []
    expected_order = 0
    try:
        for packet in packets:
            typed = schema.packet_from_dict(packet)
            expected_order = schema.validate_packet(typed, expected_order)
            events.extend(event for event in typed.slots if event.valid)
    except schema.EventValidationError as error:
        raise ComparisonError(str(error)) from error
    return tuple(events)


def compare_traces(expected_packets: list[dict], actual_packets: list[dict]) -> None:
    expected = validate_trace(expected_packets)
    actual = validate_trace(actual_packets)
    if len(expected) != len(actual):
        raise ComparisonError(f"event count differs: expected {len(expected)}, got {len(actual)}")
    fields = tuple(schema.SLOT_FIELD_WIDTHS) + ("csr_effects",)
    for index, (left, right) in enumerate(zip(expected, actual)):
        for field in fields:
            if getattr(left, field) != getattr(right, field):
                raise ComparisonError(
                    f"event {index} field {field} differs: "
                    f"expected {getattr(left, field)!r}, got {getattr(right, field)!r}"
                )


def parse_verilator_trace(output: str) -> list[dict]:
    field_names = [name for name in schema.SLOT_FIELD_WIDTHS if name != "valid"]
    packets = []
    active = None
    expected_slots = None
    for line in output.splitlines():
        if line.startswith("PACKET|"):
            if active is not None and len(active) != expected_slots:
                raise ComparisonError("Verilator packet event count is inconsistent")
            valid_bits = [int(value, 16) for value in line.split("|")[1:]]
            if len(valid_bits) != schema.COMMIT_SLOTS or valid_bits not in ([0, 0], [1, 0], [1, 1]):
                raise ComparisonError("Verilator packet valid bits are not oldest-first")
            active = []
            expected_slots = sum(valid_bits)
            packets.append({"slots": active})
        elif line.startswith("EVENT|"):
            if active is None:
                raise ComparisonError("Verilator event appeared before a packet marker")
            values = line.split("|")[1:]
            if len(values) != len(field_names):
                raise ComparisonError("Verilator event field count is inconsistent")
            event = {"valid": 1}
            event.update({name: int(value, 16) for name, value in zip(field_names, values)})
            active.append(event)
    if active is None or len(active) != expected_slots:
        raise ComparisonError("Verilator trace ended with an incomplete packet")
    for packet in packets:
        packet["slots"].extend({} for _ in range(schema.COMMIT_SLOTS - len(packet["slots"])))
    return packets


def required_mutations(hello_packets: list[dict], vectors_path: Path) -> dict[str, tuple[list[dict], list[dict]]]:
    vectors = json.loads(vectors_path.read_text(encoding="utf-8"))
    cases = {case["name"]: case["packet"] for case in vectors["valid_cases"]}
    mutations = {}

    changed = copy.deepcopy(hello_packets)
    changed[0]["slots"][0]["rd_value"] ^= 1
    mutations["destination_value"] = (hello_packets, changed)

    changed = copy.deepcopy(hello_packets)
    changed[0]["slots"][0]["pc_after"] ^= 4
    mutations["next_pc"] = (hello_packets, changed)

    trap = copy.deepcopy(cases["trapped_load"])
    trap["slots"][0]["order"] = 0
    changed = copy.deepcopy(trap)
    changed["slots"][0]["trap_cause"] ^= 1
    mutations["trap_metadata"] = ([trap], [changed])

    changed = copy.deepcopy(hello_packets)
    changed[0]["slots"].reverse()
    mutations["dual_slot_order"] = (hello_packets, changed)

    load = copy.deepcopy(cases["lane_aligned_load"])
    load["slots"][0]["order"] = 0
    changed = copy.deepcopy(load)
    changed["slots"][0]["mem_read_mask"] = 3
    mutations["memory_mask"] = ([load], [changed])

    changed = copy.deepcopy(load)
    changed["slots"][0]["mem_read_data"] |= 1
    mutations["memory_data_lane"] = ([load], [changed])

    changed = copy.deepcopy(hello_packets)
    changed[-1]["slots"][0] = {}
    mutations["missing_event"] = (hello_packets, changed)
    return mutations


def verify_required_mutations(hello_packets: list[dict], vectors_path: Path) -> tuple[str, ...]:
    caught = []
    for name, (expected, actual) in required_mutations(hello_packets, vectors_path).items():
        validate_trace(expected)
        try:
            compare_traces(expected, actual)
        except ComparisonError:
            caught.append(name)
        else:
            raise ComparisonError(f"comparator missed required mutation: {name}")
    return tuple(caught)
