"""Identity-free delivery mapping for dormant Compatibility Test Mode state."""

from __future__ import annotations

from ..domain.compatibility_test import CompatibilityTestSession, CompatibilityTestStage


def compatibility_test_status_to_payload(
    session: CompatibilityTestSession | None,
) -> dict[str, object]:
    """Expose categorical progress only; private test evidence never crosses delivery."""
    if session is None:
        return {
            "schema_version": 1,
            "available": False,
            "stage": "unavailable",
            "code": "compatibility.session_unavailable",
            "test_egpu_handoff": False,
            "test_save_exit": False,
            "egpu_handoff": "untested",
            "save_outcome": "not_tested",
            "review_required": False,
            "action_required": False,
        }
    return {
        "schema_version": 1,
        "available": True,
        "stage": session.stage.value,
        "code": session.reason_code,
        "test_egpu_handoff": session.options.test_egpu_handoff,
        "test_save_exit": session.options.test_save_exit,
        "egpu_handoff": session.egpu_handoff.value,
        "save_outcome": session.save_outcome.value,
        "review_required": session.stage is CompatibilityTestStage.AWAITING_REVIEW,
        "action_required": session.stage is CompatibilityTestStage.ACTION_REQUIRED,
    }
