from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from backend.hdm.delivery import device_filter_server as server
from backend.hdm.delivery.device_filter_arm import FilterArm
from backend.hdm.delivery.device_filter_protocol import FilterRequest
from backend.hdm.delivery.device_filter_transport import PeerCredentials


class FilterLaunchServerTests(unittest.TestCase):
    def setUp(self):
        self.arm = FilterArm(1, "operation", "gamescope-session.service", 1000,
            "a" * 64, "b" * 64, "c" * 64, "d" * 32, 15)
        self.request = FilterRequest(1, "operation", self.arm.unit, "e" * 32, "f" * 64)
        self.peer = PeerCredentials(50, 1000, 1000)
        self.runtime = SimpleNamespace(digest="1" * 64)
        self.identity = SimpleNamespace(invocation="e" * 32, uid=1000, pid=50,
                                        starttime=60, cgroup_dev=70, cgroup_inode=80)
        self.held = MagicMock()
        self.held.cgroup_fd = 9
        self.held.revalidate.return_value = self.identity
        self.held.__enter__.return_value = self.held
        self.hold = Mock(return_value=self.held)
        self.runtime_observer = Mock(return_value=SimpleNamespace(
            runtime_digest=self.runtime.digest, identity=self.identity))
        self.evidence = server.FilterLaunchEvidence("a" * 64, "b" * 64, "c" * 64,
            self.runtime.digest, ((226, 128),), True, True, True, True, True, True, True)
        self.observe = Mock(side_effect=lambda held: self.evidence)
        self.arms = Mock()
        self.arms.read.return_value = self.arm
        self.events = []
        self.binding = None
        self.journal = Mock()
        def create(binding):
            self.events.append("create")
            self.binding = binding
        self.journal.create.side_effect = create
        self.attachment_failure = False
        self.grant_failure = False

        def attachment_factory(journal, observation, **kwargs):
            def attach(operation, unit, fd):
                self.events.append("attach")
                self.assertEqual((operation, unit, fd), ("operation", self.arm.unit, 9))
                observation()
                if self.attachment_failure:
                    raise ValueError("attachment refused")
            return SimpleNamespace(attach=attach)

        def grant_factory(journal, observation, deliver, **kwargs):
            def grant(operation, unit, fd):
                self.events.append("grant")
                observation()
                if self.grant_failure:
                    raise ValueError("grant refused")
                deliver(self.binding, 5)
                return "delivery evidence"
            return SimpleNamespace(deliver=grant)

        self.handler = server.FilterLaunchServer(self.journal, SimpleNamespace(uid=1000),
            self.observe, arms=self.arms, clock=lambda: 10, observer_factory=Mock(),
            hold_peer=self.hold, observe_runtime=self.runtime_observer,
            attachment_factory=attachment_factory, grant_factory=grant_factory)
        self.connection = MagicMock()
        self.receive_patch = patch.object(server, "receive_request", return_value=(self.peer, self.request))
        self.receive = self.receive_patch.start()
        self.addCleanup(self.receive_patch.stop)
        self.send_patch = patch.object(server, "send_grant", side_effect=lambda *args, **kw: self.events.append("send"))
        self.send = self.send_patch.start()
        self.addCleanup(self.send_patch.stop)

    def handle(self):
        return self.handler.handle(self.connection, expected_arm=self.arm, runtime=self.runtime, deadline=14)

    def test_exact_binding_and_attachment_before_grant(self):
        self.assertEqual(self.handle(), "delivery evidence")
        self.assertEqual(self.events, ["create", "attach", "grant", "send"])
        for name in ("invocation", "uid", "pid", "starttime", "cgroup_dev", "cgroup_inode"):
            self.assertEqual(getattr(self.binding, name), getattr(self.identity, name))
        self.assertEqual(self.binding.deadline, 14)
        self.assertEqual(self.binding.boot_hash, self.arm.boot_hash)
        self.send.assert_called_once()
        self.connection.__exit__.assert_called_once()
        self.assertGreaterEqual(len(self.arms.method_calls), 3)
        self.assertTrue(all(call[0] == "read" for call in self.arms.method_calls))

    def test_unknown_isolation_prevents_any_journal_or_attachment(self):
        for field in ("no_game", "effective_launch_verified", "inherited_scan_complete",
                      "inherited_descriptors_free", "broker_scan_complete", "broker_descriptors_free", "broker_forwarding_restricted"):
            baseline = self.evidence
            for value in (None, False, 1):
                self.evidence = replace(baseline, **{field: value})
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.handle()
            self.evidence = baseline
        self.journal.create.assert_not_called()
        self.assertEqual(self.events, [])
        self.send.assert_not_called()

    def test_changed_arm_and_wrong_operation_fail_before_create(self):
        self.arms.read.return_value = replace(self.arm, operation="changed")
        with self.assertRaises(ValueError):
            self.handle()
        self.arms.read.return_value = self.arm
        self.receive.return_value = self.peer, replace(self.request, operation="foreign")
        with self.assertRaises(ValueError):
            self.handle()
        self.journal.create.assert_not_called()
        self.assertEqual(self.events, [])

    def test_exclusive_create_failure_never_attaches(self):
        self.journal.create.side_effect = FileExistsError("already consumed")
        with self.assertRaises(FileExistsError):
            self.handle()
        self.assertEqual(self.events, [])
        self.send.assert_not_called()
        self.journal.create.assert_called_once()

    def test_postcreate_failure_never_retries_sends_or_clears_arm(self):
        for failure, expected in (("attachment_failure", ["create", "attach"]),
                                  ("grant_failure", ["create", "attach", "grant"])):
            self.events.clear()
            setattr(self, failure, True)
            with self.assertRaises(ValueError):
                self.handle()
            setattr(self, failure, False)
            self.assertEqual(self.events, expected)
        self.send.assert_not_called()
        self.assertTrue(all(call[0] == "read" for call in self.arms.method_calls))

    def test_evidence_changes_after_create_reject(self):
        self.observe.side_effect = [self.evidence, replace(self.evidence, broker_scan_complete=False)]
        with self.assertRaises(ValueError):
            self.handle()
        self.assertEqual(self.events, ["create", "attach"])
        self.send.assert_not_called()

    def test_expired_observation_never_creates_request(self):
        self.handler.clock = lambda: 14
        with self.assertRaises(ValueError):
            self.handle()
        self.journal.create.assert_not_called()
        self.send.assert_not_called()

    def test_policy_change_between_initial_and_attachment_rejected(self):
        self.observe.side_effect = [self.evidence, replace(self.evidence, denied_devices=((226, 129),))]
        with self.assertRaises(ValueError):
            self.handle()
        self.assertEqual(self.events, ["create", "attach"])
        self.send.assert_not_called()

    def test_runtime_identity_or_arm_hash_change_rejects(self):
        for field, value in (("runtime_digest", "2" * 64), ("boot_hash", "3" * 64),
                             ("config_hash", "4" * 64), ("topology_hash", "5" * 64)):
            baseline = self.evidence
            self.evidence = replace(baseline, **{field: value})
            with self.assertRaises(ValueError):
                self.handle()
            self.evidence = baseline
        self.journal.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
