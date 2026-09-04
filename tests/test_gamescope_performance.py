import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from io import BytesIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.adapters.steamos.gamescope_performance import GamescopePerformanceReader, PerformanceTarget


def words(*values):
    return struct.pack("=" + "I" * len(values), *values)


def event(obj, opcode, payload):
    return words(obj, ((len(payload) + 8) << 16) | opcode) + payload


def registry(name=10, version=6):
    text = b"gamescope_control\0"
    return event(2, 0, words(name, len(text)) + text + bytes(-len(text) % 4) + words(version))


def handshake(version=6, feature=1):
    return (registry(version=version) + event(3, 0, words(7)) + event(1, 1, words(3))
            + event(4, 0, words(7, feature, 0)) + event(4, 0, words(0, 0, 0))
            + event(5, 0, words(8)))


class Stream:
    def __init__(self, data, fragment=3):
        self.data = data
        self.fragment = fragment
        self.sent = []
        self.closed = False
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)

    def sendall(self, data):
        self.sent.append(data)

    def recvmsg(self, size, ancillary_size):
        count = min(size, self.fragment)
        part, self.data = self.data[:count], self.data[count:]
        return part, [], 0, None

    def close(self):
        self.closed = True


class PerformanceReaderTests(unittest.TestCase):
    def setUp(self):
        self.target = PerformanceTarget(Path.cwd() / "gamescope-resolved", 1000, 4321, 42, "opaque-game-generation", 12345)

    def query(self, data, **changes):
        self.stream = Stream(data)
        values = dict(clock=lambda: 10.0, connect=lambda target, timeout: self.stream, same_process=lambda target: True)
        values.update(changes)
        # POSIX recvmsg constants are unavailable on the Windows fixture host.
        import hdm.adapters.steamos.gamescope_performance as module
        with patch.multiple(module.socket, CMSG_SPACE=lambda size: size + 16, SCM_RIGHTS=1, MSG_CTRUNC=8, MSG_TRUNC=32, create=True):
            return GamescopePerformanceReader(**values).observe(self.target)

    def test_fragmented_protocol_returns_app_bound_presented_delta(self):
        result = self.query(handshake() + event(4, 3, words(42, 20_000_000, 0)))
        self.assertEqual(result.code, "performance.observed")
        self.assertEqual(result.instantaneous_fps, 50)
        self.assertEqual(result.received_at_ms, 10_000)
        self.assertEqual(result.context_key, self.target.context_key)
        self.assertTrue(self.stream.closed)
        outgoing = [struct.unpack("=II", packet[:8]) for packet in self.stream.sent]
        self.assertEqual([(obj, word & 0xFFFF) for obj, word in outgoing], [(1, 1), (1, 0), (2, 0), (1, 0), (4, 6)])
        self.assertEqual(self.stream.sent[-1], event(4, 6, words(42)))
        self.assertIn(b"gamescope_control\0", self.stream.sent[2])
        self.assertEqual(self.stream.sent[2][-8:], words(6, 4))

    def test_high_word_preserved_and_slow_frames_not_mislabeled_invalid(self):
        result = self.query(handshake() + event(4, 3, words(42, 10, 1)))
        self.assertEqual(result.frame_time_ns, (1 << 32) + 10)

    def test_old_or_missing_or_ambiguous_protocol_never_requests_stats(self):
        for data in (handshake(version=5), event(3, 0, words(1)), registry() + registry(name=11) + event(3, 0, words(1))):
            with self.subTest(data=data):
                self.assertEqual(self.query(data).code, "performance.protocol_unavailable")
                self.assertEqual(len(self.stream.sent), 2)

    def test_missing_feature_never_requests_stats(self):
        self.assertEqual(self.query(handshake(feature=0)).code, "performance.feature_unavailable")
        self.assertEqual(len(self.stream.sent), 4)

    def test_zero_wrong_app_and_malformed_reply_remain_unavailable(self):
        for payload in (words(42, 0, 0), words(43, 1, 0), words(42, 1)):
            self.assertEqual(self.query(handshake() + event(4, 3, payload)).code, "performance.unavailable")
            self.assertTrue(self.stream.closed)

    def test_disconnect_and_protocol_error_are_redacted_and_close(self):
        for data in (b"", handshake(), event(1, 0, b"private-error\0\0\0")):
            self.assertEqual(self.query(data).code, "performance.unavailable")
            self.assertTrue(self.stream.closed)

    def test_global_removal_discards_pending_request(self):
        self.assertEqual(self.query(handshake() + event(2, 1, words(10))).code, "performance.protocol_unavailable")

    def test_deadline_covers_connect_and_handshake(self):
        ticks = iter((10.0, 10.0, 11.0))
        self.assertEqual(self.query(handshake(), clock=lambda: next(ticks)).code, "performance.timeout")
        self.assertTrue(self.stream.closed)
        self.assertEqual(self.stream.sent, [])

    def test_process_generation_revalidated_before_and_after(self):
        for results in ((False,), (True, False)):
            checks = iter(results)
            reading = self.query(handshake() + event(4, 3, words(42, 1, 0)), same_process=lambda target: next(checks))
            self.assertEqual(reading.code, "performance.context_changed")
            self.assertIsNone(reading.frame_time_ns)

    def test_final_validation_cannot_refresh_receipt_time_or_exceed_deadline(self):
        for delay, expected in ((0.2, "performance.observed"), (0.6, "performance.timeout")):
            now = [10.0]
            calls = [0]
            def validate(target):
                calls[0] += 1
                if calls[0] == 2:
                    now[0] += delay
                return True
            result = self.query(handshake() + event(4, 3, words(42, 20_000_000, 0)), clock=lambda: now[0], same_process=validate)
            self.assertEqual(result.code, expected)
            self.assertEqual(result.received_at_ms, 10_000 if delay < 0.5 else None)

    def test_dead_process_generation_is_not_live_identity(self):
        from hdm.adapters.steamos.gamescope_performance import _same_process
        for state, expected in ((b"S", True), (b"Z", False), (b"X", False), (b"x", False)):
            data = b"4321 (gamescope) " + state + b" 0" * 18 + b" 12345"
            with patch.object(Path, "open", return_value=BytesIO(data)):
                self.assertEqual(_same_process(self.target), expected)

    def test_message_size_and_total_event_budget_are_bounded(self):
        for data in (words(2, 7 << 16), words(2, 16_388 << 16), event(1, 1, words(3)) * 513):
            self.assertEqual(self.query(data).code, "performance.unavailable")
            self.assertTrue(self.stream.closed)

    def test_invalid_timeout_and_target_are_rejected(self):
        for timeout in (0, -1, 3, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                GamescopePerformanceReader(timeout_seconds=timeout)
        with self.assertRaises(ValueError):
            PerformanceTarget(Path("relative"), 1000, 10, 42, "key", 1)

    def test_unexpected_descriptor_is_closed_and_never_processed(self):
        import hdm.adapters.steamos.gamescope_performance as module
        stream = Stream(handshake())
        stream.recvmsg = lambda size, budget: (words(2, 8 << 16), [(module.socket.SOL_SOCKET, 1, struct.pack("=i", 123))], 0, None)
        with patch.multiple(module.socket, CMSG_SPACE=lambda size: size + 16, SCM_RIGHTS=1, MSG_CTRUNC=8, MSG_TRUNC=32, create=True), patch.object(module.os, "close") as close:
            result = GamescopePerformanceReader(clock=lambda: 10.0, connect=lambda *_: stream, same_process=lambda _: True).observe(self.target)
        self.assertEqual(result.code, "performance.unavailable")
        close.assert_called_once_with(123)
        self.assertTrue(stream.closed)
