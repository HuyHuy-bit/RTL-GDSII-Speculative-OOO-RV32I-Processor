from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gen_platform", ROOT / "tools/gen_platform.py")
GENERATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(GENERATOR)


class PlatformTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads((ROOT / "config/platform.yaml").read_text(encoding="utf-8"))

    def test_platform_is_valid(self) -> None:
        GENERATOR.validate(self.config)

    def test_cache_line_must_be_power_of_two(self) -> None:
        changed = copy.deepcopy(self.config)
        changed["memory"]["line_bytes"] = 24
        with self.assertRaisesRegex(ValueError, "power of two"):
            GENERATOR.validate(changed)

    def test_overlapping_regions_fail(self) -> None:
        changed = copy.deepcopy(self.config)
        changed["memory"]["regions"][1]["base"] = "0x00000020"
        with self.assertRaisesRegex(ValueError, "overlap"):
            GENERATOR.validate(changed)

    def test_reset_pc_must_be_executable(self) -> None:
        changed = copy.deepcopy(self.config)
        changed["reset"]["pc"] = "0x10000000"
        with self.assertRaisesRegex(ValueError, "executable"):
            GENERATOR.validate(changed)

    def test_read_only_csr_cannot_be_writable(self) -> None:
        changed = copy.deepcopy(self.config)
        changed["csrs"][-1]["write_mask"] = "0x00000001"
        with self.assertRaisesRegex(ValueError, "access"):
            GENERATOR.validate(changed)

    def test_mmio_attributes_are_restricted(self) -> None:
        changed = copy.deepcopy(self.config)
        changed["memory"]["regions"][1]["idempotent"] = True
        with self.assertRaisesRegex(ValueError, "MMIO"):
            GENERATOR.validate(changed)


if __name__ == "__main__":
    unittest.main()
