from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.filter_arm_sequence import (  # noqa: E402
    KNOWN_HOLDER_UNITS,
    SESSION_TARGET,
    UNREACHED_BY_SESSION_RESTART,
    ArmRestartSequence,
    ArmSequenceState,
    compose_restart_sequence,
    units_missed_by_session_restart,
)


#: Units of the holders measured on the tested profile, portable placement.
MEASURED_HOLDERS = (
    "gamescope-session.service",
    "steam-launcher.service",
    "wireplumber.service",
)


class MeasuredHardwareTests(unittest.TestCase):
    """Pins the difference between the failed and successful measured runs."""

    def test_session_restart_alone_misses_the_audio_unit(self) -> None:
        """The measured 3-holders-to-1 failure: wireplumber never reopened."""
        self.assertEqual(
            units_missed_by_session_restart(MEASURED_HOLDERS),
            ("wireplumber.service",),
        )

    def test_both_audio_units_are_flagged_when_both_hold(self) -> None:
        holders = (*MEASURED_HOLDERS, "pipewire.service")
        self.assertEqual(
            units_missed_by_session_restart(holders),
            ("pipewire.service", "wireplumber.service"),
        )

    def test_nothing_is_missed_when_only_session_units_hold(self) -> None:
        holders = ("gamescope-session.service", "steam-launcher.service")
        self.assertEqual(units_missed_by_session_restart(holders), ())

    def test_measured_holders_compose_the_successful_sequence(self) -> None:
        sequence = compose_restart_sequence(MEASURED_HOLDERS)
        self.assertIs(sequence.state, ArmSequenceState.COMPOSED)
        self.assertIn("wireplumber.service", sequence.units)
        self.assertIn("gamescope-session.service", sequence.units)

    def test_known_holder_units_cover_what_was_measured(self) -> None:
        self.assertTrue(set(MEASURED_HOLDERS).issubset(KNOWN_HOLDER_UNITS))

    def test_audio_units_are_recorded_as_unreached(self) -> None:
        self.assertIn("wireplumber.service", UNREACHED_BY_SESSION_RESTART)
        self.assertIn("pipewire.service", UNREACHED_BY_SESSION_RESTART)


class CompositionTests(unittest.TestCase):
    def test_session_target_is_restarted_last(self) -> None:
        sequence = compose_restart_sequence(MEASURED_HOLDERS)
        self.assertEqual(sequence.units[-1], SESSION_TARGET)

    def test_services_are_ordered_deterministically(self) -> None:
        forward = compose_restart_sequence(MEASURED_HOLDERS).units
        reversed_input = compose_restart_sequence(
            tuple(reversed(MEASURED_HOLDERS))
        ).units
        self.assertEqual(forward, reversed_input)

    def test_duplicate_units_collapse(self) -> None:
        holders = (*MEASURED_HOLDERS, "wireplumber.service")
        units = compose_restart_sequence(holders).units
        self.assertEqual(len(units), len(set(units)))

    def test_session_target_is_not_duplicated_when_given_as_a_holder(self) -> None:
        holders = (*MEASURED_HOLDERS, SESSION_TARGET)
        units = compose_restart_sequence(holders).units
        self.assertEqual(units.count(SESSION_TARGET), 1)
        self.assertEqual(units[-1], SESSION_TARGET)

    def test_an_unanticipated_unit_is_still_included(self) -> None:
        """Composition works from observation, not from the known-units list."""
        holders = (*MEASURED_HOLDERS, "some-future-holder.service")
        self.assertIn(
            "some-future-holder.service", compose_restart_sequence(holders).units
        )

    def test_no_holders_is_incomplete_not_an_empty_success(self) -> None:
        sequence = compose_restart_sequence(())
        self.assertIs(sequence.state, ArmSequenceState.EVIDENCE_INCOMPLETE)
        self.assertEqual(sequence.code, "arm_sequence.no_holders_observed")
        self.assertEqual(sequence.units, ())

    def test_non_tuple_input_is_invalid(self) -> None:
        sequence = compose_restart_sequence(list(MEASURED_HOLDERS))
        self.assertIs(sequence.state, ArmSequenceState.INVALID)

    def test_empty_unit_name_is_invalid(self) -> None:
        sequence = compose_restart_sequence((*MEASURED_HOLDERS, ""))
        self.assertIs(sequence.state, ArmSequenceState.INVALID)

    def test_non_string_unit_is_invalid(self) -> None:
        sequence = compose_restart_sequence((*MEASURED_HOLDERS, 7))
        self.assertIs(sequence.state, ArmSequenceState.INVALID)


class SequenceInvariantTests(unittest.TestCase):
    def test_unusable_sequence_cannot_carry_units(self) -> None:
        with self.assertRaises(ValueError):
            ArmRestartSequence(
                ArmSequenceState.EVIDENCE_INCOMPLETE, "code", ("a.service",)
            )

    def test_composed_sequence_requires_units(self) -> None:
        with self.assertRaises(ValueError):
            ArmRestartSequence(ArmSequenceState.COMPOSED, "code", ())


if __name__ == "__main__":
    unittest.main()
