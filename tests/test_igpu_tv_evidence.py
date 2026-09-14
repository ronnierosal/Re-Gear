"""Adversarial evidence tests; fixtures do not certify a live presenter."""
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.domain.igpu_tv_evidence import (
    GameSessionEvidence, bind_igpu_tv, check_igpu_tv,
)
from regear.domain.models import (
    Confidence, DisplayKind, DisplayObservation, GameState, GamescopeObservation,
    GpuObservation, GpuRole, ObservedSnapshot, SupportTier,
)

V = Confidence.VERIFIED
U = Confidence.UNKNOWN


class IgpuTvEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.igpu = GpuObservation("internal-id", GpuRole.INTERNAL, "vendor:i", True, True, V)
        self.egpu = GpuObservation("external-id", GpuRole.EXTERNAL, "vendor:e", True, False, V)
        self.tv = DisplayObservation(
            "edid-tv", DisplayKind.EXTERNAL, "observed-connector", True, False,
            True, V, owning_gpu_stable_id="external-id", owning_gpu_confidence=V,
        )
        self.snapshot = ObservedSnapshot(
            1, "sample", "profile", SupportTier.EXPERIMENTAL, GameState.RUNNING,
            (self.igpu, self.egpu), (self.tv,),
            GamescopeObservation(True, 123, render_gpu_stable_id="internal-id", confidence=V),
        )
        self.evidence = GameSessionEvidence(
            "boot:session", "boot:game:pid:start", True, V, "internal-id", V,
            "boot:compositor:pid:start", "internal-id", V,
        )
        self.binding = self.bind().binding
        self.assertIsNotNone(self.binding)

    def bind(self, snapshot=None, evidence=None):
        return bind_igpu_tv(
            snapshot or self.snapshot, evidence or self.evidence,
            igpu_stable_id="internal-id", egpu_stable_id="external-id", tv_stable_id="edid-tv",
        )

    def test_preparation_is_not_presentation(self):
        self.assertEqual(self.bind().blockers, ())
        self.assertIn("tv_presentation_not_verified", check_igpu_tv(
            self.snapshot, self.evidence, self.binding, require_presented=True))
        tv = replace(self.tv, active=True, active_confidence=V, mode_committed=True)
        self.assertEqual(check_igpu_tv(replace(self.snapshot, displays=(tv,)),
                                     self.evidence, self.binding, require_presented=True), ())

    def test_selector_and_open_device_are_not_game_renderer_proof(self):
        for grade in (U, Confidence.OBSERVED):
            evidence = replace(self.evidence, game_render_confidence=grade)
            self.assertIsNone(self.bind(evidence=evidence).binding)
        self.assertIsNone(self.bind(evidence=replace(
            self.evidence, game_render_gpu_stable_id="external-id")).binding)

    def test_independent_compositor_renderer_and_snapshot_must_agree(self):
        for evidence in (
            replace(self.evidence, compositor_render_confidence=U),
            replace(self.evidence, compositor_render_gpu_stable_id="external-id"),
        ):
            self.assertIsNone(self.bind(evidence=evidence).binding)
        for changes in ({"running": None}, {"confidence": U},
                        {"render_gpu_stable_id": "external-id"}):
            snapshot = replace(self.snapshot, gamescope=replace(self.snapshot.gamescope, **changes))
            self.assertIsNone(self.bind(snapshot).binding)

    def test_preserves_exact_process_birth_and_session_identity(self):
        for field in ("session_id", "game_instance_id", "compositor_instance_id"):
            for value in ("", "same-pid-new-start"):
                with self.subTest(field=field, value=value):
                    self.assertTrue(check_igpu_tv(self.snapshot,
                        replace(self.evidence, **{field: value}), self.binding))
                    if not value:
                        self.assertIsNone(self.bind(evidence=replace(self.evidence, **{field: value})).binding)

    def test_unknown_or_contradictory_game_state_refuses(self):
        for state in (GameState.IDLE, GameState.UNKNOWN):
            self.assertIsNone(self.bind(replace(self.snapshot, game_state=state)).binding)
        for evidence in (replace(self.evidence, game_running=None),
                         replace(self.evidence, game_running=False),
                         replace(self.evidence, game_confidence=U)):
            self.assertIsNone(self.bind(evidence=evidence).binding)

    def test_missing_duplicate_or_unverified_gpu_refuses(self):
        for gpus in ((self.igpu,), (self.egpu,), (self.igpu, self.egpu, self.egpu),
                     (self.igpu, replace(self.egpu, present=False)),
                     (self.igpu, replace(self.egpu, confidence=U)),
                     (self.igpu, replace(self.egpu, role=GpuRole.INTERNAL))):
            self.assertIsNone(self.bind(replace(self.snapshot, gpus=gpus)).binding)
        for binding in (replace(self.binding, egpu_stable_id="internal-id"),
                        replace(self.binding, igpu_stable_id="")):
            self.assertTrue(check_igpu_tv(self.snapshot, self.evidence, binding))

    def test_missing_duplicate_or_changed_target_refuses(self):
        for displays in ((), (self.tv, self.tv),
                         (self.tv, replace(self.tv, stable_id="other-edid")),
                         (replace(self.tv, connector="moved-connector"),)):
            self.assertTrue(check_igpu_tv(replace(self.snapshot, displays=displays),
                                         self.evidence, self.binding))

    def test_connection_edid_and_owner_are_independent_guards(self):
        for changes in ({"connected": False}, {"connected": None}, {"edid_ready": False},
                        {"edid_ready": None}, {"confidence": U}, {"kind": DisplayKind.INTERNAL},
                        {"owning_gpu_stable_id": "internal-id"}, {"owning_gpu_stable_id": ""},
                        {"owning_gpu_confidence": U}):
            with self.subTest(changes=changes):
                self.assertIsNone(self.bind(replace(self.snapshot,
                    displays=(replace(self.tv, **changes),))).binding)

    def test_connection_confidence_does_not_grade_activity(self):
        for changes in ({"active": False}, {"active": None}, {"active_confidence": U},
                        {"active_confidence": Confidence.OBSERVED}, {"mode_committed": None},
                        {"mode_committed": False}):
            tv = replace(self.tv, active=True, active_confidence=V, mode_committed=True)
            snapshot = replace(self.snapshot, displays=(replace(tv, **changes),))
            self.assertIn("tv_presentation_not_verified", check_igpu_tv(
                snapshot, self.evidence, self.binding, require_presented=True))

    def test_idle_opt_in_retains_session_compositor_and_target_checks(self):
        snapshot = replace(self.snapshot, game_state=GameState.IDLE)
        evidence = replace(self.evidence, game_running=False, game_instance_id="",
                           game_render_gpu_stable_id="", game_render_confidence=U)
        self.assertTrue(check_igpu_tv(snapshot, evidence, self.binding))
        self.assertEqual(check_igpu_tv(snapshot, evidence, self.binding, allow_idle=True), ())
        for changed in (replace(evidence, game_confidence=U), replace(evidence, game_running=None),
                        replace(evidence, session_id="new-session"),
                        replace(evidence, compositor_instance_id="new-compositor")):
            self.assertTrue(check_igpu_tv(snapshot, changed, self.binding, allow_idle=True))
        self.assertTrue(check_igpu_tv(replace(snapshot, game_state=GameState.UNKNOWN),
                                     evidence, self.binding, allow_idle=True))
        self.assertTrue(check_igpu_tv(self.snapshot, replace(self.evidence, game_instance_id="new-game"),
                                     self.binding, allow_idle=True))


if __name__ == "__main__":
    unittest.main()
