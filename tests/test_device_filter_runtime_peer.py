from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
import stat
import unittest
from unittest.mock import Mock, patch

from backend.hdm.delivery.device_filter_peer import HeldWaitingPeer, WaitingPeerIdentity
from backend.hdm.delivery.device_filter_runtime_peer import (validate_runtime_cmdline, observe_runtime_peer,
    validate_session_entry_cmdline,observe_session_entry_runtime_peer,SessionEntryRuntimeObservation,RuntimePeerObservation)
from tests.test_device_filter_runtime_store import bundle


class RuntimePeerTests(unittest.TestCase):
    def setUp(self):
        self.bundle = bundle()
        self.unit = "steam-launcher.service"
        self.raw = "\0".join(self.bundle.steam_argv) + "\0"
        self.identity = WaitingPeerIdentity(123, 1000, 456, "a" * 32, self.unit, "/cgroup", 1, 2)
        self.held = HeldWaitingPeer(123, 1000, None, None, 7, 8, 9, self.identity)
        self.held.revalidate = Mock(return_value=self.identity)
        self.store = Mock()
        self.store.verify.return_value = SimpleNamespace(digest=self.bundle.digest)
        self.exe = SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_dev=1, st_ino=22)

    def test_exact_isolated_command_required(self):
        validate_runtime_cmdline(self.raw, self.bundle, self.unit)
        for raw in (self.raw[:-1], self.raw.replace("-I", "-E"),
                    self.raw.replace(self.bundle.path, "/tmp/run.pyz"), self.raw + "extra\0",
                    self.raw.replace("steam", "session"), "x" * 65537):
            with self.assertRaises(ValueError):
                validate_runtime_cmdline(raw, self.bundle, self.unit)
        with self.assertRaises(ValueError):
            validate_runtime_cmdline(self.raw, self.bundle, "other.service")

    def test_gamescope_retains_native_arguments_only_after_fixed_prefix(self):
        raw = "\0".join(("/usr/bin/python3", "-I", self.bundle.path, "gamescope", "--hdr-enabled")) + "\0"
        validate_runtime_cmdline(raw, self.bundle, "gamescope-session.service")
        with self.assertRaises(ValueError):
            validate_runtime_cmdline(raw.replace("-I\0", "-I\0-c\0"), self.bundle, "gamescope-session.service")

    def observe(self, *, stats=None):
        @contextmanager
        def expected():
            yield self.exe
        prefix = "backend.hdm.delivery.device_filter_runtime_peer."
        with patch(prefix + "_python_executable", expected), patch(prefix + "_read_at", return_value=self.raw), \
             patch(prefix + "os.stat", side_effect=stats or [self.exe, self.exe]):
            return observe_runtime_peer(self.held, self.bundle, store=self.store)

    def test_source_and_lifetime_rechecked(self):
        result = self.observe()
        self.assertEqual(result.runtime_digest, self.bundle.digest)
        self.assertEqual(result.identity, self.identity)
        self.assertEqual(self.held.revalidate.call_count, 2)
        self.store.verify.assert_called_once_with(self.bundle)
        self.assertFalse(hasattr(result, "disconnect_clearance"))

    def test_exec_or_lifetime_change_rejected(self):
        other = SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_dev=1, st_ino=23)
        for stats in ([other], [self.exe, other]):
            with self.assertRaises(ValueError):
                self.observe(stats=stats)
        self.held.revalidate.side_effect = [self.identity, replace(self.identity, starttime=457)]
        with self.assertRaises(ValueError):
            self.observe()

    def test_missing_source_or_peer_does_not_produce_observation(self):
        self.store.verify.side_effect = OSError("source unavailable")
        with self.assertRaises(OSError):
            self.observe()
        with self.assertRaises(ValueError):
            observe_runtime_peer(object(), self.bundle, store=self.store)

    def test_session_entry_role_is_exact_and_separate(self):
        raw='\0'.join(self.bundle.session_argv)+'\0'
        validate_session_entry_cmdline(raw,self.bundle,'gamescope-session.service')
        for changed in (raw+'extra\0',raw.replace('session\0','gamescope\0'),self.raw):
            with self.assertRaises(ValueError):validate_session_entry_cmdline(changed,self.bundle,'gamescope-session.service')
        with self.assertRaises(ValueError):validate_runtime_cmdline(raw,self.bundle,'gamescope-session.service')
        identity=replace(self.identity,unit='gamescope-session.service')
        self.held.revalidate.return_value=identity
        @contextmanager
        def expected():yield self.exe
        prefix='backend.hdm.delivery.device_filter_runtime_peer.'
        with patch(prefix+'_python_executable',expected),patch(prefix+'_read_at',return_value=raw),patch(prefix+'os.stat',return_value=self.exe):
            result=observe_session_entry_runtime_peer(self.held,self.bundle,store=self.store)
        self.assertIs(type(result),SessionEntryRuntimeObservation)
        self.assertIsNot(type(result),RuntimePeerObservation)
        self.assertEqual(result.purpose,'prepare_and_withhold_session_entry')


if __name__ == "__main__":
    unittest.main()
