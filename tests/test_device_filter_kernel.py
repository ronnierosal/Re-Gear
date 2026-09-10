import ctypes
import errno
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.delivery import device_filter_kernel as kernel


class DeviceFilterKernelTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("system", "Linux"), ("machine", "x86_64")):
            patcher = patch.object(kernel.platform, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.identity = kernel.LinkIdentity(10, 20, 30)
        self.actual = [3, 10, 20, 30, 6]
        self.closed = []
        self.calls = []
        self.fail = None
        self.error = errno.EEXIST
        self.token = "a" * 64

    def syscall(self, nr, command, ptr, size):
        self.assertEqual(nr, 321)
        self.calls.append(command)
        if command == self.fail:
            ctypes.set_errno(self.error)
            return -1
        if command in (6, 7):
            self.assertEqual(size, 16)
            attr = ctypes.cast(ptr, ctypes.POINTER(kernel.ObjectAttr)).contents
            self.assertEqual(ctypes.string_at(attr.pathname),
                             ("/proc/self/fd/8/" + self.token).encode())
            self.assertEqual(attr.file_flags, 0)
            self.assertEqual(attr.bpf_fd, 44 if command == 6 else 0)
            return 44 if command == 7 else 0
        if command == 15:
            attr = ctypes.cast(ptr, ctypes.POINTER(kernel.InfoAttr)).contents
            self.assertEqual(attr.bpf_fd, 44)
            self.assertEqual(attr.info_len, 32)
            info = ctypes.cast(attr.info, ctypes.POINTER(kernel.LinkInfo)).contents
            info.type, info.id, info.prog_id, info.cgroup_id, info.attach_type = self.actual
            return 0
        if command == 34:
            self.assertEqual(size, 8)
            attr = ctypes.cast(ptr, ctypes.POINTER(kernel.DetachAttr)).contents
            self.assertEqual((attr.link_fd, attr.reserved), (44, 0))
            return 0
        raise AssertionError("unexpected syscall")

    def controller(self):
        return kernel.CgroupDeviceLink(syscall=self.syscall, close_fd=self.closed.append)

    def test_uapi_offsets(self):
        self.assertEqual(kernel.LinkInfo.cgroup_id.offset, 16)
        self.assertEqual(kernel.LinkInfo.attach_type.offset, 24)
        self.assertEqual(ctypes.sizeof(kernel.LinkInfo), 32)
        self.assertEqual(kernel.ObjectAttr.bpf_fd.offset, 8)
        self.assertEqual(kernel.ObjectAttr.file_flags.offset, 12)

    def test_only_object_get_enoent_is_direct_pin_absence(self):
        self.error=errno.ENOENT
        for method in ('recover','recover_detached'):
            self.fail=7
            with self.controller() as value:
                with self.assertRaises(kernel.DirectPinAbsent):getattr(value,method)(8,self.token,self.identity)
            self.fail=15
            with self.controller() as value:
                with self.assertRaises(FileNotFoundError) as error:getattr(value,method)(8,self.token,self.identity)
                self.assertNotIsInstance(error.exception,kernel.DirectPinAbsent)
        self.assertEqual(self.closed,[44,44])

    def test_recover_pin_detach_exact_held_link(self):
        with self.controller() as value:
            value.recover(8, self.token, self.identity)
            value.pin(8, self.token, self.identity)
            value.detach(self.identity)
        self.assertEqual(self.calls, [7, 15, 15, 6, 15, 34])
        self.assertEqual(self.closed, [44])

    def test_wrong_identity_cannot_recover_or_detach(self):
        for index in range(5):
            with self.subTest(field=index):
                original = self.actual[index]
                self.actual[index] += 1
                self.calls.clear()
                with self.controller() as value:
                    with self.assertRaises((ValueError, RuntimeError)):
                        value.recover(8, self.token, self.identity)
                    self.assertIsNone(value.link_fd)
                    value.link_fd = 44
                    with self.assertRaises((ValueError, RuntimeError)):
                        value.detach(self.identity)
                self.assertNotIn(34, self.calls)
                self.actual[index] = original

    def test_detach_revalidates_after_successful_recovery(self):
        with self.controller() as value:
            value.recover(8, self.token, self.identity)
            self.actual[3] += 1
            with self.assertRaises(RuntimeError):
                value.detach(self.identity)
        self.assertNotIn(34, self.calls)

    def test_pin_existing_name_propagates_without_detach_or_overwrite(self):
        with self.controller() as value:
            value.recover(8, self.token, self.identity)
            self.fail = 6
            with self.assertRaises(OSError) as result:
                value.pin(8, self.token, self.identity)
            self.assertEqual(result.exception.errno, errno.EEXIST)
        self.assertEqual(self.calls, [7, 15, 15, 6])

    def test_syscall_failure_closes_only_acquired_descriptor(self):
        for command, expected in ((7, []), (15, [44]), (34, [44])):
            self.closed.clear()
            self.fail = command
            with self.subTest(command=command), self.assertRaises(OSError):
                with self.controller() as value:
                    value.recover(8, self.token, self.identity)
                    value.detach(self.identity)
            self.assertEqual(self.closed, expected)

    def test_close_does_not_detach_or_unpin(self):
        value = self.controller()
        value.recover(8, self.token, self.identity)
        value.close()
        value.close()
        self.assertEqual(self.calls, [7, 15])
        self.assertEqual(self.closed, [44])

    def test_tokens_and_identity_reject_before_object_access(self):
        with self.controller() as value:
            for token in ("", "a" * 63, "a" * 65, "../" + "a" * 61, "A" * 64, None):
                with self.assertRaises(ValueError):
                    value.recover(8, token, self.identity)
            for fd in (-1, True, "8"):
                with self.assertRaises(ValueError):
                    value.recover(fd, self.token, self.identity)
            with self.assertRaises(ValueError):
                value.recover(8, self.token, None)
        self.assertEqual(self.calls, [])
        for values in ((True, 20, 30), (0, 20, 30), (1 << 32, 20, 30), (10, 20, 1 << 64)):
            with self.assertRaises(ValueError):
                kernel.LinkIdentity(*values)

    def test_wrong_architecture(self):
        with patch.object(kernel.platform, "machine", return_value="aarch64"):
            with self.assertRaises(RuntimeError):
                self.controller()

    def test_cleanup_only_accepts_exact_detached_link_without_mutation(self):
        self.actual[3] = 0
        with self.controller() as value:
            self.assertEqual(value.recover_detached(8, self.token, self.identity), 44)
            with self.assertRaises(ValueError):
                value.link_identity()
            with self.assertRaises(ValueError):
                value.detach(self.identity)
            with self.assertRaises(ValueError):
                value.pin(8, self.token, self.identity)
        self.assertEqual(self.closed, [44])
        self.assertNotIn(34, self.calls)
        self.assertNotIn(6, self.calls)

    def test_active_recovery_rejects_detached_link(self):
        self.actual[3] = 0
        with self.controller() as value:
            with self.assertRaises(ValueError):
                value.recover(8, self.token, self.identity)
            self.assertIsNone(value.link_fd)
        self.assertEqual(self.closed, [44])

    def test_cleanup_only_rejects_active_and_each_mismatched_field(self):
        for actual in ([3, 10, 20, 30, 6], [3, 10, 20, 31, 6],
                       [3, 11, 20, 0, 6], [3, 10, 21, 0, 6],
                       [4, 10, 20, 0, 6], [3, 10, 20, 0, 7]):
            self.actual = actual
            with self.subTest(actual=actual), self.controller() as value:
                with self.assertRaises(RuntimeError):
                    value.recover_detached(8, self.token, self.identity)
                self.assertIsNone(value.link_fd)
        self.assertNotIn(34, self.calls)

    def test_cleanup_only_rejects_missing_expected_and_owned_handle(self):
        with self.controller() as value:
            with self.assertRaises(ValueError):
                value.recover_detached(8, self.token, None)
            value.link_fd = 44
            with self.assertRaises(RuntimeError):
                value.recover_detached(8, self.token, self.identity)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
