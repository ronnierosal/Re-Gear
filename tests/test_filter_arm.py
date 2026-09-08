from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.application.filter_arm import (  # noqa: E402
    UNDISTURBED_STAGES,
    ArmSequenceResult,
    ArmStage,
    FilterArmCoordinator,
)
from hdm.domain.filter_authorization import (  # noqa: E402
    CgroupIdentity,
    OwnerIdentity,
    authorize_parent_scope,
)
from hdm.ports.device_filter import (  # noqa: E402
    ArmedFilter,
    ArmOutcome,
    ArmResult,
    DisarmOutcome,
    DisarmResult,
)


UID = 1000
MANAGER = f"/sys/fs/cgroup/user.slice/user-{UID}.slice/user@{UID}.service"
BOOT = "a" * 64
CGROUP = CgroupIdentity(MANAGER, 30, 5561)
FILTER = ArmedFilter(program_id=444, link_id=6, cgroup_id=5561)
PROGRAM = b"\x00" * 312

HOLDERS = (
    "gamescope-session.service",
    "steam-launcher.service",
    "wireplumber.service",
)


def grant(deadline: float = 1000.0):
    return authorize_parent_scope(
        cgroup=CGROUP,
        uid=UID,
        session_uid=UID,
        owner=OwnerIdentity(1844, 99001),
        boot_hash=BOOT,
        attachment_binding="egpu-stable-id",
        generation="generation",
        sample_id="sample",
        deadline=deadline,
    )


class FakeFilter:
    def __init__(self, *, arm_ok=True, enforced=True, disarm_ok=True) -> None:
        self._arm_ok = arm_ok
        self._enforced = enforced
        self._disarm_ok = disarm_ok
        self.armed = False
        self.disarm_calls = 0

    def arm(self, program, cgroup):
        if not self._arm_ok:
            return ArmResult(ArmOutcome.ATTACH_FAILED, code="fake.attach_failed")
        self.armed = True
        return ArmResult(ArmOutcome.ARMED, FILTER)

    def enforced(self, cgroup, program_id):
        return self._enforced

    def disarm(self):
        self.disarm_calls += 1
        if not self._disarm_ok:
            return DisarmResult(DisarmOutcome.FAILED, "fake.disarm_failed")
        self.armed = False
        return DisarmResult(DisarmOutcome.DISARMED)


def coordinator(
    *,
    device_filter=None,
    holders=(HOLDERS, ()),
    restart_fails=None,
    cgroup=CGROUP,
    now=1.0,
):
    """Build a coordinator whose holder scan returns each value in turn."""
    sequence = list(holders)
    restarted: list[str] = []

    def observe():
        return sequence.pop(0) if len(sequence) > 1 else sequence[0]

    def restart(unit):
        if restart_fails and unit == restart_fails:
            return False
        restarted.append(unit)
        return True

    instance = FilterArmCoordinator(
        device_filter=device_filter or FakeFilter(),
        restart=restart,
        observe_holder_units=observe,
        observe_cgroup=lambda: cgroup,
        monotonic=lambda: now,
    )
    instance.restarted = restarted  # type: ignore[attr-defined]
    return instance


class SuccessTests(unittest.TestCase):
    def test_the_measured_sequence_arms_and_clears(self) -> None:
        fake = FakeFilter()
        result = coordinator(device_filter=fake).arm(grant(), PROGRAM, boot_hash=BOOT)
        self.assertIs(result.stage, ArmStage.ARMED_AND_CLEAR)
        self.assertTrue(result.ok)
        self.assertEqual(result.filter, FILTER)
        self.assertFalse(result.disarmed)
        self.assertTrue(fake.armed)

    def test_only_the_planned_units_are_restarted(self) -> None:
        instance = coordinator()
        instance.arm(grant(), PROGRAM, boot_hash=BOOT)
        self.assertEqual(
            instance.restarted, ["wireplumber.service", "gamescope-session.target"]
        )

    def test_success_reports_the_session_as_disturbed(self) -> None:
        result = coordinator().arm(grant(), PROGRAM, boot_hash=BOOT)
        self.assertTrue(result.session_disturbed)


class AuthorizationTests(unittest.TestCase):
    def test_a_refused_grant_never_arms(self) -> None:
        fake = FakeFilter()
        refused = authorize_parent_scope(
            cgroup=CGROUP,
            uid=UID,
            session_uid=1001,
            owner=OwnerIdentity(1844, 99001),
            boot_hash=BOOT,
            attachment_binding="b",
            generation="g",
            sample_id="s",
            deadline=1000.0,
        )
        result = coordinator(device_filter=fake).arm(refused, PROGRAM, boot_hash=BOOT)
        self.assertIs(result.stage, ArmStage.NOT_AUTHORIZED)
        self.assertFalse(fake.armed)

    def test_a_recreated_cgroup_stops_the_sequence(self) -> None:
        fake = FakeFilter()
        recreated = CgroupIdentity(MANAGER, 30, 9999)
        result = coordinator(device_filter=fake, cgroup=recreated).arm(
            grant(), PROGRAM, boot_hash=BOOT
        )
        self.assertIs(result.stage, ArmStage.AUTHORIZATION_STALE)
        self.assertFalse(fake.armed)

    def test_an_expired_grant_stops_the_sequence(self) -> None:
        fake = FakeFilter()
        result = coordinator(device_filter=fake, now=5000.0).arm(
            grant(deadline=1000.0), PROGRAM, boot_hash=BOOT
        )
        self.assertIs(result.stage, ArmStage.AUTHORIZATION_STALE)
        self.assertFalse(fake.armed)

    def test_a_different_boot_stops_the_sequence(self) -> None:
        result = coordinator().arm(grant(), PROGRAM, boot_hash="b" * 64)
        self.assertIs(result.stage, ArmStage.AUTHORIZATION_STALE)


class EnforcementTests(unittest.TestCase):
    """Enforcement is verified before the player's session is disturbed."""

    def test_unverified_enforcement_disarms_without_restarting(self) -> None:
        fake = FakeFilter(enforced=False)
        instance = coordinator(device_filter=fake)
        result = instance.arm(grant(), PROGRAM, boot_hash=BOOT)
        self.assertIs(result.stage, ArmStage.ENFORCEMENT_UNVERIFIED)
        self.assertEqual(instance.restarted, [])
        self.assertFalse(result.session_disturbed)

    def test_unverified_enforcement_takes_the_filter_down(self) -> None:
        fake = FakeFilter(enforced=False)
        result = coordinator(device_filter=fake).arm(grant(), PROGRAM, boot_hash=BOOT)
        self.assertEqual(fake.disarm_calls, 1)
        self.assertTrue(result.disarmed)
        self.assertFalse(fake.armed)

    def test_a_failed_disarm_is_reported_not_hidden(self) -> None:
        fake = FakeFilter(enforced=False, disarm_ok=False)
        result = coordinator(device_filter=fake).arm(grant(), PROGRAM, boot_hash=BOOT)
        self.assertFalse(result.disarmed)


class FailureRecoveryTests(unittest.TestCase):
    def test_arm_failure_leaves_the_session_undisturbed(self) -> None:
        fake = FakeFilter(arm_ok=False)
        instance = coordinator(device_filter=fake)
        result = instance.arm(grant(), PROGRAM, boot_hash=BOOT)
        self.assertIs(result.stage, ArmStage.ARM_FAILED)
        self.assertEqual(instance.restarted, [])
        self.assertIn(result.stage, UNDISTURBED_STAGES)

    def test_a_blocked_plan_disarms_before_restarting(self) -> None:
        fake = FakeFilter()
        instance = coordinator(
            device_filter=fake, holders=(("mystery.service",), ())
        )
        result = instance.arm(grant(), PROGRAM, boot_hash=BOOT)
        self.assertIs(result.stage, ArmStage.PLAN_BLOCKED)
        self.assertEqual(result.code, "arm_sequence.unapproved_holder")
        self.assertEqual(instance.restarted, [])
        self.assertEqual(fake.disarm_calls, 1)

    def test_a_failed_restart_disarms_and_reports_what_ran(self) -> None:
        fake = FakeFilter()
        result = coordinator(
            device_filter=fake, restart_fails="gamescope-session.target"
        ).arm(grant(), PROGRAM, boot_hash=BOOT)
        self.assertIs(result.stage, ArmStage.RESTART_FAILED)
        self.assertEqual(result.restarted, ("wireplumber.service",))
        self.assertTrue(result.session_disturbed)
        self.assertEqual(fake.disarm_calls, 1)

    def test_remaining_holders_disarm_and_are_named(self) -> None:
        """A composed plan is not evidence the device was cleared."""
        fake = FakeFilter()
        result = coordinator(
            device_filter=fake, holders=(HOLDERS, ("wireplumber.service",))
        ).arm(grant(), PROGRAM, boot_hash=BOOT)
        self.assertIs(result.stage, ArmStage.HOLDERS_REMAIN)
        self.assertEqual(result.remaining_holders, ("wireplumber.service",))
        self.assertEqual(fake.disarm_calls, 1)

    def test_no_failure_path_leaves_the_filter_attached(self) -> None:
        for fake, holders, fails in (
            (FakeFilter(enforced=False), (HOLDERS, ()), None),
            (FakeFilter(), (("mystery.service",), ()), None),
            (FakeFilter(), (HOLDERS, ()), "wireplumber.service"),
            (FakeFilter(), (HOLDERS, ("steam-launcher.service",)), None),
        ):
            coordinator(
                device_filter=fake, holders=holders, restart_fails=fails
            ).arm(grant(), PROGRAM, boot_hash=BOOT)
            self.assertFalse(fake.armed, "filter left attached after a failure")


class ResultInvariantTests(unittest.TestCase):
    def test_success_requires_a_filter_identity(self) -> None:
        with self.assertRaises(ValueError):
            ArmSequenceResult(ArmStage.ARMED_AND_CLEAR, "code")

    def test_success_cannot_also_be_disarmed(self) -> None:
        with self.assertRaises(ValueError):
            ArmSequenceResult(
                ArmStage.ARMED_AND_CLEAR, "code", FILTER, (), (), True
            )

    def test_arming_never_removes_a_device(self) -> None:
        """Reaching armed_and_clear is not removal authority."""
        source = (ROOT / "backend/hdm/application/filter_arm.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("device_removal", source)
        self.assertNotIn("rescan", source)


if __name__ == "__main__":
    unittest.main()
