from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.filter_arm_sequence import (  # noqa: E402
    APPROVED_EXPLICIT_RESTARTS,
    APPROVED_HOLDER_UNITS,
    APPROVED_SESSION_REACHED,
    SESSION_TARGET,
    ArmRestartPlan,
    ArmSequenceState,
    classify_holder_units,
)
from hdm.domain.filter_arm_sequence import (  # noqa: E402
    compose_restart_plan as _compose_restart_plan,
)


def compose_restart_plan(holder_units, *, scan_complete=True):
    """Compose over a scan that finished, which is what these tests are about.

    Completeness is a required argument on the real function, deliberately: an
    empty result from a scan that could not look needs the opposite answer from
    an empty result from one that did. The tests for that distinction call the
    real function directly, in `EmptyScanTests`.
    """
    return _compose_restart_plan(holder_units, scan_complete=scan_complete)


#: Units of the holders measured on the tested profile, portable placement.
MEASURED_HOLDERS = (
    "gamescope-session.service",
    "steam-launcher.service",
    "wireplumber.service",
)


class ApprovalTests(unittest.TestCase):
    """Observation identifies a holder; it does not authorise restarting it."""

    def test_unapproved_holder_blocks_the_plan(self) -> None:
        plan = compose_restart_plan((*MEASURED_HOLDERS, "unknown-daemon.service"))
        self.assertIs(plan.state, ArmSequenceState.BLOCKED_UNAPPROVED_HOLDER)
        self.assertEqual(plan.code, "arm_sequence.unapproved_holder")
        self.assertEqual(plan.unapproved, ("unknown-daemon.service",))

    def test_blocked_plan_exposes_no_units(self) -> None:
        plan = compose_restart_plan(("unknown-daemon.service",))
        self.assertEqual(plan.units, ())
        self.assertFalse(plan.usable)

    def test_every_unapproved_holder_is_named(self) -> None:
        plan = compose_restart_plan(("b-daemon.service", "a-daemon.service"))
        self.assertEqual(plan.unapproved, ("a-daemon.service", "b-daemon.service"))

    def test_a_system_service_is_not_silently_restarted(self) -> None:
        """systemd-logind held drm_card when docked; it must never be restarted."""
        plan = compose_restart_plan((*MEASURED_HOLDERS, "systemd-logind.service"))
        self.assertIs(plan.state, ArmSequenceState.BLOCKED_UNAPPROVED_HOLDER)
        self.assertIn("systemd-logind.service", plan.unapproved)

    def test_mangoapp_is_approved_on_restart_evidence(self) -> None:
        """Observed holding drm_render when docked. Verified reached: it
        recorded the same ActiveEnterTimestamp as the target restart."""
        self.assertIn("gamescope-mangoapp.service", APPROVED_SESSION_REACHED)
        units = compose_restart_plan(
            (*MEASURED_HOLDERS, "gamescope-mangoapp.service")
        ).units
        self.assertNotIn("gamescope-mangoapp.service", units)

    def test_a_target_unit_without_restart_evidence_is_not_approved(self) -> None:
        """galileo-mura-setup is wanted by the target but was never observed
        restarting, so no evidence exists and it must block."""
        self.assertNotIn("galileo-mura-setup.service", APPROVED_HOLDER_UNITS)
        plan = compose_restart_plan((*MEASURED_HOLDERS, "galileo-mura-setup.service"))
        self.assertIs(plan.state, ArmSequenceState.BLOCKED_UNAPPROVED_HOLDER)


class MeasuredHardwareTests(unittest.TestCase):
    """Reproduces the sequence that actually released every holder."""

    def test_measured_holders_compose_the_measured_sequence(self) -> None:
        plan = compose_restart_plan(MEASURED_HOLDERS)
        self.assertIs(plan.state, ArmSequenceState.COMPOSED)
        self.assertEqual(plan.units, ("wireplumber.service", SESSION_TARGET))

    def test_session_reached_units_are_not_restarted_individually(self) -> None:
        """Restarting Steam and the compositor separately was not what worked,
        and would disrupt the session more than the measured sequence."""
        units = compose_restart_plan(MEASURED_HOLDERS).units
        self.assertNotIn("steam-launcher.service", units)
        self.assertNotIn("gamescope-session.service", units)

    def test_session_target_is_last(self) -> None:
        plan = compose_restart_plan((*MEASURED_HOLDERS, "pipewire.service"))
        self.assertEqual(plan.units[-1], SESSION_TARGET)

    def test_explicit_restarts_keep_the_recorded_order(self) -> None:
        """Order is the one measured, not alphabetical: nothing here
        establishes a dependency ordering."""
        plan = compose_restart_plan(("pipewire.service", "wireplumber.service"))
        # No session unit is holding, so the session target is not in the plan.
        self.assertEqual(plan.units, ("wireplumber.service", "pipewire.service"))

    def test_audio_units_are_the_ones_the_target_misses(self) -> None:
        self.assertEqual(
            APPROVED_EXPLICIT_RESTARTS, ("wireplumber.service", "pipewire.service")
        )
        for unit in APPROVED_EXPLICIT_RESTARTS:
            self.assertNotIn(unit, APPROVED_SESSION_REACHED)


class CoverageTests(unittest.TestCase):
    def test_unapproved_units_are_never_reported_as_reached(self) -> None:
        coverage = classify_holder_units((*MEASURED_HOLDERS, "mystery.service"))
        self.assertNotIn("mystery.service", coverage.reached)
        self.assertNotIn("mystery.service", coverage.requires_explicit_restart)
        self.assertEqual(coverage.unapproved, ("mystery.service",))
        self.assertFalse(coverage.complete)

    def test_measured_holders_are_fully_covered(self) -> None:
        coverage = classify_holder_units(MEASURED_HOLDERS)
        self.assertTrue(coverage.complete)
        self.assertEqual(coverage.requires_explicit_restart, ("wireplumber.service",))
        self.assertEqual(
            coverage.reached,
            ("gamescope-session.service", "steam-launcher.service"),
        )

    def test_session_only_restart_would_miss_the_audio_unit(self) -> None:
        """The measured 3-holders-to-1 failure, expressed as coverage."""
        coverage = classify_holder_units(MEASURED_HOLDERS)
        self.assertIn("wireplumber.service", coverage.requires_explicit_restart)


class EmptyScanTests(unittest.TestCase):
    """An empty result means opposite things depending on the scan."""

    def test_a_scan_that_could_not_finish_is_not_a_clear_device(self) -> None:
        plan = _compose_restart_plan((), scan_complete=False)

        self.assertIs(plan.state, ArmSequenceState.EVIDENCE_INCOMPLETE)
        self.assertEqual(plan.code, "arm_sequence.no_holders_observed")
        self.assertFalse(plan.usable)

    def test_a_finished_scan_that_found_nothing_has_nothing_to_restart(self) -> None:
        """The ordinary state of an idle eGPU before a disconnect.

        This used to be indistinguishable from the case above, because the
        completeness the caller already had was dropped at this boundary, and
        a device nothing holds could not be armed at all.
        """
        plan = _compose_restart_plan((), scan_complete=True)

        self.assertIs(plan.state, ArmSequenceState.NOTHING_TO_RESTART)
        self.assertEqual(plan.code, "arm_sequence.device_already_clear")
        self.assertTrue(plan.usable)
        self.assertEqual(plan.units, ())

    def test_nothing_to_restart_cannot_name_units(self) -> None:
        with self.assertRaises(ValueError):
            ArmRestartPlan(
                ArmSequenceState.NOTHING_TO_RESTART, "code", ("wireplumber.service",)
            )

    def test_a_completeness_that_is_not_a_boolean_is_invalid(self) -> None:
        self.assertIs(
            _compose_restart_plan(MEASURED_HOLDERS, scan_complete="yes").state,
            ArmSequenceState.INVALID,
        )


class SessionTargetTests(unittest.TestCase):
    """The session target restarts the player's whole session.

    It is by far the most disruptive step a plan can take, so it has to earn
    its place. Restarting a session that is holding nothing cannot release
    anything.
    """

    def test_a_session_unit_holding_earns_the_session_target(self) -> None:
        plan = compose_restart_plan(MEASURED_HOLDERS)

        self.assertIn(SESSION_TARGET, plan.units)
        self.assertEqual(plan.units[-1], SESSION_TARGET)

    def test_audio_alone_does_not_restart_the_player_session(self) -> None:
        """The state measured on the tested Ally X.

        The player had already returned to the handheld, so gamescope and
        Steam were holding nothing and only the audio daemon remained. The
        session was restarted anyway, for nothing.
        """
        plan = compose_restart_plan(("wireplumber.service",))

        self.assertEqual(plan.units, ("wireplumber.service",))
        self.assertNotIn(SESSION_TARGET, plan.units)
        self.assertTrue(plan.usable)

    def test_a_session_unit_alone_restarts_only_the_target(self) -> None:
        plan = compose_restart_plan(("gamescope-session.service",))

        self.assertEqual(plan.units, (SESSION_TARGET,))

    def test_every_reached_unit_counts_not_just_the_compositor(self) -> None:
        plan = compose_restart_plan(("steam-launcher.service",))

        self.assertEqual(plan.units, (SESSION_TARGET,))


class PlanValidationTests(unittest.TestCase):

    def test_non_tuple_input_is_invalid(self) -> None:
        self.assertIs(
            compose_restart_plan(list(MEASURED_HOLDERS)).state,
            ArmSequenceState.INVALID,
        )

    def test_empty_unit_name_is_invalid(self) -> None:
        self.assertIs(
            compose_restart_plan((*MEASURED_HOLDERS, "")).state,
            ArmSequenceState.INVALID,
        )

    def test_non_string_unit_is_invalid(self) -> None:
        self.assertIs(
            compose_restart_plan((*MEASURED_HOLDERS, 7)).state,
            ArmSequenceState.INVALID,
        )

    def test_duplicate_holders_do_not_duplicate_restarts(self) -> None:
        plan = compose_restart_plan((*MEASURED_HOLDERS, "wireplumber.service"))
        self.assertEqual(plan.units.count("wireplumber.service"), 1)

    def test_composed_plan_cannot_carry_unapproved_units(self) -> None:
        with self.assertRaises(ValueError):
            ArmRestartPlan(
                ArmSequenceState.COMPOSED, "code", (SESSION_TARGET,), ("x.service",)
            )

    def test_blocked_plan_must_name_its_holders(self) -> None:
        with self.assertRaises(ValueError):
            ArmRestartPlan(ArmSequenceState.BLOCKED_UNAPPROVED_HOLDER, "code")

    def test_unusable_plan_cannot_carry_units(self) -> None:
        with self.assertRaises(ValueError):
            ArmRestartPlan(
                ArmSequenceState.EVIDENCE_INCOMPLETE, "code", (SESSION_TARGET,)
            )


if __name__ == "__main__":
    unittest.main()
