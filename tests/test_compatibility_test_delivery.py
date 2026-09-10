from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.delivery.compatibility_test import (  # noqa: E402
    compatibility_test_status_to_payload,
)
from regear.domain.compatibility_test import (  # noqa: E402
    CompatibilityBaseline,
    CompatibilityTestOptions,
    CompatibilityTestStage,
    finish_compatibility_test,
    record_compatibility_baseline,
    record_egpu_handoff_result,
    record_save_result,
    start_compatibility_test,
)
from regear.domain.control_plane import PlacementState  # noqa: E402
from regear.domain.game_compatibility import (  # noqa: E402
    CompatibilityEvidenceKind,
    EgpuHandoffStatus,
    ObservedRenderGpu,
    SaveTestOutcome,
)
from regear.domain.models import GameState  # noqa: E402


def awaiting_review():
    session = start_compatibility_test(
        session_id="private-session-123",
        options=CompatibilityTestOptions(),
        evidence_kind=CompatibilityEvidenceKind.HARDWARE_TEST,
        game_catalog_id="steam-1234",
        host_profile_id="asus-rog-ally-x",
        egpu_profile_id="gpd-g1-rx7600mxt-titan-ridge",
        regear_version="0.2.0",
        steamos_version="20260831",
        user_confirmed=True,
        hardware_test_authorized=True,
        now_ms=100,
    )
    session = record_compatibility_baseline(
        session,
        CompatibilityBaseline(
            "a" * 64,
            PlacementState.PORTABLE,
            GameState.RUNNING,
            "1234",
            ObservedRenderGpu.INTERNAL,
        ),
        now_ms=101,
    )
    session = record_egpu_handoff_result(
        session,
        status=EgpuHandoffStatus.VERIFIED,
        observed_render_gpu=ObservedRenderGpu.EXTERNAL,
        observation_generation="b" * 64,
        now_ms=102,
    )
    session = record_save_result(
        session,
        outcome=SaveTestOutcome.MANUAL_SAVE_REQUIRED,
        observation_generation="c" * 64,
        now_ms=103,
    )
    return finish_compatibility_test(session, now_ms=104)


class CompatibilityTestDeliveryTests(unittest.TestCase):
    def test_missing_session_is_categorical_and_non_authorizing(self):
        payload = compatibility_test_status_to_payload(None)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["stage"], "unavailable")
        self.assertFalse(payload["review_required"])

    def test_payload_exposes_only_categorical_progress(self):
        payload = compatibility_test_status_to_payload(awaiting_review())
        encoded = json.dumps(payload, sort_keys=True).lower()

        self.assertTrue(payload["available"])
        self.assertEqual(payload["stage"], "awaiting_review")
        self.assertTrue(payload["review_required"])
        self.assertFalse(payload["action_required"])
        self.assertEqual(payload["egpu_handoff"], "verified")
        for private in (
            "private-session",
            "steam-1234",
            "1234",
            "asus",
            "gpd",
            "20260831",
            "aaaaaaaa",
            "bbbbbbbb",
            "started",
            "expires",
        ):
            self.assertNotIn(private, encoded)


if __name__ == "__main__":
    unittest.main()
