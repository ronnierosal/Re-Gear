"""Event/poll equivalence and bounded automatic session recovery scheduling."""
import sys
import unittest
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.application.automatic_link_recovery import AutomaticLinkRecovery
from regear.delivery.automatic_dock_preferences import AutomaticDockPreferenceStore


class AutomaticRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.policy = AutomaticLinkRecovery()

    def sample(self, now, **changes):
        facts = dict(now=now, absent=False, present=True, identity="transport:known",
                     pci_complete=False, enabled=True, idle=True)
        facts.update(changes)
        return self.policy.observe(**facts)

    def arm(self):
        self.sample(0, absent=True, present=False, identity="")
        self.assertFalse(self.sample(1))

    def test_no_restart_from_startup_with_a_dock_already_present(self):
        for now in [0, 10, 1000]:
            self.assertFalse(self.sample(now))

    def test_ten_seconds_then_cooldown_after_completion_and_two_attempt_cap(self):
        self.arm()
        self.assertFalse(self.sample(10.9))
        self.assertTrue(self.sample(11))
        self.policy.begin()
        self.assertFalse(self.sample(100))
        self.policy.finish(100)
        self.assertFalse(self.sample(101))
        self.assertFalse(self.sample(110))
        self.assertTrue(self.sample(111))
        self.policy.begin(); self.policy.finish(120)
        self.assertFalse(self.sample(121))
        self.assertFalse(self.sample(10000))
        self.assertEqual(self.policy.attempts, 2)

    def test_gpu_arrival_stops_retry_even_if_later_observation_loses_gpu(self):
        self.arm(); self.sample(5, pci_complete=True)
        self.assertFalse(self.sample(100))

    def test_game_or_unknown_idle_evidence_restarts_settling(self):
        self.arm(); self.sample(10, idle=False)
        self.assertFalse(self.sample(11))
        self.assertFalse(self.sample(20.9))
        self.assertTrue(self.sample(21))

    def test_disabled_or_unresolved_transport_never_dispatches(self):
        for changes in [dict(enabled=False), dict(identity="transport:unresolved"), dict(present=False)]:
            self.setUp(); self.arm()
            self.assertFalse(self.sample(100, **changes))

    def test_unknown_absence_and_identity_change_do_not_rearm(self):
        self.arm(); self.policy.begin(); self.policy.finish(20)
        self.sample(21, present=False)
        self.assertEqual(self.policy.attempts, 1)
        self.assertFalse(self.sample(100, identity="transport:changed"))
        self.assertFalse(self.sample(200))
        self.sample(201, present=False, absent=True, identity="")
        self.assertFalse(self.sample(202))
        self.assertTrue(self.sample(212))

    def test_recovery_consent_is_separate_default_off_and_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            dock = AutomaticDockPreferenceStore(Path(tmp))
            recovery = AutomaticDockPreferenceStore(Path(tmp), recovery=True)
            dock.save(True)
            self.assertFalse(recovery.load())
            recovery.save(True)
            self.assertTrue(AutomaticDockPreferenceStore(Path(tmp), recovery=True).load())
            recovery.save(False)
            self.assertTrue(dock.load())


if __name__ == "__main__": unittest.main()
