import itertools
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.delivery.device_filter_program import compile_device_filter


def evaluate(program, device_type, major, minor, access):
    """Independent subset interpreter: decode serialized ABI, not compiler IR."""
    context = struct.pack("<III", device_type | (access << 16), major, minor)
    registers = {1: 0}
    instructions = list(struct.iter_unpack("<BBhi", program))
    pc = 0
    for _ in range(100):
        if not 0 <= pc < len(instructions):
            raise AssertionError("jump outside program")
        op, regs, offset, immediate = instructions[pc]
        dst, src = regs & 15, regs >> 4
        pc += 1
        if op == 0x61:
            if src != 1 or offset not in (0, 4, 8) or immediate:
                raise AssertionError("invalid context load")
            registers[dst] = struct.unpack_from("<I", context, offset)[0]
        elif op == 0x54:
            registers[dst] &= immediate & 0xffffffff
        elif op == 0x56:
            if (registers[dst] & 0xffffffff) != (immediate & 0xffffffff):
                pc += offset
        elif op == 0xb4:
            registers[dst] = immediate & 0xffffffff
        elif op == 0x95:
            return registers[0]
        else:
            raise AssertionError("unsupported opcode")
    raise AssertionError("program did not terminate")


class DeviceFilterProgramTests(unittest.TestCase):
    def test_every_denied_device_and_access_combination(self):
        policy = tuple((226, index * 8) for index in range(16))
        program = compile_device_filter(policy)
        for pair, access in itertools.product(policy, range(1, 8)):
            with self.subTest(pair=pair, access=access):
                self.assertEqual(evaluate(program, 2, *pair, access), 0)

    def test_block_devices_same_numbers_remain_allowed(self):
        policy = ((0, 0), (226, 128), (4095, 1048575))
        for pair, access in itertools.product(policy, range(1, 8)):
            self.assertEqual(evaluate(compile_device_filter(policy), 1, *pair, access), 1)

    def test_adjacent_and_cross_product_devices_remain_allowed(self):
        policy = ((10, 20), (30, 40))
        program = compile_device_filter(policy)
        for major, minor, access in itertools.product(
                (9, 10, 11, 29, 30, 31), (19, 20, 21, 39, 40, 41), range(1, 8)):
            self.assertEqual(evaluate(program, 2, major, minor, access),
                             int((major, minor) not in policy))

    def test_unsigned_context_edges_do_not_alias_policy(self):
        policy = ((0, 0), (4095, 1048575))
        program = compile_device_filter(policy)
        for pair in policy:
            self.assertEqual(evaluate(program, 2, *pair, 7), 0)
        for pair in ((0x80000000, 0), (0, 0x80000000), (0xffffffff, 0xffffffff),
                     (4096, 1048575), (4095, 1048576)):
            self.assertEqual(evaluate(program, 2, *pair, 7), 1)

    def test_access_bits_cannot_bypass_deny(self):
        program = compile_device_filter(((10, 20),))
        for access in (0, 8, 0xffff):
            self.assertEqual(evaluate(program, 2, 10, 20, access), 0)

    def test_type_requires_exact_character_type(self):
        program = compile_device_filter(((10, 20),))
        for kind in (0, 1, 3, 0xffff):
            self.assertEqual(evaluate(program, kind, 10, 20, 7), 1)

    def test_deterministic_bounded_serialization(self):
        policy = tuple((226, i) for i in range(16))
        result = compile_device_filter(policy)
        self.assertEqual(result, compile_device_filter(tuple(reversed(policy))))
        self.assertEqual(len(result), 71 * 8)
        self.assertEqual(result[:8], bytes.fromhex("6112000000000000"))

    def test_invalid_policy_rejected(self):
        cases = (None, [], (), ((1, 2),) * 2, tuple((1, i) for i in range(17)),
                 ([1, 2],), ((1,),), ((1, 2, 3),), ((True, 2),), ((1, False),),
                 ((1.0, 2),), ((1, "2"),), ((-1, 0),), ((0, -1),),
                 ((4096, 0),), ((0, 1048576),), ((2**100, 0),))
        for policy in cases:
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                compile_device_filter(policy)


if __name__ == "__main__":
    unittest.main()
