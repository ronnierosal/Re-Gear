from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm import egpu_disconnect  # noqa: E402
from hdm.adapters.steamos.drm_crtc import CardCrtcState, CrtcRecord  # noqa: E402
from hdm.application.live_disconnect import LiveDisconnectStage  # noqa: E402
from hdm.egpu_disconnect import (  # noqa: E402
    NEXT_ACTION,
    await_unit_release,
    disconnect_snapshot_service,
    observe_display,
    present_addresses,
)
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


class AwaitUnitReleaseTests(unittest.TestCase):
    """The step that stands in for spawning a restart."""

    def test_a_unit_that_is_not_holding_passes_without_waiting(self) -> None:
        """There is nothing to wait for, so waiting would only cost the operator."""
        clock = Clock()

        released = await_unit_release(
            UNIT,
            scans(HolderScan(())),
            deadline=90.0,
            now=clock.now,
            sleep=clock.sleep,
        )

        self.assertTrue(released)
        self.assertEqual(clock.slept, [])

    def test_a_unit_that_lets_go_partway_through_is_reported_released(self) -> None:
        clock = Clock()

        released = await_unit_release(
            UNIT,
            scans(HolderScan((UNIT,)), HolderScan((UNIT,)), HolderScan(())),
            deadline=90.0,
            now=clock.now,
            sleep=clock.sleep,
        )

        self.assertTrue(released)
        self.assertEqual(clock.slept, [3.0, 3.0])

    def test_a_unit_that_never_lets_go_fails_at_the_deadline(self) -> None:
        """It reports that the unit got restarted, not that a command was run.

        A command that was issued and did nothing must not read as success.
        """
        clock = Clock()

        released = await_unit_release(
            UNIT,
            scans(HolderScan((UNIT,))),
            deadline=10.0,
            now=clock.now,
            sleep=clock.sleep,
        )

        self.assertFalse(released)
        self.assertLessEqual(clock.value, 10.0)

    def test_the_wait_never_runs_past_the_deadline(self) -> None:
        clock = Clock()

        await_unit_release(
            UNIT,
            scans(HolderScan((UNIT,))),
            deadline=4.0,
            now=clock.now,
            sleep=clock.sleep,
        )

        self.assertEqual(clock.slept, [3.0, 1.0])

    def test_another_unit_still_holding_does_not_block_this_one(self) -> None:
        clock = Clock()

        released = await_unit_release(
            UNIT,
            scans(HolderScan(("steam.service",))),
            deadline=90.0,
            now=clock.now,
            sleep=clock.sleep,
        )

        self.assertTrue(released)


class FakeEntry:
    def __init__(self, exists: bool) -> None:
        self._exists = exists

    def is_dir(self) -> bool:
        return self._exists


class FakePciRoot:
    """A bus that enumerates exactly the given addresses.

    A real directory tree cannot stand in here: PCI addresses contain colons,
    which Windows will not accept as a path component, and this test has to run
    wherever the suite does.
    """

    def __init__(self, present) -> None:
        self._present = set(present)

    def __truediv__(self, name: str) -> FakeEntry:
        return FakeEntry(name in self._present)


class PresentAddressTests(unittest.TestCase):
    def _enumerate(self, *addresses):
        return patch.object(
            egpu_disconnect, "PCI_DEVICE_ROOT", FakePciRoot(addresses)
        )

    def test_both_functions_are_reported_when_the_bus_has_them(self) -> None:
        with self._enumerate(GPU, AUDIO):
            self.assertEqual(present_addresses(GPU, AUDIO), (AUDIO, GPU))

    def test_a_half_detached_device_reports_only_what_remains(self) -> None:
        """This is the reading `reconcile` treats as needing recovery."""
        with self._enumerate(GPU):
            self.assertEqual(present_addresses(GPU, AUDIO), (GPU,))

    def test_a_fully_removed_device_reports_nothing(self) -> None:
        with self._enumerate():
            self.assertEqual(present_addresses(GPU, AUDIO), ())


class FakeProbe:
    def __init__(self, states) -> None:
        self._states = states

    def observe(self, node):
        return self._states[node]


def crtc_state(node, *, committed=True, complete=True):
    records = (CrtcRecord(98, 133 if committed else 0, committed, 3840, 2160),)
    return CardCrtcState(node, "fake", records if complete else (), complete)


class ObserveDisplayTests(unittest.TestCase):
    def _observe(self, *, external, internal, scan):
        probe = FakeProbe(
            {"/dev/dri/card1": external, "/dev/dri/card0": internal}
        )
        with patch.object(egpu_disconnect, "DrmCrtcProbe", lambda: probe), patch.object(
            egpu_disconnect, "scan_holders", lambda *a, **k: scan
        ):
            return observe_display(NODES, nodes_incomplete=False)

    def test_the_reading_carries_both_displays_and_the_holders(self) -> None:
        evidence = self._observe(
            external=crtc_state("/dev/dri/card1"),
            internal=crtc_state("/dev/dri/card0"),
            scan=HolderScan(()),
        )

        self.assertEqual(evidence.external_committed, (98,))
        self.assertTrue(evidence.external_complete)
        self.assertIs(evidence.internal_committed, True)
        self.assertEqual(evidence.client_holders, ())
        self.assertTrue(evidence.client_scan_complete)

    def test_an_incomplete_holder_scan_travels_into_the_evidence(self) -> None:
        """An empty holder list from a scan that could not finish is not clear."""
        evidence = self._observe(
            external=crtc_state("/dev/dri/card1"),
            internal=crtc_state("/dev/dri/card0"),
            scan=HolderScan((), unreadable_processes=2),
        )

        self.assertEqual(evidence.client_holders, ())
        self.assertFalse(evidence.client_scan_complete)

    def test_an_unreadable_internal_panel_is_unknown_rather_than_absent(self) -> None:
        evidence = self._observe(
            external=crtc_state("/dev/dri/card1"),
            internal=crtc_state("/dev/dri/card0", complete=False),
            scan=HolderScan(()),
        )

        self.assertIsNone(evidence.internal_committed)


class HolderProjectionTests(unittest.TestCase):
    def test_scan_completeness_reaches_the_coordinator(self) -> None:
        """Dropping it is what made an empty tuple read as a clear device."""
        scan = HolderScan((), unreadable_descriptors=1)
        with patch.object(egpu_disconnect, "scan_holders", lambda *a, **k: scan):
            observation = egpu_disconnect._holder_observation(NODES, True)

        self.assertEqual(observation.units, ())
        self.assertFalse(observation.complete)
        self.assertFalse(observation.clear)


class SelfExclusionTests(unittest.TestCase):
    def test_the_disconnect_excludes_itself_from_its_own_client_scan(self) -> None:
        """It holds the card open to keep DRM master while releasing the display.

        Without this the scan sees this process holding the device and the
        disconnect reports itself as the thing blocking the disconnect.
        """
        service = disconnect_snapshot_service()
        scanner = service._discovery._egpu_clients

        self.assertIn(os.getpid(), scanner._exclude_pids)
        # Exactly this process, and nothing else.
        self.assertEqual(scanner._exclude_pids, frozenset({os.getpid()}))


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
