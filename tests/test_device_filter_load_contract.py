"""Mock kernel ABI checks: never load or attach a real BPF program."""

import ctypes
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.delivery import device_filter_kernel as kernel
from regear.delivery.device_filter_program import compile_device_filter


class LoadContractTests(unittest.TestCase):
    def test_compile_load_identify_attach_query_and_close(self):
        program = compile_device_filter(((226, 129), (116, 15)))
        calls, closed = [], []

        def syscall(number, command, pointer, size):
            self.assertEqual(number, 321)
            calls.append(command)
            if command == 5:
                attr = ctypes.cast(pointer, ctypes.POINTER(kernel.LoadAttr)).contents
                self.assertEqual(size, ctypes.sizeof(kernel.LoadAttr))
                self.assertEqual((attr.prog_type, attr.expected_attach_type), (15, 6))
                self.assertEqual(ctypes.string_at(attr.insns, attr.insn_cnt * 8), program)
                self.assertEqual(ctypes.string_at(attr.license), b"GPL")
                return 41
            if command == 15:
                attr = ctypes.cast(pointer, ctypes.POINTER(kernel.InfoAttr)).contents
                self.assertEqual((attr.bpf_fd, attr.info_len), (41, 8))
                info = ctypes.cast(attr.info, ctypes.POINTER(ctypes.c_uint32))
                info[0], info[1] = 15, 91
                return 0
            if command == 28:
                attr = ctypes.cast(pointer, ctypes.POINTER(kernel.LinkAttr)).contents
                self.assertEqual((attr.prog_fd, attr.target_fd, attr.attach_type, attr.flags),
                                 (41, 17, 6, 0))
                return 42
            if command == 16:
                attr = ctypes.cast(pointer, ctypes.POINTER(kernel.QueryAttr)).contents
                self.assertEqual((attr.target_fd, attr.attach_type, attr.prog_cnt),
                                 (17, 6, 64))
                ids = ctypes.cast(attr.prog_ids, ctypes.POINTER(ctypes.c_uint32))
                ids[0], ids[1], attr.prog_cnt = 80, 91, 2
                return 0
            self.fail(f"unexpected syscall command {command}")

        with patch.object(kernel.platform, "system", return_value="Linux"), \
                patch.object(kernel.platform, "machine", return_value="x86_64"):
            with kernel.CgroupDeviceLink(syscall=syscall, close_fd=closed.append) as link:
                self.assertEqual(link.load(program), 41)
                self.assertEqual(link.program_id(), 91)
                self.assertEqual(link.attach(17), 42)
                self.assertEqual(link.query_program_ids(17), (80, 91))
                with self.assertRaises(RuntimeError):
                    link.attach(17)
            self.assertEqual(calls, [5, 15, 28, 16])
            self.assertEqual(closed, [42, 41])
            self.assertNotIn(17, closed)
