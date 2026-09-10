import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from hdm.domain.models import Confidence, DisplayKind, EgpuPresence, GpuRole
from hdm.domain.serialization import snapshot_from_dict
from hdm.domain.tdp_placement import tdp_placement_readiness


class TdpPlacementTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = snapshot_from_dict(json.loads((Path(__file__).parent / "fixtures/portable.json").read_text()))

    def test_detached_portable_is_the_only_currently_supported_placement(self):
        self.assertEqual(tdp_placement_readiness(self.snapshot, EgpuPresence.ABSENT), "tdp.ready")
        for role, display, expected in (
            (GpuRole.INTERNAL, DisplayKind.EXTERNAL, "tdp.docked_power_profile_unavailable"),
            (GpuRole.EXTERNAL, DisplayKind.INTERNAL, "tdp.egpu_power_profile_unavailable"),
            (GpuRole.EXTERNAL, DisplayKind.EXTERNAL, "tdp.egpu_power_profile_unavailable"),
        ):
            snapshot = replace(self.snapshot, gpus=(replace(self.snapshot.gpus[0], role=role),),
                               displays=(replace(self.snapshot.displays[0], kind=display),))
            presence = EgpuPresence.ABSENT if role is GpuRole.INTERNAL else EgpuPresence.PRESENT
            self.assertEqual(tdp_placement_readiness(snapshot, presence), expected)

    def test_attach_and_unknown_presence_override_portable_label(self):
        self.assertEqual(tdp_placement_readiness(self.snapshot, EgpuPresence.PRESENT), "tdp.egpu_attached")
        self.assertEqual(tdp_placement_readiness(self.snapshot, EgpuPresence.UNKNOWN), "tdp.egpu_presence_unverified")

    def test_conflicting_or_incomplete_placement_never_admits_power_control(self):
        for gamescope in (replace(self.snapshot.gamescope, running=False),
                          replace(self.snapshot.gamescope, confidence=Confidence.UNKNOWN),
                          replace(self.snapshot.gamescope, render_gpu_stable_id="different")):
            self.assertEqual(tdp_placement_readiness(replace(self.snapshot, gamescope=gamescope), EgpuPresence.ABSENT), "tdp.placement_unverified")

    def test_returning_to_portable_requires_fresh_consistent_observation(self):
        self.assertNotEqual(tdp_placement_readiness(self.snapshot, EgpuPresence.PRESENT), "tdp.ready")
        self.assertNotEqual(tdp_placement_readiness(self.snapshot, EgpuPresence.UNKNOWN), "tdp.ready")
        self.assertEqual(tdp_placement_readiness(self.snapshot, EgpuPresence.ABSENT), "tdp.ready")
