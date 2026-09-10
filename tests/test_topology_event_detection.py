from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.topology_event_detection import (  # noqa: E402
    TopologyDetectionStatus,
    detect_topology_event,
)
from regear.domain.event_policy import TopologyEvent  # noqa: E402
from regear.domain.models import Confidence, DisplayKind, GpuRole  # noqa: E402
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.ports.transition import VersionedObservation  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def snapshot(name: str):
    return snapshot_from_dict(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def observed(generation: str, sample: str, value):
    return VersionedObservation(generation, value, sample)


class TopologyEventDetectionTests(unittest.TestCase):
    def test_exact_attach_requires_verified_absence_then_exact_profile(self):
        result = detect_topology_event(
            observed("portable-a", "sample-a", snapshot("portable.json")),
            observed("docked-b", "sample-b", snapshot("tv-docked.json")),
        )

        self.assertEqual(result.status, TopologyDetectionStatus.DETECTED)
        self.assertEqual(result.event, TopologyEvent.EGPU_ATTACHED)
        self.assertEqual(result.previous_sample_id, "sample-a")

    def test_partial_usb4_phase_can_settle_into_one_exact_attach_candidate(self):
        portable = snapshot("portable.json")
        partial = replace(
            portable,
            gpus=(
                *portable.gpus,
                replace(
                    next(
                        gpu
                        for gpu in snapshot("connected-internal.json").gpus
                        if gpu.role is GpuRole.EXTERNAL
                    ),
                    present=False,
                    confidence=Confidence.UNKNOWN,
                ),
            ),
        )
        result = detect_topology_event(
            observed("partial-a", "sample-a", partial),
            observed(
                "exact-b", "sample-b", snapshot("connected-internal.json")
            ),
        )

        self.assertEqual(result.status, TopologyDetectionStatus.DETECTED)
        self.assertEqual(result.event, TopologyEvent.EGPU_ATTACHED)

    def test_exact_removal_requires_the_same_verified_gpu_become_absent(self):
        before = snapshot("tv-docked.json")
        portable = snapshot("portable.json")
        g1 = next(gpu for gpu in before.gpus if gpu.role is GpuRole.EXTERNAL)
        after = replace(
            portable,
            gpus=portable.gpus + (replace(g1, present=False, selected_for_render=False),),
        )

        result = detect_topology_event(
            observed("docked-a", "sample-a", before),
            observed("portable-b", "sample-b", after),
        )

        self.assertEqual(result.status, TopologyDetectionStatus.DETECTED)
        self.assertEqual(result.event, TopologyEvent.EGPU_REMOVED)

    def test_display_loss_requires_same_g1_and_the_same_external_display(self):
        before = snapshot("tv-docked.json")
        external = next(display for display in before.displays if display.kind is DisplayKind.EXTERNAL)
        after = replace(
            before,
            displays=tuple(
                replace(display, connected=False, active=False)
                if display.stable_id == external.stable_id
                else display
                for display in before.displays
            ),
        )

        result = detect_topology_event(
            observed("docked-a", "sample-a", before),
            observed("display-b", "sample-b", after),
        )

        self.assertEqual(result.status, TopologyDetectionStatus.DETECTED)
        self.assertEqual(result.event, TopologyEvent.EXTERNAL_DISPLAY_LOST)

    def test_missing_or_reused_observation_never_emits_a_candidate(self):
        value = snapshot("tv-docked.json")
        for previous, current in (
            (None, observed("b", "sample-b", value)),
            (observed("a", "sample-a", value), observed("a", "sample-b", value)),
            (observed("a", "sample-a", value), observed("b", "sample-a", value)),
        ):
            with self.subTest(previous=previous, current=current):
                result = detect_topology_event(previous, current)
                self.assertEqual(result.status, TopologyDetectionStatus.UNVERIFIED)
                self.assertIsNone(result.event)

    def test_ambiguous_or_unproven_loss_stays_unverified(self):
        before = snapshot("tv-docked.json")
        portable = snapshot("portable.json")
        unknown_external = replace(
            next(gpu for gpu in before.gpus if gpu.role is GpuRole.EXTERNAL),
            present=False,
            confidence=Confidence.UNKNOWN,
        )
        after = replace(portable, gpus=portable.gpus + (unknown_external,))

        result = detect_topology_event(
            observed("docked-a", "sample-a", before),
            observed("portable-b", "sample-b", after),
        )

        self.assertEqual(result.status, TopologyDetectionStatus.UNVERIFIED)
        self.assertIsNone(result.event)


if __name__ == "__main__":
    unittest.main()
