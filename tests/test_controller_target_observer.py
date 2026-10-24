"""Synthetic evdev records and injected I/O only; never open an input device."""

import stat
import struct
import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from backend.regear.delivery import controller_target_observer as observer
from backend.regear.delivery.controller_target_observer import (
    Limits, NodeIdentity, VerifiedTarget, observe,
)


def event(us, code, value, *, kind=1, bits=64, endian="little"):
    prefix = "<" if endian == "little" else ">"
    layout = struct.Struct(prefix + ("qqHHi" if bits == 64 else "iiHHi"))
    return layout.pack(us // 1_000_000, us % 1_000_000, kind, code, value)


class FakeIO:
    def __init__(self, chunks=()):
        self.now = 100.0
        self.chunks = list(chunks)
        self.identity = NodeIdentity(stat.S_IFCHR | 0o600, 1, 2, 3)
        self.opened = []
        self.closed = []
        self.reads = 0
        self.waits = []
        self.after_open = None
        self.on_wait = None
        self.failure = None

    def monotonic(self):
        return self.now

    def lstat(self, path):
        return self.identity

    def open(self, path, flags):
        self.opened.append((path, flags))
        if self.failure == "open":
            raise OSError("private fixture path must not escape")
        if self.after_open:
            self.identity = self.after_open
        return 17

    def fstat(self, fd):
        return self.identity

    def wait(self, fd, timeout):
        self.waits.append(timeout)
        self.now += min(timeout, 0.01) if self.chunks else timeout
        if self.on_wait:
            return self.on_wait(self)
        return "ready" if self.chunks else "timeout"

    def read(self, fd, size):
        self.reads += 1
        if self.failure == "read":
            raise OSError("private fixture content must not escape")
        data = self.chunks.pop(0)
        if len(data) > size:
            self.chunks.insert(0, data[size:])
        return data[:size]

    def close(self, fd):
        self.closed.append(fd)
        if self.failure == "close":
            raise OSError("private fixture close detail")


TARGET = VerifiedTarget("/dev/input/event7", 1, 2, 3, 100.0, True,
                        menu_code=316, a_code=304, word_bits=64, byteorder="little")
LIMITS = Limits(seconds=0.2, max_records=128, max_facts=32, poll_seconds=0.02)


class ControllerTargetObserverTests(unittest.TestCase):
    def run_fixture(self, chunks=(), *, target=TARGET, limits=LIMITS, cancelled=lambda: False):
        io = FakeIO(chunks)
        result = observe(target, io=io, limits=limits, cancelled=cancelled)
        return result, io

    def test_observed_chord_order_duration_repeat_and_overlap(self):
        data = (event(1_000_000, 316, 1) + event(1_010_000, 304, 1)
                + event(1_012_000, 304, 2) + event(1_020_000, 304, 0)
                + event(1_030_000, 316, 0))
        result, io = self.run_fixture([data])
        self.assertEqual(result.reason, "deadline")
        self.assertEqual([(f.button, f.kind) for f in result.facts],
                         [("menu", "press"), ("a", "press"), ("a", "repeat"),
                          ("a", "release"), ("both", "overlap"), ("menu", "release")])
        self.assertEqual([f.duration_us for f in result.facts if f.kind == "release"], [10_000, 30_000])
        self.assertEqual(next(f.duration_us for f in result.facts if f.kind == "overlap"), 10_000)
        self.assertEqual(io.closed, [17])
        flags = io.opened[0][1]
        self.assertEqual(flags & 3, 0)  # Linux O_ACCMODE / O_RDONLY.
        self.assertTrue(flags & 0x800)  # Linux O_NONBLOCK.
        self.assertTrue(flags & 0x80000)  # Linux O_CLOEXEC.
        self.assertTrue(flags & 0x20000)  # Linux O_NOFOLLOW.

    def test_explicit_32_and_64_bit_little_and_big_endian_fixtures(self):
        for bits in (32, 64):
            for endian in ("little", "big"):
                with self.subTest(bits=bits, endian=endian):
                    data = event(1_000_000, 304, 1, bits=bits, endian=endian)
                    result, _ = self.run_fixture([data], target=replace(TARGET, word_bits=bits, byteorder=endian))
                    self.assertEqual(result.facts[0].button, "a")

    def test_symlink_regular_file_and_identity_mismatch_never_open(self):
        for identity in (NodeIdentity(stat.S_IFLNK, 1, 2, 3), NodeIdentity(stat.S_IFREG, 1, 2, 3),
                         NodeIdentity(stat.S_IFCHR, 1, 99, 3), NodeIdentity(stat.S_IFCHR, 1, 2, 99)):
            io = FakeIO(); io.identity = identity
            result = observe(TARGET, io=io, limits=LIMITS)
            self.assertEqual(result.reason, "identity_mismatch")
            self.assertEqual(io.opened, [])

    def test_post_open_identity_race_closes_without_collecting(self):
        io = FakeIO([event(0, 304, 1)])
        io.after_open = NodeIdentity(stat.S_IFCHR, 1, 99, 3)
        result = observe(TARGET, io=io, limits=LIMITS)
        self.assertEqual(result.reason, "identity_mismatch")
        self.assertEqual(io.reads, 0)
        self.assertEqual(io.closed, [17])

    def test_invalid_or_stale_target_and_limits_never_open(self):
        targets = [replace(TARGET, path=p) for p in ("/dev/input/by-id/pad", "/tmp/event7", "/dev/input/../event7")]
        targets += [replace(TARGET, verified_at=t) for t in (97.0, 101.0, float("nan"))]
        targets += [replace(TARGET, virtual_confirmed=False), replace(TARGET, menu_code=304),
                    replace(TARGET, word_bits=16), replace(TARGET, byteorder="native")]
        for target in targets:
            result, io = self.run_fixture(target=target)
            self.assertEqual(result.reason, "invalid_request")
            self.assertEqual(io.opened, [])
        for limits in (replace(LIMITS, seconds=46), replace(LIMITS, seconds=float("nan")),
                       replace(LIMITS, max_records=0), replace(LIMITS, max_facts=0)):
            result, io = self.run_fixture(limits=limits)
            self.assertEqual(result.reason, "invalid_request")
            self.assertEqual(io.opened, [])

    def test_partial_record_disconnect_loss_and_bad_event_stop_and_close(self):
        fixtures = [(b"partial", "truncated_record"), (b"", "disconnected"),
                    (event(0, 3, 0, kind=0), "event_loss"),
                    (event(0, 304, 9), "invalid_event")]
        for data, reason in fixtures:
            result, io = self.run_fixture([data])
            self.assertEqual(result.reason, reason)
            self.assertFalse(result.timing_valid)
            self.assertEqual(io.closed, [17])

    def test_cancel_before_open_and_after_wait_performs_no_read(self):
        result, io = self.run_fixture(cancelled=lambda: True)
        self.assertEqual(result.reason, "cancelled"); self.assertEqual(io.opened, [])
        io = FakeIO([event(0, 304, 1)])
        result = observe(TARGET, io=io, limits=LIMITS, cancelled=lambda: io.now > 100.0)
        self.assertEqual(result.reason, "cancelled"); self.assertEqual(io.reads, 0)
        self.assertEqual(io.closed, [17])

    def test_final_deadline_is_checked_before_read(self):
        io = FakeIO([event(0, 304, 1)])
        def late(port):
            port.now = 100.3
            return "ready"
        io.on_wait = late
        result = observe(TARGET, io=io, limits=LIMITS)
        self.assertEqual(result.reason, "deadline"); self.assertEqual(io.reads, 0)
        self.assertEqual(io.closed, [17])

    def test_clock_regression_and_event_clock_jump_fail_closed(self):
        result, _ = self.run_fixture([event(2_000, 304, 1) + event(1_000, 304, 0)])
        self.assertEqual(result.reason, "event_clock_invalid")
        result, _ = self.run_fixture([event(0, 304, 1) + event(50_000_000, 304, 0)])
        self.assertEqual(result.reason, "event_clock_invalid")
        io = FakeIO([event(0, 304, 1)])
        io.on_wait = lambda port: setattr(port, "now", 99.0) or "ready"
        result = observe(TARGET, io=io, limits=LIMITS)
        self.assertEqual(result.reason, "clock_invalid"); self.assertEqual(io.reads, 0)

    def test_fact_and_record_bounds_close_without_unbounded_output(self):
        data = b"".join(event(n * 1000, 304, n % 2) for n in range(20))
        result, io = self.run_fixture([data], limits=replace(LIMITS, max_facts=3))
        self.assertEqual(result.reason, "output_limit"); self.assertLessEqual(len(result.facts), 3)
        self.assertEqual(io.closed, [17])
        result, _ = self.run_fixture([data], limits=replace(LIMITS, max_records=3))
        self.assertEqual(result.reason, "record_limit"); self.assertEqual(result.record_count, 3)

    def test_initial_release_and_repeat_do_not_invent_prior_press_duration(self):
        result, _ = self.run_fixture([event(0, 304, 0) + event(1000, 316, 2)])
        self.assertEqual([f.duration_us for f in result.facts], [None, None])
        self.assertFalse(any(f.kind == "overlap" for f in result.facts))

    def test_oversized_port_result_is_rejected_without_decoding(self):
        io = FakeIO()
        io.on_wait = lambda port: "ready"
        io.read = lambda fd, size: b"x" * (size + 1)
        result = observe(TARGET, io=io, limits=LIMITS)
        self.assertEqual(result.reason, "read_error")
        self.assertEqual(result.record_count, 0)
        self.assertEqual(io.closed, [17])

    def test_duplicate_press_does_not_reset_observed_duration(self):
        result, _ = self.run_fixture([event(0, 304, 1) + event(5000, 304, 1) + event(10000, 304, 0)])
        self.assertEqual(result.facts[-1].duration_us, 10000)

    def test_poll_read_and_close_failures_are_sanitized_and_never_reopen(self):
        for failure in ("open", "read", "close"):
            io = FakeIO([event(0, 304, 1)]); io.failure = failure
            result = observe(TARGET, io=io, limits=LIMITS)
            self.assertEqual(result.reason, failure + "_error")
            self.assertNotIn("private", repr(result))
            self.assertNotIn("/dev/", repr(result))
            self.assertEqual(len(io.opened), 1)
            self.assertEqual(io.closed, [] if failure == "open" else [17])
            if failure == "close": self.assertFalse(result.descriptor_closed)
        for state in ("error", "disconnected"):
            io = FakeIO(); io.on_wait = lambda port, state=state: state
            result = observe(TARGET, io=io, limits=LIMITS)
            self.assertEqual(result.reason, "poll_error" if state == "error" else "disconnected")
            self.assertEqual(io.closed, [17])

    def test_system_adapter_with_only_mocked_syscalls_and_poll(self):
        bits = struct.calcsize("@l") * 8
        io = FakeIO([event(0, 304, 1, bits=bits, endian=sys.byteorder)
                     + event(10000, 304, 0, bits=bits, endian=sys.byteorder)])
        native_stat = SimpleNamespace(st_mode=io.identity.mode, st_dev=1, st_ino=2, st_rdev=3)
        class Poll:
            def register(self, fd, flags):
                self.fd = fd
            def poll(self, milliseconds):
                state = io.wait(self.fd, milliseconds / 1000)
                return [(self.fd, 1)] if state == "ready" else []
        fake_select = SimpleNamespace(poll=Poll, POLLIN=1, POLLERR=8, POLLHUP=16, POLLNVAL=32)
        with patch.dict(sys.modules, {"select": fake_select}), \
                patch.object(sys, "platform", "linux"), \
                patch.object(observer.os, "lstat", return_value=native_stat) as lstat_mock, \
                patch.object(observer.os, "open", side_effect=io.open), \
                patch.object(observer.os, "fstat", return_value=native_stat), \
                patch.object(observer.SystemIO, "read", side_effect=io.read), \
                patch.object(observer.SystemIO, "close", side_effect=io.close), \
                patch.object(observer.SystemIO, "monotonic", side_effect=io.monotonic):
            result = observe(replace(TARGET, word_bits=bits, byteorder=sys.byteorder), limits=LIMITS)
        self.assertEqual(result.reason, "deadline")
        self.assertEqual(result.facts[-1].duration_us, 10000)
        self.assertEqual(io.closed, [17])
        lstat_mock.assert_called_once_with(TARGET.path)

    def test_wrong_native_abi_is_rejected_before_any_node_access(self):
        wrong_bits = 32 if struct.calcsize("@l") == 8 else 64
        with patch.object(sys, "platform", "linux"), \
                patch.object(observer.SystemIO, "monotonic", return_value=100.0), \
                patch.object(observer.SystemIO, "lstat") as node:
            result = observe(replace(TARGET, word_bits=wrong_bits), limits=LIMITS)
        self.assertEqual(result.reason, "invalid_request")
        node.assert_not_called()

    def test_keyboard_interrupt_and_post_wait_identity_loss_close(self):
        io = FakeIO([event(0, 304, 1)])
        io.read = lambda fd, size: (_ for _ in ()).throw(KeyboardInterrupt())
        result = observe(TARGET, io=io, limits=LIMITS)
        self.assertEqual(result.reason, "cancelled"); self.assertEqual(io.closed, [17])
        io = FakeIO([event(0, 304, 1)])
        def changed(port):
            port.identity = NodeIdentity(stat.S_IFCHR, 1, 99, 3)
            return "ready"
        io.on_wait = changed
        result = observe(TARGET, io=io, limits=LIMITS)
        self.assertEqual(result.reason, "identity_mismatch")
        self.assertEqual(io.reads, 0); self.assertEqual(io.closed, [17])
