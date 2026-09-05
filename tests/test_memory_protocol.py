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


GENERATOR = load_module("gen_memory_protocol", ROOT / "tools/gen_memory_protocol.py")
MEMORY = load_module("memory_protocol", ROOT / "verif/protocol/generated/memory_protocol.py")


def line_read(transaction_id: int = 1, address: int = 0) -> dict:
    return {"transaction_id": transaction_id, "address": address}


class MemoryProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads((ROOT / "config/memory_protocol.yaml").read_text(encoding="utf-8"))

    def test_schema_and_platform_agree(self) -> None:
        GENERATOR.validate(self.config)
        GENERATOR.validate_dependencies(self.config)

    def test_request_payload_holds_until_accepted(self) -> None:
        port = MEMORY.SingleOutstandingPort("instruction")
        request = line_read()
        port.step(request_valid=True, request_ready=False, request=request)
        changed = line_read(address=32)
        with self.assertRaisesRegex(MEMORY.ProtocolError, "changed while stalled"):
            port.step(request_valid=True, request_ready=False, request=changed)
        result = port.step(request_valid=True, request_ready=True, request=request)
        self.assertTrue(result.request_accepted)

    def test_response_payload_holds_until_accepted(self) -> None:
        port = MEMORY.SingleOutstandingPort("instruction")
        port.step(request_valid=True, request_ready=True, request=line_read())
        response = {"transaction_id": 1, "line_read_data": 0x11223344}
        port.step(response_valid=True, response_ready=False, response=response)
        changed = {"transaction_id": 1, "line_read_data": 0x55667788}
        with self.assertRaisesRegex(MEMORY.ProtocolError, "changed while stalled"):
            port.step(response_valid=True, response_ready=False, response=changed)
        result = port.step(response_valid=True, response_ready=True, response=response)
        self.assertTrue(result.response_accepted)
        self.assertTrue(result.completion)

    def test_response_requires_matching_live_owner(self) -> None:
        port = MEMORY.SingleOutstandingPort("instruction")
        with self.assertRaisesRegex(MEMORY.ProtocolError, "no live transaction"):
            port.step(response_valid=True, response_ready=True, response={"transaction_id": 1})
        port.step(request_valid=True, request_ready=True, request=line_read())
        with self.assertRaisesRegex(MEMORY.ProtocolError, "does not own"):
            port.step(response_valid=True, response_ready=True, response={"transaction_id": 2})

    def test_port_forbids_turnover_while_occupied(self) -> None:
        port = MEMORY.SingleOutstandingPort("instruction")
        port.step(request_valid=True, request_ready=True, request=line_read())
        with self.assertRaisesRegex(MEMORY.ProtocolError, "advertised request ready"):
            port.step(
                request_valid=True,
                request_ready=True,
                request=line_read(transaction_id=2, address=32),
                response_valid=True,
                response_ready=True,
                response={"transaction_id": 1},
            )

    def test_cached_read_can_be_dropped_without_reusing_slot(self) -> None:
        port = MEMORY.SingleOutstandingPort("instruction")
        port.step(request_valid=True, request_ready=True, request=line_read())
        port.step(drop=True)
        self.assertIsNotNone(port.outstanding)
        result = port.step(response_valid=True, response_ready=True, response={"transaction_id": 1})
        self.assertTrue(result.killed)
        self.assertFalse(result.completion)
        self.assertIsNone(port.outstanding)

    def test_uncached_request_cannot_be_dropped(self) -> None:
        port = MEMORY.SingleOutstandingPort("data")
        request = {"transaction_id": 3, "uncached": 1, "address": 0x10000000, "uncached_size": 2}
        port.step(request_valid=True, request_ready=True, request=request)
        with self.assertRaisesRegex(MEMORY.ProtocolError, "cached read"):
            port.step(drop=True)

    def test_reset_clears_owner_and_suppresses_stale_response(self) -> None:
        port = MEMORY.SingleOutstandingPort("instruction")
        port.step(request_valid=True, request_ready=True, request=line_read())
        port.step(reset=True)
        self.assertIsNone(port.outstanding)
        with self.assertRaisesRegex(MEMORY.ProtocolError, "no live transaction"):
            port.step(response_valid=True, response_ready=True, response={"transaction_id": 1})

    def test_request_classes_and_byte_lanes(self) -> None:
        valid_write = MEMORY.request_from_dict({
            "transaction_id": 4,
            "write": 1,
            "uncached": 1,
            "address": 0x10000002,
            "uncached_size": 1,
            "uncached_write_data": 0xabcd0000,
            "uncached_write_strobe": 12,
        })
        MEMORY.validate_request("data", valid_write)
        uncached_read = MEMORY.request_from_dict({
            "transaction_id": 4,
            "uncached": 1,
            "address": 0x10000000,
            "uncached_size": 2,
        })
        with self.assertRaisesRegex(MEMORY.ProtocolError, "does not permit uncached"):
            MEMORY.validate_request("instruction", uncached_read)
        bad_size = MEMORY.request_from_dict({"uncached": 1, "address": 0x10000000, "uncached_size": 3})
        with self.assertRaisesRegex(MEMORY.ProtocolError, "byte, halfword, or word"):
            MEMORY.validate_request("data", bad_size)
        bad_line = MEMORY.request_from_dict({"address": 4})
        with self.assertRaisesRegex(MEMORY.ProtocolError, "line aligned"):
            MEMORY.validate_request("data", bad_line)

    def test_error_response_completes_with_status(self) -> None:
        port = MEMORY.SingleOutstandingPort("data")
        request = {"transaction_id": 5, "uncached": 1, "address": 0x10000000, "uncached_size": 2}
        port.step(request_valid=True, request_ready=True, request=request)
        result = port.step(
            response_valid=True,
            response_ready=True,
            response={"transaction_id": 5, "status": MEMORY.RESPONSE_STATUS["access_fault"]},
        )
        self.assertTrue(result.completion)
        self.assertEqual(MEMORY.RESPONSE_STATUS["access_fault"], result.status)

    def test_protocol_error_selects_fatal_path(self) -> None:
        port = MEMORY.SingleOutstandingPort("instruction")
        port.step(request_valid=True, request_ready=True, request=line_read())
        result = port.step(
            response_valid=True,
            response_ready=True,
            response={"transaction_id": 1, "status": MEMORY.RESPONSE_STATUS["protocol_error"]},
        )
        self.assertTrue(result.fatal)
        self.assertFalse(result.completion)

    def test_direct_type_width_is_checked(self) -> None:
        request = MEMORY.MemoryRequest(transaction_id=16)
        with self.assertRaisesRegex(MEMORY.ProtocolError, "exceeds 4 bits"):
            MEMORY.validate_request("data", request)


if __name__ == "__main__":
    unittest.main()
