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

    def test_a_live_handoff_still_pauses_the_ambient_reconcile(self):
        # Existing behaviour, pinned so the resume path cannot loosen it: while
        # a handoff is live its release for the suspend is not undone a
        # second later by the loop.
        self.assertTrue(self.controller.prepare_handoff(self.owner))
        self.controller.release_handoff(self.owner)
        self.assertFalse(self.lease.active)
        self.controller.reconcile(EgpuPresence.PRESENT)
        self.assertFalse(self.lease.active, "reconcile is paused by the live handoff -- correct while suspending")

    def test_resume_returns_the_guard_to_presence_policy(self):
        self.controller.prepare_handoff(self.owner)
        self.controller.release_handoff(self.owner)
        self.assertTrue(self.controller.resume_protection(self.owner))
        # Next ambient tick with the eGPU present: protection comes back.
        self.controller.reconcile(EgpuPresence.PRESENT)
        self.assertTrue(self.lease.active)
        # Still owned: resuming did not clear the claim, and a second handoff
        # cannot start on top of the unresolved one.
        self.assertTrue(self.controller.handoff_owned(self.owner))
        self.assertFalse(self.controller.prepare_handoff(object()))
        # Unplugged: the guard lets go again. An acquire-only resume would hold
        # a block inhibitor for the rest of the process -- a dead sleep button,
        # not protection.
        self.controller.reconcile(EgpuPresence.ABSENT)
        self.assertFalse(self.lease.active)
        # And back, when the eGPU is.
        self.controller.reconcile(EgpuPresence.PRESENT)
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
