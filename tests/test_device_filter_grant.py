from dataclasses import replace
import unittest
import os
import sys
import tempfile
from unittest.mock import Mock

from backend.hdm.delivery.device_filter_grant import FilterGrantController, GrantObservation
from backend.hdm.delivery.device_filter_lifecycle import Phase, PairedOwnership, PairedStage, PairedReceiveIdentity
from tests.test_device_filter_attachment import AttachmentTests as _AttachmentTests

_attachment_setup = _AttachmentTests.setUp
_run_attach = _AttachmentTests.run_attach
del _AttachmentTests


class GrantTests(unittest.TestCase):
    run_attach = _run_attach

    def setUp(self):
        _attachment_setup(self)
        self.run_attach()
        self.events.clear()
        self.evidence = GrantObservation(self.observation, True, True, True, True, True)
        def send(binding, revision):
            self.assertEqual(self.record.lifecycle.phase, Phase.GRANTED)
            self.assertEqual(self.events[0], "lock")
            self.assertNotIn("unlock", self.events)
            self.events.append("send")
            return True
        self.sender = Mock(side_effect=send)
        self.grant = FilterGrantController(self.controller.journal, lambda: self.evidence,
            self.sender, kernel_factory=self.controller.kernel_factory,
            pin_factory=self.controller.pin_factory, fstat=self.controller.fstat, clock=lambda: 10)

    def deliver(self):
        return self.grant.deliver("op", self.binding.unit, 9)

    def test_commit_precedes_one_response_without_execution_claim(self):
        result = self.deliver()
        self.assertTrue(result.response_sent)
        self.assertFalse(result.execution_verified)
        self.assertFalse(result.disconnect_clearance)
        self.assertLess(self.events.index("grant"), self.events.index("send"))
        self.sender.assert_called_once_with(self.binding, self.record.revision)
        self.assertEqual(self.events[-1], "unlock")

    def test_paired_preparation_never_enters_grant_kernel_path(self):
        self.record = replace(self.record, paired=PairedOwnership(11,
            PairedStage.RECEIVE_CONFIRMED, PairedReceiveIdentity(12, 13, 14, 15)))
        before = self.record
        self.grant.kernel_factory = Mock(side_effect=AssertionError('unexpected kernel access'))
        self.grant.pin_factory = Mock(side_effect=AssertionError('unexpected pin access'))
        with self.assertRaisesRegex(ValueError, 'paired launch authority'):
            self.deliver()
        self.grant.kernel_factory.assert_not_called()
        self.grant.pin_factory.assert_not_called()
        self.sender.assert_not_called()
        self.assertEqual(self.record, before)

    def test_replay_and_recovery_states_never_send_again(self):
        self.deliver()
        with self.assertRaises(ValueError):
            self.deliver()
        self.record = replace(self.record, lifecycle=self.record.lifecycle.after_crash())
        with self.assertRaises(ValueError):
            self.deliver()
        self.assertEqual(self.sender.call_count, 1)

    def test_missing_descriptor_or_broker_evidence_prevents_grant(self):
        for field in ("inherited_scan_complete", "inherited_descriptors_free",
                      "broker_scan_complete", "broker_descriptors_free", "broker_forwarding_restricted"):
            for value in (False, None, 1):
                with self.subTest(field=field, value=value):
                    self.setUp()
                    self.evidence = replace(self.evidence, **{field: value})
                    with self.assertRaises(ValueError):
                        self.deliver()
                    self.sender.assert_not_called()
                    self.assertEqual(self.record.lifecycle.phase, Phase.CANCELLED)

    def test_empty_broker_snapshot_alone_never_grants(self):
        self.evidence = GrantObservation(self.observation, True, True, True, True)
        with self.assertRaises(ValueError):
            self.deliver()
        self.sender.assert_not_called()

    def test_changed_policy_or_waiting_process_prevents_grant(self):
        for changes in ({"denied_devices": ((226, 129),)}, {"no_game": False},
                        {"waiting_wrapper_verified": False}):
            self.setUp()
            self.evidence = replace(self.evidence, launch=replace(self.observation, **changes))
            with self.assertRaises(ValueError):
                self.deliver()
            self.sender.assert_not_called()

    def test_write_failure_never_sends_and_uncertain_publication_recovers(self):
        for failure, phase in (("grant", Phase.CANCELLED),
                               ("grant_published", Phase.RECOVERY_REQUIRED)):
            self.setUp()
            self.fail = failure
            with self.assertRaises(OSError):
                self.deliver()
            self.sender.assert_not_called()
            self.assertEqual(self.record.lifecycle.phase, phase)

    def test_uncertain_delivery_never_retries_and_retains_recovery(self):
        for result in (False, None, 1, OSError("disconnected")):
            self.setUp()
            self.sender.side_effect = result if isinstance(result, Exception) else None
            self.sender.return_value = result
            with self.assertRaises(OSError):
                self.deliver()
            self.assertEqual(self.sender.call_count, 1)
            self.assertEqual(self.record.lifecycle.phase, Phase.RECOVERY_REQUIRED)
            with self.assertRaises(ValueError):
                self.deliver()
            self.assertEqual(self.sender.call_count, 1)

    def test_deadline_after_commit_prevents_response(self):
        self.grant.clock = Mock(side_effect=[10, 10, 30])
        with self.assertRaises(ValueError):
            self.deliver()
        self.sender.assert_not_called()
        self.assertEqual(self.record.lifecycle.phase, Phase.RECOVERY_REQUIRED)

    def test_missing_or_wrong_pin_never_sends(self):
        self.fail = "readback"
        with self.assertRaises(OSError):
            self.deliver()
        self.sender.assert_not_called()
        self.assertEqual(self.record.lifecycle.phase, Phase.CANCELLED)

    @unittest.skipUnless(sys.platform == "linux", "requires real journal dirfd semantics")
    def test_real_journal_never_redelivers_success_or_uncertainty(self):
        from backend.hdm.delivery.device_filter_journal import FilterJournal
        for sent in (True, False):
            self.setUp()
            with tempfile.TemporaryDirectory() as root:
                fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    info = os.fstat(fd)
                    self.binding = replace(self.binding, cgroup_dev=info.st_dev, cgroup_inode=info.st_ino)
                    self.evidence = replace(self.evidence, launch=replace(self.observation, binding=self.binding))
                    journal = FilterJournal(owner_uid=os.geteuid(), trusted_directory_fd=fd)
                    journal.create(self.binding)
                    owner = self.record.lifecycle.owned
                    journal.prepare_pin("op", self.binding.unit, 1,
                        owned=replace(owner, survives_owner_exit=False), observed=self.binding, now=10)
                    journal.attach("op", self.binding.unit, 2, owned=owner, observed=self.binding, now=10)
                    self.grant.journal = journal
                    self.grant.fstat = os.fstat
                    self.sender.side_effect = None
                    self.sender.return_value = sent
                    if sent:
                        self.grant.deliver("op", self.binding.unit, fd)
                    else:
                        with self.assertRaises(OSError):
                            self.grant.deliver("op", self.binding.unit, fd)
                    loaded = journal.read("op", self.binding.unit)
                    self.assertEqual(loaded.lifecycle.phase, Phase.GRANTED if sent else Phase.RECOVERY_REQUIRED)
                    self.assertFalse(loaded.delivery_granted)
                    with self.assertRaises(ValueError):
                        self.grant.deliver("op", self.binding.unit, fd)
                    self.assertEqual(self.sender.call_count, 1)
                finally:
                    os.close(fd)
