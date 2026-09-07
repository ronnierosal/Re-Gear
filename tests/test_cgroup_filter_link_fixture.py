import ctypes
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import probe_cgroup_filter_link as fixture


class CgroupFilterLinkTests(unittest.TestCase):
    def setUp(self):
        self.system = patch.object(fixture.platform, "system", return_value="Linux")
        self.machine = patch.object(fixture.platform, "machine", return_value="x86_64")
        self.system.start()
        self.machine.start()
        self.addCleanup(self.system.stop)
        self.addCleanup(self.machine.stop)
        self.calls = []
        self.closed = []
        self.fail = None
        self.wrong_type = False

    def syscall(self, number, command, pointer, size):
        self.assertEqual(number, 321)
        kind = {5: fixture.LoadAttr, 28: fixture.LinkAttr,
                16: fixture.QueryAttr, 15: fixture.InfoAttr}[command]
        self.assertEqual(size, ctypes.sizeof(kind))
        attr = ctypes.cast(pointer, ctypes.POINTER(kind)).contents
        self.calls.append(command)
        if command == self.fail:
            ctypes.set_errno(1)
            return -1
        if command == 5:
            self.assertEqual((attr.prog_type, attr.expected_attach_type, attr.prog_flags), (15, 6, 0))
            self.assertEqual(ctypes.string_at(attr.license), b"GPL")
            self.assertEqual((attr.log_level, attr.log_size, attr.log_buf), (0, 0, 0))
            self.assertEqual(ctypes.string_at(attr.insns, attr.insn_cnt * 8), b"\0" * 8)
            return 20
        if command == 28:
            self.assertEqual((attr.prog_fd, attr.target_fd, attr.attach_type, attr.flags), (20, 9, 6, 0))
            return 21
        if command == 15:
            self.assertEqual((attr.bpf_fd, attr.info_len), (20, 8))
            info = ctypes.cast(attr.info, ctypes.POINTER(ctypes.c_uint32))
            info[0], info[1] = (99 if self.wrong_type else 15), 100
        if command == 16:
            self.assertEqual((attr.target_fd, attr.attach_type, attr.query_flags,
                              attr.attach_flags, attr.prog_cnt, attr.prog_attach_flags),
                             (9, 6, 0, 0, 64, 0))
            ids = ctypes.cast(attr.prog_ids, ctypes.POINTER(ctypes.c_uint32))
            ids[0] = 100
            attr.prog_cnt = 1
        return 0

    def controller(self):
        return fixture.CgroupDeviceLink(syscall=self.syscall, close_fd=self.closed.append)

    def test_fixed_uapi_layout(self):
        self.assertEqual(ctypes.sizeof(fixture.LoadAttr), 72)
        self.assertEqual(fixture.LoadAttr.expected_attach_type.offset, 68)
        self.assertEqual(ctypes.sizeof(fixture.LinkAttr), 16)
        self.assertEqual(ctypes.sizeof(fixture.QueryAttr), 40)
        self.assertEqual(fixture.QueryAttr.prog_ids.offset, 16)
        self.assertEqual(fixture.QueryAttr.prog_cnt.offset, 24)
        self.assertEqual(ctypes.sizeof(fixture.InfoAttr), 16)

    def test_load_identity_link_query_and_detach_cleanup(self):
        with self.controller() as value:
            value.load(b"\0" * 8)
            self.assertEqual(value.program_id(), 100)
            value.attach(9)
            self.assertEqual(value.query_program_ids(9), (100,))
            value.close_link()
            self.assertEqual(self.closed, [21])
            value.close_link()
        self.assertEqual(self.closed, [21, 20])
        self.assertEqual(self.calls, [5, 15, 28, 16])

    def test_failure_cleanup_at_each_syscall(self):
        for command, expected in ((5, []), (15, [20]), (28, [20]), (16, [21, 20])):
            self.closed.clear()
            self.fail = command
            with self.subTest(command=command), self.assertRaises(OSError):
                with self.controller() as value:
                    value.load(b"\0" * 8)
                    value.program_id()
                    value.attach(9)
                    value.query_program_ids(9)
            self.assertEqual(self.closed, expected)

    def test_wrong_program_identity_fails_and_closes(self):
        self.wrong_type = True
        with self.assertRaises(RuntimeError):
            with self.controller() as value:
                value.load(b"\0" * 8)
                value.program_id()
        self.assertEqual(self.closed, [20])

    def test_wrong_architecture_rejected_before_syscall(self):
        with patch.object(fixture.platform, "machine", return_value="aarch64"):
            with self.assertRaises(RuntimeError):
                self.controller()
        with patch.object(fixture.platform, "system", return_value="Windows"):
            with self.assertRaises(RuntimeError):
                self.controller()
        self.assertEqual(self.calls, [])

    def test_input_and_lifecycle_fail_before_syscalls(self):
        with self.controller() as value:
            for code in (None, b"", b"a", bytes(576), bytearray(8)):
                with self.assertRaises(ValueError):
                    value.load(code)
            for descriptor in (True, -1, 1 << 31, "9"):
                with self.assertRaises(ValueError):
                    value.attach(descriptor)
            with self.assertRaises(RuntimeError):
                value.attach(9)
            self.assertEqual(self.calls, [])
            value.load(bytes(8))
            with self.assertRaises(RuntimeError):
                value.load(bytes(8))
            value.attach(9)
            with self.assertRaises(RuntimeError):
                value.attach(9)

    def test_program_closed_even_if_link_close_fails(self):
        def close(descriptor):
            self.closed.append(descriptor)
            if descriptor == 21:
                raise OSError("fixture close failure")
        value = fixture.CgroupDeviceLink(syscall=self.syscall, close_fd=close)
        value.load(bytes(8))
        value.attach(9)
        with self.assertRaises(OSError):
            value.close()
        self.assertEqual(self.closed, [21, 20])
        value.close()


if __name__ == "__main__":
    unittest.main()
