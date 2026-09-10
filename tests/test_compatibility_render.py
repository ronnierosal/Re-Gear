from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.compatibility_render import (  # noqa: E402
    CompatibilityExternalHandoffCollector,
    CompatibilityRenderEvidenceCollector,
)
from regear.domain.compatibility_test import (  # noqa: E402
    CompatibilityBaseline,
    CompatibilityTestOptions,
    CompatibilityTestStage,
    record_compatibility_baseline,
    start_compatibility_test,
)
from regear.domain.control_plane import PlacementState  # noqa: E402
from regear.domain.game_compatibility import (  # noqa: E402
    CompatibilityEvidenceKind,
    EgpuHandoffStatus,
    ObservedRenderGpu,
)
from regear.domain.game_render_activity import (  # noqa: E402
    GameRenderActivityEvidence,
    GameRenderActivityStatus,
)
from regear.domain.game_runtime import GameRuntimeKind  # noqa: E402
from regear.domain.game_session import (  # noqa: E402
    ActiveGameIdentity,
    GameSessionObservation,
)
from regear.domain.models import GameState  # noqa: E402


IDENTITY = ActiveGameIdentity("1234", ("app-steam-app1234-test.scope",))


def session(*, app_id="1234"):
    value = start_compatibility_test(
        session_id="compat-render-session",
        options=CompatibilityTestOptions(
            test_egpu_handoff=True, test_save_exit=False
        ),
        evidence_kind=CompatibilityEvidenceKind.SIMULATION,
        game_catalog_id="steam-1234",
        host_profile_id="asus-rog-ally-x",
        egpu_profile_id="gpd-g1-rx7600mxt-titan-ridge",
        regear_version="0.2.0",
        steamos_version="20260831",
        user_confirmed=True,
        now_ms=100,
        ttl_ms=1000,
    )
    return record_compatibility_baseline(
        value,
        CompatibilityBaseline(
            "baseline-generation",
            PlacementState.PORTABLE,
            GameState.RUNNING,
            app_id,
            ObservedRenderGpu.INTERNAL,
        ),
        now_ms=101,
    )


def evidence(
    status=GameRenderActivityStatus.ACTIVE,
    *,
    placement=PlacementState.DOCKED_EGPU,
):
    return GameRenderActivityEvidence(
        status,
        GameRuntimeKind.NATIVE,
        1 if status is GameRenderActivityStatus.ACTIVE else 0,
        (
            "render_activity.active"
            if status is GameRenderActivityStatus.ACTIVE
            else "render_activity.idle_window"
        ),
        "a" * 64,
        placement,
    )


class Renderer:
    def __init__(self, value):
        self.value = value

    def observe(self, identity, *, user_uid):
        if isinstance(self.value, Exception):
            raise self.value
        self.identity = identity
        self.user_uid = user_uid
        return self.value


class Sessions:
    def __init__(self, *values):
        self.values = iter(values)

    def observe(self):
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value


def running_session(sample_id="b" * 64):
    return GameSessionObservation(GameState.RUNNING, "c" * 64, sample_id, IDENTITY)


class CompatibilityRenderEvidenceTests(unittest.TestCase):
    def test_exact_active_docked_egpu_evidence_records_but_does_not_review(self):
        renderer = Renderer(evidence())
        result = CompatibilityRenderEvidenceCollector(
            renderer
        ).record_external_handoff(session(), IDENTITY, user_uid=1000, now_ms=102)

        self.assertEqual(result.stage, CompatibilityTestStage.ACTIVE)
        self.assertEqual(result.egpu_handoff, EgpuHandoffStatus.VERIFIED)
        self.assertEqual(result.observed_render_gpu, ObservedRenderGpu.EXTERNAL)
        self.assertEqual(result.observation_generations[-1], "a" * 64)
        self.assertEqual(renderer.identity, IDENTITY)

    def test_idle_window_or_wrong_placement_stops_without_recording_success(self):
        idle = CompatibilityRenderEvidenceCollector(
            Renderer(evidence(GameRenderActivityStatus.IDLE_WINDOW))
        ).record_external_handoff(session(), IDENTITY, user_uid=1000, now_ms=102)
        portable = CompatibilityRenderEvidenceCollector(
            Renderer(evidence(placement=PlacementState.BOOSTED_HANDHELD))
        ).record_external_handoff(session(), IDENTITY, user_uid=1000, now_ms=102)

        self.assertEqual(idle.stage, CompatibilityTestStage.ACTION_REQUIRED)
        self.assertEqual(idle.egpu_handoff, EgpuHandoffStatus.UNTESTED)
        self.assertEqual(
            idle.reason_code, "compatibility.external_render_unverified"
        )
        self.assertEqual(portable.stage, CompatibilityTestStage.ACTION_REQUIRED)
        self.assertEqual(
            portable.reason_code,
            "compatibility.external_placement_unverified",
        )

    def test_app_identity_mismatch_or_renderer_failure_fails_closed(self):
        mismatch = CompatibilityRenderEvidenceCollector(
            Renderer(evidence())
        ).record_external_handoff(
            session(app_id="9999"), IDENTITY, user_uid=1000, now_ms=102
        )
        failed = CompatibilityRenderEvidenceCollector(
            Renderer(OSError("unavailable"))
        ).record_external_handoff(session(), IDENTITY, user_uid=1000, now_ms=102)

        self.assertEqual(
            mismatch.reason_code, "compatibility.render_baseline_mismatch"
        )
        self.assertEqual(
            failed.reason_code, "compatibility.external_render_unverified"
        )
        self.assertTrue(
            all(
                value.stage is CompatibilityTestStage.ACTION_REQUIRED
                for value in (mismatch, failed)
            )
        )

    def test_external_capture_requires_a_stable_exact_game_session(self):
        capture = CompatibilityExternalHandoffCollector(
            sessions=Sessions(running_session(), running_session("d" * 64)),
            render_collector=CompatibilityRenderEvidenceCollector(Renderer(evidence())),
        )
        accepted = capture.capture_external_handoff(
            session(), user_uid=1000, now_ms=102
        )
        changed = CompatibilityExternalHandoffCollector(
            sessions=Sessions(
                running_session(),
                replace(running_session("d" * 64), generation="e" * 64),
            ),
            render_collector=CompatibilityRenderEvidenceCollector(Renderer(evidence())),
        ).capture_external_handoff(session(), user_uid=1000, now_ms=102)

        self.assertEqual(accepted.egpu_handoff, EgpuHandoffStatus.VERIFIED)
        self.assertEqual(changed.stage, CompatibilityTestStage.ACTION_REQUIRED)
        self.assertEqual(changed.reason_code, "compatibility.external_game_changed")


if __name__ == "__main__":
    unittest.main()
