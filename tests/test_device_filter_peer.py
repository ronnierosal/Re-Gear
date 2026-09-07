import unittest
import stat
import sys
import os
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.hdm.delivery.device_filter_peer import validate_peer_text, hold_waiting_peer
from backend.hdm.delivery.device_filter_protocol import FilterRequest
from backend.hdm.delivery.device_filter_transport import PeerCredentials


class PeerTests(unittest.TestCase):
    def setUp(self):
        self.request = FilterRequest(1, "op", "gamescope-session.service", "a" * 32, "b" * 64)
        self.path = "/user.slice/user-1000.slice/user@1000.service/session.slice/gamescope-session.service"
        self.properties = dict(MainPID="123", InvocationID="a" * 32, ActiveState="activating", ControlGroup=self.path)
        self.stat = "123 (python weird ) name) S " + "0 " * 18 + "456"
        self.status = "Name: python\nUid:\t1000\t1000\t1000\t1000\n"
        self.cgroup = "0::" + self.path + "\n"

    def validate(self):
        return validate_peer_text(123, 1000, self.request, self.properties, self.stat, self.status, self.cgroup)

    def test_exact_starting_service_and_parenthesized_comm(self):
        self.assertEqual(self.validate(), (456, self.path))
        self.properties["ActiveState"] = "active"
        self.validate()

    def test_wrong_main_process_invocation_state_or_slice_rejected(self):
        for key, value in (("MainPID", "124"), ("InvocationID", "c" * 32),
                           ("ActiveState", "failed"), ("ControlGroup", self.path + "/child")):
            self.setUp()
            self.properties[key] = value
            with self.assertRaises(ValueError): self.validate()

    def test_duplicate_or_changed_uid_and_membership_rejected(self):
        for text in (self.status + self.status, self.status.replace("1000", "1001", 1), ""):
            self.setUp()
            self.status = text
            with self.assertRaises(ValueError): self.validate()
        self.setUp()
        self.cgroup += "1::/other"
        with self.assertRaises(ValueError): self.validate()

    def test_dead_unknown_malformed_or_oversized_stat_rejected(self):
        for text in (self.stat.replace(") S ", ") Z "), self.stat.replace(") S ", ") ? "),
                     "124 (python) S " + "0 " * 19, self.stat[:-3] + "0", "x" * 8193):
            self.setUp()
            self.stat = text
            with self.assertRaises(ValueError): self.validate()

    def test_steam_requires_app_slice(self):
        self.request = replace(self.request, unit="steam-launcher.service")
        with self.assertRaises(ValueError): self.validate()
        self.path = self.path.replace("session.slice/gamescope-session", "app.slice/steam-launcher")
        self.properties["ControlGroup"] = self.path
        self.cgroup = "0::" + self.path
        self.validate()

    def test_pidfd_failure_has_no_pid_only_fallback(self):
        peer = PeerCredentials(123, 1000, 1000)
        with patch("backend.hdm.delivery.device_filter_peer.os.pidfd_open", create=True,
                   side_effect=OSError("unsupported")), patch("backend.hdm.delivery.device_filter_peer.os.open") as opening:
            with self.assertRaises(OSError):
                with hold_waiting_peer(peer, self.request, expected_uid=1000, inspect_unit=Mock()): pass
            opening.assert_not_called()

    def test_held_process_exit_closes_every_descriptor(self):
        peer = PeerCredentials(123, 1000, 1000)
        prefix = "backend.hdm.delivery.device_filter_peer."
        poller = Mock()
        poller.poll.return_value = [(7, 1)]
        with patch(prefix+"os.O_DIRECTORY", create=True, new=0), patch(prefix+"os.O_NOFOLLOW", create=True, new=0), \
             patch(prefix+"select.POLLIN", create=True, new=1), patch(prefix+"os.pidfd_open", create=True, return_value=7), patch(prefix+"os.open", return_value=8), \
             patch(prefix+"_read_at", side_effect=[self.stat, self.status, self.cgroup]), \
             patch(prefix+"_open_cgroup", return_value=9), patch(prefix+"os.fstat", return_value=SimpleNamespace(st_dev=1, st_ino=2)), \
             patch(prefix+"select.poll", create=True, return_value=poller), patch(prefix+"os.close") as close:
            with self.assertRaises(ValueError):
                with hold_waiting_peer(peer, self.request, expected_uid=1000,
                                       inspect_unit=lambda _: self.properties): pass
            self.assertEqual([call.args[0] for call in close.call_args_list], [9, 8, 7])

    @unittest.skipUnless(sys.platform == "linux", "Linux proc observation")
    def test_real_proc_stat_and_credentials_parse(self):
        pid, uid = os.getpid(), os.getuid()
        if uid == 0:
            self.skipTest("requires ordinary fixture user")
        properties = dict(self.properties, MainPID=str(pid))
        path = f"/user.slice/user-{uid}.slice/user@{uid}.service/session.slice/gamescope-session.service"
        properties["ControlGroup"] = path
        starttime, observed = validate_peer_text(pid, uid, self.request, properties,
            Path(f"/proc/{pid}/stat").read_text(), Path(f"/proc/{pid}/status").read_text(), "0::" + path)
        self.assertGreater(starttime, 0)
        self.assertEqual(observed, path)

    def test_cgroup_replacement_and_expired_holder_are_rejected(self):
        from backend.hdm.delivery.device_filter_peer import HeldWaitingPeer, WaitingPeerIdentity
        identity = WaitingPeerIdentity(123, 1000, 456, self.request.invocation,
            self.request.unit, self.path, 1, 2)
        held = HeldWaitingPeer(123, 1000, self.request, lambda _: self.properties, 7, 8, 9, identity)
        prefix = "backend.hdm.delivery.device_filter_peer."
        poller = Mock()
        poller.poll.return_value = []
        with patch(prefix+"select.POLLIN", create=True, new=1), patch(prefix+"select.poll", create=True, return_value=poller), \
             patch(prefix+"_read_at", side_effect=[self.stat, self.status, self.cgroup]), \
             patch(prefix+"_open_cgroup", return_value=10), patch(prefix+"os.close") as close, \
             patch(prefix+"os.fstat", side_effect=[SimpleNamespace(st_dev=1, st_ino=3),
                 SimpleNamespace(st_mode=stat.S_IFDIR, st_dev=1, st_ino=2)]):
            with self.assertRaises(ValueError): held.revalidate()
            close.assert_called_once_with(10)
        held.pid_fd = None
        with self.assertRaises(ValueError): held.revalidate()
