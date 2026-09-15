import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.adapters.steamos.sleep_inhibitor import InhibitorLeaseStatus, SleepGuardController
from regear.domain.models import EgpuPresence


class FakeLease:
    """A login1 inhibitor that records what it was asked to do."""

    def __init__(self):
        self.active = False
        self.calls = []

    def acquire(self):
        self.calls.append("acquire")
        self.active = True
        return InhibitorLeaseStatus(True)

    def release(self):
        self.calls.append("release")
        self.active = False
        return InhibitorLeaseStatus(False)

    def status(self):
        return InhibitorLeaseStatus(self.active)


class ResumeProtectionTests(unittest.TestCase):
    """A handoff that failed to restore must not silence the guard for the process lifetime.

    Before this, `reconcile` returned early whenever any handoff owner was set,
    so a failed restore -- owner kept for recovery, lease released for the
    suspend -- left an attached eGPU with no inhibitor until the plugin
    restarted. The 1-second reconcile loop kept calling to no effect.
    """

    def setUp(self):
        self.lease = FakeLease()
        self.controller = SleepGuardController(lease=self.lease)
        self.owner = object()

    def test_the_hazard_without_resume(self):
        # Reproduce the failure shape: handoff owned, lease released, restore
        # never finishes. The ambient reconcile is now inert.
        self.assertTrue(self.controller.prepare_handoff(self.owner))
        self.controller.release_handoff(self.owner)
        self.assertFalse(self.lease.active)
        self.controller.reconcile(EgpuPresence.PRESENT)
        self.assertFalse(self.lease.active, "reconcile is paused by the live handoff -- correct while suspending")

    def test_resume_lets_the_ambient_guard_reacquire_but_only_acquire(self):
        self.controller.prepare_handoff(self.owner)
        self.controller.release_handoff(self.owner)
        self.assertTrue(self.controller.resume_protection(self.owner))
        # Next ambient tick with the eGPU present: protection comes back.
        self.controller.reconcile(EgpuPresence.PRESENT)
        self.assertTrue(self.lease.active)
        # Still owned: recovery can finish it properly. Resuming did not clear
        # ownership, and it did not let a second handoff start.
        self.assertTrue(self.controller.handoff_owned(self.owner))
        self.assertFalse(self.controller.prepare_handoff(object()))
        # And the resumed path may never RELEASE. An absent reading while a
        # failed handoff is outstanding keeps whatever is held.
        self.lease.calls.clear()
        self.controller.reconcile(EgpuPresence.ABSENT)
        self.assertNotIn("release", self.lease.calls)
        self.assertTrue(self.lease.active)

    def test_resume_requires_the_owner(self):
        self.controller.prepare_handoff(self.owner)
        self.assertFalse(self.controller.resume_protection(object()))
        self.assertFalse(self.controller.resume_protection(None))

    def test_finish_clears_the_resumed_state(self):
        self.controller.prepare_handoff(self.owner)
        self.controller.release_handoff(self.owner)
        self.controller.resume_protection(self.owner)
        self.controller.reconcile(EgpuPresence.PRESENT)
        self.assertTrue(self.controller.finish_handoff(self.owner))
        self.assertFalse(self.controller.handoff_owned(self.owner))
        # Back to ordinary reconciliation: ABSENT releases again.
        self.controller.reconcile(EgpuPresence.ABSENT)
        self.assertFalse(self.lease.active)

    def test_a_fresh_handoff_starts_paused_even_after_a_resumed_one(self):
        # Resume, recover properly, then start a second handoff: it must begin
        # paused like any other, not inherit the resumed state.
        self.controller.prepare_handoff(self.owner)
        self.controller.release_handoff(self.owner)
        self.controller.resume_protection(self.owner)
        self.controller.reconcile(EgpuPresence.PRESENT)
        self.assertTrue(self.controller.finish_handoff(self.owner))
        other = object()
        self.assertTrue(self.controller.prepare_handoff(other))
        self.controller.release_handoff(other)
        self.controller.reconcile(EgpuPresence.PRESENT)
        self.assertFalse(self.lease.active, "a live handoff is paused by default")


if __name__ == "__main__":
    unittest.main()
