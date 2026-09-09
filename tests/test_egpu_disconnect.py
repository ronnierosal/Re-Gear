from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm import egpu_disconnect  # noqa: E402
from hdm.application.live_disconnect import LiveDisconnectStage  # noqa: E402
from hdm.domain.filter_arm_sequence import (  # noqa: E402
    SESSION_TARGET,
    units_cleared_by,
)
from hdm.egpu_disconnect import NEXT_ACTION  # noqa: E402
from hdm.egpu_release import HolderScan  # noqa: E402


GPU = "0000:08:00.0"
AUDIO = "0000:08:00.1"
UNIT = "wireplumber.service"
NODES = ("/dev/dri/card1", "/dev/dri/renderD129")


class Clock:
    def __init__(self) -> None:
        self.value = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.value += seconds


def scans(*results):
    """Return a scan callable yielding each result, repeating the last."""
    remaining = list(results)

    def scan():
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return scan


class UnitsClearedByTests(unittest.TestCase):
    """A target is not a holder, and that distinction cost a hardware run."""

    def test_a_session_target_clears_its_member_services_not_its_own_name(
        self,
    ) -> None:
        """Holders are leaf cgroup names; a systemd target has no cgroup.

        Waiting for "gamescope-session.target" to leave the holder set
        therefore succeeded on the first scan, instantly and always, without
        the session having been restarted. The sequence then re-observed and
        refused with the very holders the restart was meant to clear.
        """
        holders = ("gamescope-session.service", "steam-launcher.service",
                   "wireplumber.service")

        cleared = units_cleared_by(SESSION_TARGET, holders)

        self.assertEqual(
            cleared, ("gamescope-session.service", "steam-launcher.service")
        )
        self.assertNotIn(SESSION_TARGET, cleared)

    def test_a_service_clears_itself(self) -> None:
        self.assertEqual(
            units_cleared_by(UNIT, (UNIT, "steam-launcher.service")), (UNIT,)
        )

    def test_a_unit_that_is_not_holding_clears_nothing(self) -> None:
        self.assertEqual(units_cleared_by(UNIT, ("steam-launcher.service",)), ())

    def test_a_session_target_with_no_member_holding_clears_nothing(self) -> None:
        self.assertEqual(units_cleared_by(SESSION_TARGET, (UNIT,)), ())

    def test_only_approved_members_are_waited_on(self) -> None:
        """An unapproved holder is refused upstream, never waited for here."""
        cleared = units_cleared_by(
            SESSION_TARGET, ("gamescope-session.service", "init.scope")
        )
        self.assertEqual(cleared, ("gamescope-session.service",))


class HolderProjectionTests(unittest.TestCase):
    def test_scan_completeness_reaches_the_coordinator(self) -> None:
        """Dropping it is what made an empty tuple read as a clear device."""
        scan = HolderScan((), unreadable_descriptors=1)
        with patch.object(egpu_disconnect, "scan_holders", lambda *a, **k: scan):
            observation = egpu_disconnect._holder_observation(NODES, True)

        self.assertEqual(observation.units, ())
        self.assertFalse(observation.complete)
        self.assertFalse(observation.clear)


class NextActionTests(unittest.TestCase):
    def test_every_outcome_that_leaves_the_device_half_attached_names_the_recovery(
        self,
    ) -> None:
        """A refusal a reader cannot act on sends them nowhere."""
        for stage in (
            LiveDisconnectStage.RECOVERY_FAILED,
            LiveDisconnectStage.REMOVAL_UNRECOVERABLE,
        ):
            with self.subTest(stage=stage):
                advice = " ".join(NEXT_ACTION[stage])
                self.assertIn("--rescan", advice)
                self.assertIn("half attached", advice)

    def test_a_standing_display_points_at_the_flag_that_addresses_it(self) -> None:
        advice = " ".join(NEXT_ACTION[LiveDisconnectStage.NOT_SAFE_AFTER_RELEASE])
        self.assertIn("--release-display", advice)


if __name__ == "__main__":
    unittest.main()
