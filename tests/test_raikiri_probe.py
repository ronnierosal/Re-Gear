"""Synthetic protocol tests, not recordings or hardware support evidence."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("raikiri_probe", Path(__file__).resolve().parents[1] / "scripts/raikiri_probe.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def descriptor():
    # Two vendor application collections, each report has 63 payload bytes.
    return bytes.fromhex("06 03 ff 09 01 a1 01 85 b0 75 08 95 3f 81 02 91 02 c0 "
                         "06 c3 ff 09 01 a1 01 85 b3 75 08 95 3f 81 02 c0")


def report(bank=2, left=0, right=0):
    data = bytearray(64)
    data[0], data[3], data[5], data[6] = 0xB3, bank, left, right
    return bytes(data)


ACK = bytes.fromhex("b0 51 36 01") + bytes(60)
REJECT = bytes.fromhex("b0 ff aa") + bytes(61)


class FakeDevice:
    def __init__(self, packets=(), baseline=()):
        self.packets, self.baseline = list(packets), list(baseline)
        self.writes = []
        self.now = 0.0
        self.short_write = False

    def read(self, timeout):
        if timeout == 0:
            return self.baseline.pop(0) if self.baseline else b""
        self.now += timeout
        return self.packets.pop(0) if self.packets else b""

    def write(self, data):
        self.writes.append(data)
        return len(data) - int(self.short_write)


class RaikiriProbeTests(unittest.TestCase):
    def run_capture(self, device, enable=False, seconds=4):
        rows = []
        result = probe.capture(device, rows.append, seconds, enable, lambda: device.now)
        return rows, result

    def test_descriptor_exact_vendor_layout(self):
        self.assertTrue(probe.descriptor_supported(descriptor()))

    def test_descriptor_rejects_wrong_length_page_and_truncation(self):
        raw = descriptor()
        for data in (raw[:-1], raw.replace(b"\x95\x3f", b"\x95\x40"), raw.replace(b"\xc3\xff", b"\xc2\xff"), b"\xfe", b"\xb4", b"\xc0", b""):
            with self.subTest(data=data.hex()):
                self.assertFalse(probe.descriptor_supported(data))

    def test_descriptor_rejects_duplicate_report_id_elsewhere(self):
        self.assertFalse(probe.descriptor_supported(descriptor() + bytes.fromhex("06 04 ff 09 01 a1 01 85 b3 75 08 95 3f 81 02 c0")))

    def test_descriptor_global_push_pop(self):
        raw = descriptor().replace(b"\x95\x3f", b"\x95\x3f\xa4\x75\x01\xb4")
        self.assertTrue(probe.descriptor_supported(raw))

    def test_front_release_hold_and_both_are_unverified_snapshots(self):
        for left, right, expected in ((0, 0, []), (1, 0, ["command_candidate"]), (0, 1, ["library_candidate"]), (1, 1, ["command_candidate", "library_candidate"])):
            decoded = probe.decode_report(report(left=left, right=right))
            self.assertFalse(decoded["verified"])
            self.assertEqual(decoded["pressed"], expected)

    def test_rear_bank_does_not_become_front(self):
        self.assertEqual(probe.decode_report(report(bank=0, left=1))["pressed"], ["rear_1"])

    def test_unknown_reports_do_not_create_candidate(self):
        for data in (b"", report()[:9], report() + b"\x00", report(bank=1), report(left=2), bytes(64)):
            self.assertEqual(probe.decode_report(data)["kind"], "unknown")

    def test_passive_never_writes_even_with_ack(self):
        dev = FakeDevice([ACK, report(left=1)])
        rows, result = self.run_capture(dev)
        self.assertEqual(dev.writes, [])
        self.assertEqual(result["activation"], "passive")
        self.assertTrue(any(row.get("decoded", {}).get("kind") == "candidate" for row in rows))

    def test_enable_exactly_once_ack_is_not_hardware_verification(self):
        dev = FakeDevice([ACK, report(left=1)])
        _, result = self.run_capture(dev, True)
        self.assertEqual(dev.writes, [bytes.fromhex("b0 51 36 01 00 01") + bytes(58)])
        self.assertEqual(result["activation"], "ack")
        self.assertFalse(result["hardware_verified"])

    def test_stale_ack_in_baseline_cannot_confirm_write(self):
        dev = FakeDevice(baseline=[ACK])
        rows, result = self.run_capture(dev, True)
        self.assertEqual(rows[0]["phase"], "baseline")
        self.assertEqual(result["activation"], "timeout")
        self.assertEqual(len(dev.writes), 1)
        self.assertLess(dev.now, 3.1)

    def test_rejection_stops_without_retry(self):
        dev = FakeDevice([REJECT, report(left=1)])
        _, result = self.run_capture(dev, True)
        self.assertEqual(result["activation"], "rejected")
        self.assertEqual(len(dev.writes), 1)
        self.assertEqual(len(dev.packets), 1)

    def test_late_ack_is_recorded_but_cannot_confirm(self):
        class LateDevice(FakeDevice):
            def read(self, timeout):
                if not timeout:
                    return b""
                self.now += 3.1
                return ACK
        rows, result = self.run_capture(LateDevice(), True)
        self.assertEqual(result["activation"], "timeout")
        self.assertTrue(any(row.get("phase") == "late_response" for row in rows))

    def test_capture_replay_keeps_phases_and_unverified_labels(self):
        rows, _ = self.run_capture(FakeDevice([ACK, report(left=1)], baseline=[report()]), True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(probe.main(["replay", str(path)]), 0)
        replayed = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(replayed[0]["phase"], "baseline")
        self.assertEqual(replayed[-1]["decoded"]["pressed"], ["command_candidate"])
        self.assertFalse(replayed[-1]["decoded"]["verified"])

    def test_replay_rejects_oversized_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.jsonl"
            path.write_text(" " * 16385, encoding="utf-8")
            with self.assertRaises(ValueError):
                probe.main(["replay", str(path)])

    def test_opened_handle_validation_and_cleanup(self):
        for correct in (True, False):
            def ioctl(fd, command, buffer, mutate):
                self.assertEqual(fd, 99)
                if command == 0x80084803:
                    buffer[:] = struct.pack("IHH", 3, probe.VID, probe.PID if correct else 0)
                elif command == 0x80044801:
                    buffer[:] = struct.pack("I", len(descriptor()))
                elif command == 0x90044802:
                    buffer[4:4 + len(descriptor())] = descriptor()
                else:
                    self.fail("Unexpected ioctl")
            with patch.object(probe.os, "O_NONBLOCK", 0x800, create=True), patch.object(probe.sys, "platform", "linux"), patch.dict(sys.modules, {"fcntl": types.SimpleNamespace(ioctl=ioctl)}), patch.object(probe.os, "open", return_value=99) as opened, patch.object(probe.os, "close") as closed, patch.object(probe.os, "write") as written:
                if correct:
                    device = probe.LinuxHidraw("fixture", False)
                    device.close()
                else:
                    with self.assertRaises(ValueError):
                        probe.LinuxHidraw("fixture", False)
                opened.assert_called_once_with("fixture", os.O_RDONLY | os.O_NONBLOCK)
                closed.assert_called_once_with(99)
                written.assert_not_called()

    def test_existing_output_stops_before_device_open(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            path.write_text("preserve", encoding="utf-8")
            with patch.object(probe.sys, "platform", "linux"), patch.object(probe, "discover", return_value=["fixture"]), patch.object(probe, "LinuxHidraw") as device:
                with self.assertRaises(FileExistsError):
                    probe.main(["capture", "--label", "baseline", "--output", str(path), "--enable-events"])
                device.assert_not_called()
            self.assertEqual(path.read_text(encoding="utf-8"), "preserve")

    def test_cli_closes_device_when_capture_fails(self):
        device = Mock()
        device.read.side_effect = OSError("disconnected")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            with patch.object(probe.sys, "platform", "linux"), patch.object(probe, "discover", return_value=["fixture"]), patch.object(probe, "LinuxHidraw", return_value=device) as opened, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(OSError):
                    probe.main(["capture", "--label", "baseline", "--output", str(path)])
            opened.assert_called_once_with("fixture", False)
            device.close.assert_called_once()
            device.write.assert_not_called()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8").splitlines()[-1])["type"], "stopped")

    def test_short_duration_cannot_claim_activation(self):
        _, result = self.run_capture(FakeDevice(), True, seconds=1)
        self.assertEqual(result["activation"], "unconfirmed")

    def test_short_write_never_retries(self):
        dev = FakeDevice()
        dev.short_write = True
        with self.assertRaises(OSError):
            self.run_capture(dev, True)
        self.assertEqual(len(dev.writes), 1)

    def test_continuous_baseline_stops_before_write(self):
        dev = FakeDevice(baseline=[ACK] * 128)
        with self.assertRaises(ValueError):
            self.run_capture(dev, True)
        self.assertEqual(dev.writes, [])

    def test_invalid_duration_stops_before_write(self):
        for seconds in (0, 121):
            dev = FakeDevice()
            with self.assertRaises(ValueError):
                self.run_capture(dev, True, seconds)
            self.assertEqual(dev.writes, [])

    def test_unrelated_reports_not_retained(self):
        rows, result = self.run_capture(FakeDevice([bytes([7]) + bytes(63)]))
        self.assertEqual(result["reports"], 1)
        self.assertFalse(any(row["type"] == "report" for row in rows))


if __name__ == "__main__":
    unittest.main()
