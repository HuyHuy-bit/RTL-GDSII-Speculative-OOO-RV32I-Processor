from __future__ import annotations

import copy
from pathlib import Path
import unittest

from model.iss.spike_log import parse_spike_log
from tools.run_lockstep_smoke import smoke_config
from verif.lockstep.comparator import (
    ComparisonError,
    compare_traces,
    parse_verilator_trace,
    required_mutations,
    validate_trace,
    verify_required_mutations,
)


ROOT = Path(__file__).resolve().parents[1]
SPIKE_LOG = """
core   0: 3 0x80000000 (0x00700293) x5  0x00000007
core   0: 3 0x80000004 (0x00528313) x6  0x0000000c
core   0: 3 0x80000008 (0x006283b3) x7  0x00000013
core   0: 3 0x8000000c (0x00638463)
core   0: 3 0x80000010 (0x00138413) x8  0x00000014
"""


class LockstepTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hello = parse_spike_log(SPIKE_LOG, 0x80000000, 0x10000)

    def test_spike_adapter_reconstructs_sources_and_next_pc(self) -> None:
        events = [event for packet in self.hello for event in packet["slots"] if event]
        self.assertEqual(5, len(events))
        self.assertEqual((5, 7, 6, 12), (
            events[2]["rs1_addr"], events[2]["rs1_value"],
            events[2]["rs2_addr"], events[2]["rs2_value"],
        ))
        self.assertEqual(0x10, events[3]["pc_after"])
        self.assertEqual(20, events[4]["rd_value"])

    def test_comparator_accepts_equal_trace(self) -> None:
        compare_traces(self.hello, copy.deepcopy(self.hello))

    def test_smoke_scope_is_explicit(self) -> None:
        config = smoke_config()
        self.assertIn("without claiming full platform lockstep", config["limitation"])

    def test_comparator_reports_field_mismatch(self) -> None:
        changed = copy.deepcopy(self.hello)
        changed[0]["slots"][0]["rd_value"] = 8
        with self.assertRaisesRegex(ComparisonError, "rd_value"):
            compare_traces(self.hello, changed)

    def test_required_mutations_are_all_detected(self) -> None:
        mutations = required_mutations(
            self.hello,
            ROOT / "verif/lockstep/vectors/commit_event_cases.json",
        )
        for expected, _ in mutations.values():
            validate_trace(expected)
        caught = verify_required_mutations(
            self.hello,
            ROOT / "verif/lockstep/vectors/commit_event_cases.json",
        )
        self.assertEqual({
            "destination_value", "next_pc", "trap_metadata", "dual_slot_order",
            "memory_mask", "memory_data_lane", "missing_event",
        }, set(caught))

    def test_verilator_trace_requires_oldest_first_slots(self) -> None:
        with self.assertRaisesRegex(ComparisonError, "oldest-first"):
            parse_verilator_trace("PACKET|0|1")


if __name__ == "__main__":
    unittest.main()
