"""Fragmented offline Wayland protocol fixtures; no live socket is opened."""
import stat
import struct
import unittest
from dataclasses import replace
from pathlib import PurePosixPath
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_gamescope_performance import Stream, event, words
from regear.adapters.steamos.gamescope_performance import PerformanceTarget
import regear.adapters.steamos.gamescope_performance as performance
from regear.adapters.steamos.gamescope_stream_export import GamescopeStreamExportReader, StreamExportReading


def registry(name=10, version=1, interface="gamescope_pipewire"):
    text = interface.encode() + b"\0"
    return event(2, 0, words(name, len(text)) + text + bytes(-len(text) % 4) + words(version))


def handshake(*, prefix=None, node=42, events=None):
    return ((registry() if prefix is None else prefix) + event(3, 0, words(7))
            + event(1, 1, words(3))
            + (event(4, 0, words(node)) if events is None else events)
            + event(5, 0, words(8)))


class PeerStream(Stream):
    def __init__(self, data, peers=None):
        super().__init__(data, fragment=3)
        self.peers = list(peers or [(4321, 1000, 1000)] * 8)

    def getsockopt(self, *args):
        return struct.pack("=iii", *self.peers.pop(0))


class GamescopeStreamExportTests(unittest.TestCase):
    def setUp(self):
        self.target = PerformanceTarget(PurePosixPath("/run/user/1000/gamescope-0"),
                                      1000, 4321, 42, "private-session-generation", 12345)

    def query(self, data, *, peers=None, target=None, **changes):
        self.stream = PeerStream(data, peers)
        values = dict(clock=lambda: 10.0, connect=lambda target, timeout: self.stream,
                      same_process=lambda target: True)
        values.update(changes)
        with patch.multiple(performance.socket, CMSG_SPACE=lambda n: n + 16, SCM_RIGHTS=1,
                            MSG_CTRUNC=8, MSG_TRUNC=32, SO_PEERCRED=17, create=True):
            return GamescopeStreamExportReader(**values).observe(target or self.target)

    def test_fragmented_export_observation_sends_only_registry_sync_bind_sync(self):
        result = self.query(handshake())
        self.assertEqual(result.code, "export.observed")
        self.assertEqual(result.node_id, 42)
        self.assertEqual(result.context_key, self.target.context_key)
        self.assertEqual(result.received_at_ms, 10000)
        self.assertTrue(self.stream.closed)
        outgoing = [struct.unpack("=II", packet[:8]) for packet in self.stream.sent]
        self.assertEqual([(obj, word & 0xFFFF) for obj, word in outgoing], [(1, 1), (1, 0), (2, 0), (1, 0)])
        self.assertEqual(self.stream.sent[0], event(1, 1, words(2)))
        self.assertEqual(self.stream.sent[1], event(1, 0, words(3)))
        self.assertIn(b"gamescope_pipewire\0", self.stream.sent[2])
        self.assertEqual(self.stream.sent[2][-8:], words(1, 4))
        self.assertEqual(self.stream.sent[3], event(1, 0, words(5)))

    def test_only_fixed_runtime_socket_names_are_accepted(self):
        for name in ("gamescope-0", "wayland-0", "wayland-9999"):
            result = self.query(handshake(), target=replace(self.target,
                socket_path=PurePosixPath("/run/user/1000") / name))
            self.assertEqual(result.code, "export.observed")
        for path in ("/tmp/gamescope-0", "/run/user/1001/gamescope-0", "/run/user/1000/nested/gamescope-0",
                     "/run/user/1000/../gamescope-0", "/run/user/1000/wayland-10000",
                     "/run/user/1000/wayland--1", "/run/user/1000/arbitrary"):
            result = self.query(handshake(), target=replace(self.target, socket_path=PurePosixPath(path)))
            self.assertEqual(result.code, "export.target_invalid")
            self.assertEqual(self.stream.sent, [])

    def test_missing_wrong_version_and_ambiguous_global_refuse(self):
        for prefix in (b"", registry(version=0), registry(version=2),
                       registry() + registry(11), registry() + registry(),
                       registry() + event(2, 1, words(10)) + registry()):
            self.assertIn(self.query(handshake(prefix=prefix)).code, ("export.protocol_unavailable", "export.unavailable"))
            self.assertEqual(len(self.stream.sent), 2)

    def test_duplicate_other_global_names_are_ambiguous_too(self):
        prefix = registry() + registry(11, interface="wl_compositor") + registry(11, interface="wl_seat")
        self.assertIn(self.query(handshake(prefix=prefix)).code, ("export.protocol_unavailable", "export.unavailable"))

    def test_duplicate_missing_invalid_or_wrong_export_event_refuses(self):
        for events in (b"", event(4, 0, words(0)), event(4, 0, words(0xFFFFFFFF)),
                       event(4, 0, words(42)) * 2, event(4, 0, words(42, 43)),
                       event(4, 1, words(42)), event(99, 0, words(42))):
            result = self.query(handshake(events=events))
            self.assertNotEqual(result.code, "export.observed")
            self.assertIsNone(result.node_id)
            self.assertTrue(self.stream.closed)

    def test_strict_callback_delete_and_registry_events(self):
        for extra in (event(1, 1, words(99)), event(1, 1, words(3)) * 2,
                      event(3, 1, words(1)), event(2, 2, words(1)),
                      event(2, 1, words(10)), event(3, 0, words(1))):
            self.assertNotEqual(self.query(handshake(events=extra + event(4, 0, words(42)))).code, "export.observed")

    def test_partial_eof_error_and_invalid_message_bounds_close(self):
        for data in (b"", handshake()[:-1], words(2, 7 << 16), words(2, 16388 << 16),
                     event(1, 0, b"private-server-error\0"), registry()[:9]):
            result = self.query(data)
            self.assertNotEqual(result.code, "export.observed")
            self.assertIsNone(result.node_id)
            self.assertTrue(self.stream.closed)

    def test_before_and_after_process_birth_checks_require_exact_true(self):
        for answers in ((False,), (1,), ("yes",), (True, False), (True, 1)):
            checks = iter(answers)
            self.assertEqual(self.query(handshake(), same_process=lambda _: next(checks)).code,
                             "export.context_changed")

    def test_peer_credentials_must_match_before_and_after_protocol(self):
        for peers in ([(999, 1000, 1000)], [(4321, 2000, 2000)],
                      [(4321, 1000, 1000), (999, 1000, 1000)],
                      [(4321, 1000, 1000), (4321, 2000, 2000)]):
            result = self.query(handshake(), peers=peers)
            self.assertNotEqual(result.code, "export.observed")
            self.assertIsNone(result.node_id)
            self.assertTrue(self.stream.closed)

    def test_deadline_and_nonfinite_clocks_never_succeed(self):
        ticks = iter((10.0, 10.0, 11.0))
        self.assertEqual(self.query(handshake(), clock=lambda: next(ticks)).code, "export.timeout")
        for clock in (lambda: float("nan"), lambda: float("inf"), lambda: True):
            self.assertNotEqual(self.query(handshake(), clock=clock).code, "export.observed")
        now = [10.0]
        calls = [0]
        def process(_):
            calls[0] += 1
            if calls[0] == 2:
                now[0] += 0.6
            return True
        self.assertEqual(self.query(handshake(), clock=lambda: now[0], same_process=process).code, "export.timeout")

    def test_timeout_configuration_rejects_invalid_values(self):
        for value in (0, -1, 3, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                GamescopeStreamExportReader(timeout_seconds=value)

    def test_payload_is_redacted_and_never_claims_presenter(self):
        result = self.query(handshake())
        payload = result.to_payload()
        self.assertTrue(payload["export_observed"])
        self.assertNotIn("context_key", payload)
        self.assertNotIn("node_id", payload)
        for key in ("presenter_supported", "game_renderer_verified", "frame_delivery_verified", "drm_lease_verified"):
            self.assertIs(payload[key], False)
        self.assertNotIn("private", str(StreamExportReading("private-error", "private-key", 99, 10).to_payload()))

    def test_close_failure_is_categorical_and_cannot_report_export_success(self):
        with patch.object(PeerStream, "close", side_effect=OSError("private-socket-path")):
            result = self.query(handshake())
        self.assertEqual(result.code, "export.unavailable")
        self.assertIsNone(result.node_id)
        self.assertNotIn("private", str(result.to_payload()))

    def test_default_connect_rejects_wrong_peer_and_closes_socket(self):
        # Test the real shared connector without opening a socket. PurePosixPath
        # has no lstat, so supply a fixed-path test object with just that method.
        from regear.adapters.steamos.gamescope_performance import _connect
        class FixedPath:
            def lstat(self):
                return SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=1000)
            def __str__(self):
                return "/run/user/1000/gamescope-0"
        stream = PeerStream(b"", peers=[(999, 1000, 1000)])
        stream.connect = lambda path: None
        target = SimpleNamespace(socket_path=FixedPath(), uid=1000, compositor_pid=4321)
        with patch.multiple(performance.socket, SO_PEERCRED=17, AF_UNIX=1, create=True), patch.object(performance.socket, "socket", return_value=stream):
            with self.assertRaises(OSError):
                _connect(target, .5)
        self.assertTrue(stream.closed)


if __name__ == "__main__":
    unittest.main()
