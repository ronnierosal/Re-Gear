from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.filter_arm import (  # noqa: E402
    UNDISTURBED_STAGES,
    ArmSequenceResult,
    ArmStage,
    FilterArmCoordinator,
    HolderObservation,
    release_outcome,
)
from regear.domain.device_removal import (  # noqa: E402
    RemovalFunction,
    RemovalFunctionKind,
)
from regear.domain.disconnect_sequence import (  # noqa: E402
    ReleaseOutcome,
    decide_disconnect,
)
from regear.domain.filter_authorization import (  # noqa: E402
    CgroupIdentity,
    OwnerIdentity,
    authorize_parent_scope,
)
from regear.ports.device_filter import (  # noqa: E402
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
    complete=True,
    restart_raises=None,
    clock=None,
):
    """Build a coordinator whose holder scan returns each value in turn."""
    sequence = list(holders)
    restarted: list[str] = []

    def observe():
        units = sequence.pop(0) if len(sequence) > 1 else sequence[0]
        return HolderObservation(tuple(units), complete)

    def restart(unit):
        if restart_raises and unit == restart_raises:
            raise OSError('restart exploded')
        if restart_fails and unit == restart_fails:
            return False
        restarted.append(unit)
        return True

    instance = FilterArmCoordinator(
        device_filter=device_filter or FakeFilter(),
        restart=restart,
        observe_holders=observe,
        observe_cgroup=lambda: cgroup,
        monotonic=clock or (lambda: now),
    )
    instance.restarted = restarted  # type: ignore[attr-defined]
    return instance



class ClearDeviceTests(unittest.TestCase):
    """A device nothing holds is the ordinary state before a disconnect."""

    def test_a_finished_scan_that_found_nothing_still_arms(self) -> None:
        """Arming is still worth doing with no holders to restart.

        The filter is what stops a holder reappearing during the window that
        follows, so a clear device is a reason to arm and restart nothing --
        not a reason to refuse.
        """
        instance = coordinator(holders=((), ()))

        result = instance.arm(grant(), PROGRAM, boot_hash=BOOT)

        self.assertIs(result.stage, ArmStage.ARMED_AND_CLEAR)
        self.assertEqual(result.restarted, ())
        self.assertFalse(result.session_disturbed)
        self.assertEqual(instance.restarted, [])

    def test_an_unfinished_scan_that_found_nothing_still_refuses(self) -> None:
        instance = coordinator(holders=((), ()), complete=False)

        result = instance.arm(grant(), PROGRAM, boot_hash=BOOT)

        self.assertIs(result.stage, ArmStage.PLAN_BLOCKED)
        self.assertEqual(result.code, "arm_sequence.no_holders_observed")
        self.assertTrue(result.disarmed)


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
        source = (ROOT / "backend/regear/application/filter_arm.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("device_removal", source)
        self.assertNotIn("rescan", source)


class ReleaseOutcomeProjectionTests(unittest.TestCase):
    """The seam between the release half and the disconnect decision.

    Only a demonstrably clear device may lead to a removal, so the mapping
    names its permissive cases and treats every other stage as refused. A
    stage added later therefore cannot accidentally read as permission.
    """

    def result(self, stage: ArmStage) -> ArmSequenceResult:
        if stage is ArmStage.ARMED_AND_CLEAR:
            return ArmSequenceResult(stage, "code", FILTER)
        return ArmSequenceResult(stage, "code")

    def test_a_clear_device_is_the_only_clear_outcome(self) -> None:
        self.assertIs(
            release_outcome(self.result(ArmStage.ARMED_AND_CLEAR)),
            ReleaseOutcome.CLEAR,
        )

    def test_remaining_holders_keep_their_own_outcome(self) -> None:
        self.assertIs(
            release_outcome(self.result(ArmStage.HOLDERS_REMAIN)),
            ReleaseOutcome.HOLDERS_REMAIN,
        )

    def test_every_other_stage_refuses(self) -> None:
        for stage in ArmStage:
            if stage in (ArmStage.ARMED_AND_CLEAR, ArmStage.HOLDERS_REMAIN):
                continue
            self.assertIs(
                release_outcome(self.result(stage)),
                ReleaseOutcome.REFUSED,
                f"{stage} must not permit a removal",
            )

    def test_no_stage_maps_to_not_attempted(self) -> None:
        # NOT_ATTEMPTED means no release ran at all, which an arm result by
        # definition contradicts. Producing it here would let a caller believe
        # the sequence had not started when it had.
        for stage in ArmStage:
            self.assertIsNot(
                release_outcome(self.result(stage)), ReleaseOutcome.NOT_ATTEMPTED
            )

    def test_a_clear_arm_composes_into_a_removal_decision(self) -> None:
        """The two halves join without an adapter in between."""
        decision = decide_disconnect(
            release_outcome(self.result(ArmStage.ARMED_AND_CLEAR)),
            _ready_removal_safety(),
            (
                RemovalFunction(RemovalFunctionKind.GPU, "0000:08:00.0"),
                RemovalFunction(RemovalFunctionKind.AUDIO, "0000:08:00.1"),
            ),
            released_attachment="binding",
        )
        self.assertTrue(decision.may_remove)

    def test_holders_remaining_stops_the_removal_decision(self) -> None:
        decision = decide_disconnect(
            release_outcome(self.result(ArmStage.HOLDERS_REMAIN)),
            _ready_removal_safety(),
            (
                RemovalFunction(RemovalFunctionKind.GPU, "0000:08:00.0"),
                RemovalFunction(RemovalFunctionKind.AUDIO, "0000:08:00.1"),
            ),
            released_attachment="binding",
        )
        self.assertFalse(decision.may_remove)


def _ready_removal_safety():
    from regear.domain.removal_safety import RemovalSafety, RemovalSafetyState
    from regear.domain.safe_undock_readiness import SafeUndockRevalidation

    return RemovalSafety(
        RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL,
        "removal_safety.ready_for_supervised_removal",
        SafeUndockRevalidation("binding", "generation", "sample"),
    )


class ReviewFindingRegressionTests(unittest.TestCase):
    """One case per defect reproduced by the 2026-09-08 review harness.

    Each of these passed before the repair, which is the point: they are the
    fake reproducer's cases turned into standing coverage.
    """

    def test_an_incomplete_final_scan_is_not_a_clear_device(self) -> None:
        """Finding 1: the fail-open removed in #137, returned at this layer.

        A bare tuple could not say the difference between nothing holding the
        device and a scan that could not finish, so an empty one reported
        armed_and_clear.
        """
        result = coordinator(holders=(HOLDERS, ()), complete=False).arm(
            grant(), PROGRAM, boot_hash=BOOT
        )
        self.assertIs(result.stage, ArmStage.SCAN_INCOMPLETE)
        self.assertIsNot(result.stage, ArmStage.ARMED_AND_CLEAR)
        self.assertTrue(result.disarmed)

    def test_a_raised_restart_still_takes_the_filter_down(self) -> None:
        """Finding 2: an OSError escaped and left the filter armed."""
        fake = FakeFilter()
        result = coordinator(
            device_filter=fake, restart_raises="wireplumber.service"
        ).arm(grant(), PROGRAM, boot_hash=BOOT)
        self.assertIs(result.stage, ArmStage.RESTART_FAILED)
        self.assertTrue(result.disarmed)
        self.assertGreaterEqual(fake.disarm_calls, 1)

    def test_authorization_expiring_mid_restart_stops_the_remaining_ones(
        self,
    ) -> None:
        """Finding 3: an expired grant still allowed the next restart."""
        ticks = iter([1.0, 1.0, 2000.0, 2000.0, 2000.0, 2000.0])
        instance = coordinator(clock=lambda: next(ticks, 2000.0))
        result = instance.arm(grant(), PROGRAM, boot_hash=BOOT)
        self.assertIs(result.stage, ArmStage.AUTHORIZATION_STALE)
        self.assertTrue(result.disarmed)
        # The second unit was never restarted.
        self.assertLess(len(instance.restarted), 2)

    def test_a_clear_scan_still_reaches_armed_and_clear(self) -> None:
        """The repair must not make the honest case unreachable."""
        result = coordinator(holders=(HOLDERS, ()), complete=True).arm(
            grant(), PROGRAM, boot_hash=BOOT
        )
        self.assertIs(result.stage, ArmStage.ARMED_AND_CLEAR)
        self.assertIs(release_outcome(result), ReleaseOutcome.CLEAR)

    def test_an_incomplete_scan_refuses_a_removal(self) -> None:
        result = coordinator(holders=(HOLDERS, ()), complete=False).arm(
            grant(), PROGRAM, boot_hash=BOOT
        )
        self.assertIs(release_outcome(result), ReleaseOutcome.REFUSED)


if __name__ == "__main__":
    unittest.main()
