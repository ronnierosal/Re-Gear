import struct
import unittest

from backend.hdm.delivery.device_receive_program import compile_device_receive


def run(code, *, group=9, prior=0, mode=0x2180, dev=0x100003,
        fail=0, null_inode=False, null_file=False):
    """Decode bytes independently, with helper clobbers and byte memory."""
    memory = {}
    def put(address, value, size):
        for i, byte in enumerate(value.to_bytes(size, 'little')):
            memory[address+i] = byte
    def get(address, size):
        return int.from_bytes(bytes(memory[address+i] for i in range(size)), 'little')
    put(1000, 0 if null_file else 2000, 8)
    put(1008, prior & 0xffffffff, 8)
    put(2024, 0 if null_inode else 3000, 8)
    put(3030, mode, 2)
    put(3040, dev, 4)
    regs = [0]*11
    regs[1], regs[10] = 1000, 10000
    rows = list(struct.iter_unpack('<BBhi', code))
    pc, reads = 0, 0
    for _ in range(1000):
        op, packed, off, imm = rows[pc]
        dst, src = packed & 15, packed >> 4
        pc += 1
        if op in (0x61, 0x69, 0x79):
            regs[dst] = get(regs[src]+off, {0x61:4, 0x69:2, 0x79:8}[op])
        elif op == 0xbf: regs[dst] = regs[src]
        elif op == 0xb7: regs[dst] = imm & (2**64-1)
        elif op == 0x07: regs[dst] = (regs[dst]+imm) & (2**64-1)
        elif op == 0x54: regs[dst] &= imm & 0xffffffff
        elif op == 0x18:
            high = rows[pc]
            assert high[:3] == (0,0,0)
            regs[dst] = (imm & 0xffffffff) | ((high[3] & 0xffffffff)<<32)
            pc += 1
        elif op == 0x85:
            if imm == 80: result = group
            elif imm == 113:
                reads += 1
                result = -14 if reads == fail else 0
                if result == 0: put(regs[1], get(regs[3], regs[2]), regs[2])
            else: raise AssertionError('unexpected helper')
            regs[0] = result & (2**64-1)
            regs[1:6] = [None]*5
        elif op == 0x05: pc += off
        elif op in (0x55, 0x15, 0x56, 0x16, 0x1d):
            a = regs[dst]
            b = regs[src] if op == 0x1d else imm & (2**64-1)
            if op in (0x56, 0x16): a, b = a & 0xffffffff, b & 0xffffffff
            condition = a != b if op in (0x55, 0x56) else a == b
            if condition: pc += off
        elif op == 0x95:
            value = regs[0] & 0xffffffff
            return value if value < 2**31 else value-2**32, reads
        else: raise AssertionError(hex(op))
    raise AssertionError('did not terminate')


class ReceiveCompilerTests(unittest.TestCase):
    def build(self, groups=(9,), devices=((1,3),), **kw):
        return compile_device_receive(groups, devices, **{
            'file_inode_offset':24, 'inode_mode_offset':30,
            'inode_rdev_offset':40, **kw})

    def test_prior_result_preserved_before_scope_or_reads(self):
        for prior in (-1,-13,-4095,1):
            self.assertEqual(run(self.build(), prior=prior), (prior,0))

    def test_exact_64bit_scope_and_no_reads_elsewhere(self):
        high = 2**63+9
        code = self.build((high,2**64-1))
        self.assertEqual(run(code), (0,0))
        for group in (high,2**64-1): self.assertEqual(run(code,group=group),(-13,3))

    def test_char_only_and_exact_device(self):
        for mode in (0x8180,0xc180,0x6180,0x4180):
            self.assertEqual(run(self.build(),mode=mode),(0,2))
        self.assertEqual(run(self.build(),dev=0x100004),(0,3))
        self.assertEqual(run(self.build()),(-13,3))

    def test_target_read_failures_and_null_pointers_deny(self):
        for failure in (1,2,3):
            self.assertEqual(run(self.build(),fail=failure),(-13,failure))
        self.assertEqual(run(self.build(),null_inode=True),(-13,1))
        self.assertEqual(run(self.build(),null_file=True),(-13,0))

    def test_device_range_and_maximum_rules(self):
        devices = ((0,0),(4095,1048575),*((i, i*100) for i in range(1,15)))
        code = self.build(devices=devices)
        for major,minor in devices:
            self.assertEqual(run(code,dev=major*1048576+minor)[0],-13)
        self.assertEqual(run(code,dev=0x12345678)[0],0)
        self.assertEqual(code,self.build(devices=tuple(reversed(devices))))

    def test_invalid_inputs(self):
        for groups in ((),(True,),(0,),(-1,),(2**64,),(9,9),(1,2,3),[9]):
            with self.assertRaises(ValueError): self.build(groups)
        for devices in ((),((1,3),(1,3)),((4096,0),),((0,2**20),)):
            with self.assertRaises(ValueError): self.build(devices=devices)
        for name in ('file_inode_offset','inode_mode_offset','inode_rdev_offset'):
            for value in (True,-1,32767,1.0,None):
                with self.assertRaises(ValueError): self.build(**{name:value})


if __name__ == '__main__':
    unittest.main()
