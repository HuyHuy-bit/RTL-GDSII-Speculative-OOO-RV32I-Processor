from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


GENERATOR = load_module("gen_commit_event", ROOT / "tools/gen_commit_event.py")
EVENT = load_module("commit_event", ROOT / "verif/lockstep/generated/commit_event.py")


class CommitEventTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads((ROOT / "config/commit_event.yaml").read_text(encoding="utf-8"))
        cls.vectors = json.loads(
            (ROOT / "verif/lockstep/vectors/commit_event_cases.json").read_text(encoding="utf-8")
        )

    def test_schema_is_valid(self) -> None:
        GENERATOR.validate(self.config)
        GENERATOR.validate_dependencies(self.config)

    def test_required_valid_examples(self) -> None:
        names = {case["name"] for case in self.vectors["valid_cases"]}
        required = {
            "bubble", "single_retirement", "dual_retirement_register_and_store",
            "trapped_load", "buffered_committed_store", "lane_aligned_load",
            "csr_read_modify_write",
        }
        self.assertEqual(required, names)
        for case in self.vectors["valid_cases"]:
            with self.subTest(case=case["name"]):
                result = EVENT.validate_packet(case["packet"], case["expected_order"])
                self.assertEqual(case["next_order"], result)

    def test_seeded_invalid_examples(self) -> None:
        for case in self.vectors["invalid_cases"]:
            with self.subTest(case=case["name"]):
                with self.assertRaisesRegex(EVENT.EventValidationError, case["error"]):
                    EVENT.validate_packet(case["packet"], case["expected_order"])

    def test_host_types_are_generated(self) -> None:
        packet = EVENT.packet_from_dict(self.vectors["valid_cases"][1]["packet"])
        self.assertIsInstance(packet, EVENT.CommitPacket)
        self.assertIsInstance(packet.slots[0], EVENT.CommitEvent)

    def test_example_instruction_encodings(self) -> None:
        cases = {case["name"]: case for case in self.vectors["valid_cases"]}
        self.assertEqual(0x00700293, cases["single_retirement"]["packet"]["slots"][0]["instruction"])
        self.assertEqual(0x00532023, cases["buffered_committed_store"]["packet"]["slots"][0]["instruction"])
        self.assertEqual(0x00231383, cases["lane_aligned_load"]["packet"]["slots"][0]["instruction"])
        self.assertEqual(0x300322f3, cases["csr_read_modify_write"]["packet"]["slots"][0]["instruction"])

    def test_schema_rejects_unpinned_rvfi(self) -> None:
        changed = json.loads(json.dumps(self.config))
        changed["rvfi"]["revision"] = "main"
        with self.assertRaisesRegex(ValueError, "full Git commit"):
            GENERATOR.validate(changed)

    def test_schema_rejects_mismatched_rvfi_lock(self) -> None:
        changed = json.loads(json.dumps(self.config))
        changed["rvfi"]["revision"] = "0" * 40
        GENERATOR.validate(changed)
        with self.assertRaisesRegex(ValueError, "locked RVFI"):
            GENERATOR.validate_dependencies(changed)

    def test_numeric_mask_reason_is_checked(self) -> None:
        case = json.loads(json.dumps(self.vectors["valid_cases"][-1]))
        case["packet"]["slots"][0]["csr_effects"][0]["mask_reason"] = 1
        EVENT.validate_packet(case["packet"], case["expected_order"])
        case["packet"]["slots"][0]["csr_effects"][0]["mask_reason"] = 7
        with self.assertRaisesRegex(EVENT.EventValidationError, "unknown CSR mask reason"):
            EVENT.validate_packet(case["packet"], case["expected_order"])

    def test_direct_host_type_width_is_checked(self) -> None:
        event = EVENT.CommitEvent(valid=2, order=70, instruction=19, privilege=3, pc_after=4, retired=1)
        packet = EVENT.CommitPacket((event, EVENT.CommitEvent()))
        with self.assertRaisesRegex(EVENT.EventValidationError, "exceeds 1 bits"):
            EVENT.validate_packet(packet, 70)


if __name__ == "__main__":
    unittest.main()
