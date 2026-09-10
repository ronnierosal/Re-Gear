from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.sleep_workflow import (  # noqa: E402
    SnapshotSleepWorkflowObservationAdapter,
)
from regear.domain.control_plane import PlacementState, RemovalBehavior  # noqa: E402
from regear.domain.models import Blocker, Confidence, EgpuPresence  # noqa: E402
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.ports.transition import VersionedObservation  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def snapshot(name):
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return snapshot_from_dict(value)


class Observations:
    def __init__(self, value):
        self.value = value

    def observe(self):
        return VersionedObservation("semantic-1", self.value, "sample-1")


class SnapshotSleepWorkflowObservationAdapterTests(unittest.TestCase):
    def test_portable_snapshot_proves_absence_but_not_removal_readiness(self):
        result = SnapshotSleepWorkflowObservationAdapter(
            Observations(snapshot("portable.json"))
        ).observe()
        self.assertEqual(result.context.egpu_presence, EgpuPresence.ABSENT)
        self.assertTrue(result.context.exact_egpu_identity_verified)
        self.assertEqual(result.context.placement, PlacementState.PORTABLE)
        self.assertFalse(result.context.removal_readiness_verified)

    def test_exact_certified_g1_uses_profile_without_claiming_live_removal(self):
        result = SnapshotSleepWorkflowObservationAdapter(
            Observations(snapshot("connected-internal.json"))
        ).observe()
        self.assertEqual(result.context.egpu_presence, EgpuPresence.PRESENT)
        self.assertTrue(result.context.exact_egpu_identity_verified)
        self.assertEqual(
            result.context.capabilities.removal_behavior,
            RemovalBehavior.SHUTDOWN_BEFORE_DISCONNECT,
        )
        self.assertFalse(result.context.removal_readiness_verified)

    def test_ambiguous_external_gpu_fails_closed_as_unknown(self):
        value = snapshot("connected-internal.json")
        ambiguous = dataclasses.replace(
            value,
            gpus=(
                value.gpus[0],
                dataclasses.replace(value.gpus[1], confidence=Confidence.UNKNOWN),
            ),
        )
        result = SnapshotSleepWorkflowObservationAdapter(
            Observations(ambiguous)
        ).observe()
        self.assertEqual(result.context.egpu_presence, EgpuPresence.UNKNOWN)
        self.assertFalse(result.context.exact_egpu_identity_verified)

    def test_missing_drm_inventory_cannot_be_promoted_to_absence(self):
        value = snapshot("portable.json")
        incomplete = dataclasses.replace(
            value,
            blockers=(Blocker("drm_inventory_unavailable", "test"),),
        )
        result = SnapshotSleepWorkflowObservationAdapter(
            Observations(incomplete)
        ).observe()
        self.assertEqual(result.context.egpu_presence, EgpuPresence.UNKNOWN)
        self.assertFalse(result.context.exact_egpu_identity_verified)


if __name__ == "__main__":
    unittest.main()
