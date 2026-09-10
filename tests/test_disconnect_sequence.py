from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.device_removal import (  # noqa: E402
    RemovalFunction,
    RemovalFunctionKind,
)
from regear.domain.disconnect_sequence import (  # noqa: E402
    DisconnectDecision,
    DisconnectStage,
    ReleaseOutcome,
    decide_disconnect,
)
from regear.domain.removal_safety import RemovalSafety, RemovalSafetyState  # noqa: E402
from regear.domain.safe_undock_readiness import SafeUndockRevalidation  # noqa: E402


GPU = RemovalFunction(RemovalFunctionKind.GPU, "0000:08:00.0")
AUDIO = RemovalFunction(RemovalFunctionKind.AUDIO, "0000:08:00.1")
BOTH = (GPU, AUDIO)


def ready() -> RemovalSafety:
    return RemovalSafety(
        RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL,
        "removal_safety.ready_for_supervised_removal",
        SafeUndockRevalidation("binding", "generation", "sample"),
    )


def blocked(code: str = "removal_safety.external_display_still_active") -> RemovalSafety:
    return RemovalSafety(RemovalSafetyState.NOT_READY, code)


class OrderingTests(unittest.TestCase):
    """Removal safety is only meaningful after the release has run."""

    def test_a_release_that_was_never_attempted_requires_one(self) -> None:
        decision = decide_disconnect(ReleaseOutcome.NOT_ATTEMPTED, ready(), BOTH, released_attachment="binding")
        self.assertIs(decision.stage, DisconnectStage.RELEASE_REQUIRED)
        self.assertFalse(decision.may_remove)

    def test_a_ready_verdict_cannot_substitute_for_a_release(self) -> None:
        """A clean-looking device that was never released must not be removed.

        Removal safety is not evidence that a release happened, and the
        verdict here describes a moment before the sequence began.
        """
        for outcome in (ReleaseOutcome.NOT_ATTEMPTED, ReleaseOutcome.REFUSED):
            decision = decide_disconnect(outcome, ready(), BOTH, released_attachment="binding")
            self.assertFalse(decision.may_remove, outcome)
            self.assertIsNone(decision.plan)

    def test_a_refused_release_does_not_consult_readiness(self) -> None:
        decision = decide_disconnect(ReleaseOutcome.REFUSED, ready(), BOTH, released_attachment="binding")
        self.assertIs(decision.stage, DisconnectStage.RELEASE_REFUSED)
        self.assertEqual(decision.code, "disconnect.release_refused")

    def test_remaining_holders_stop_the_sequence(self) -> None:
        decision = decide_disconnect(ReleaseOutcome.HOLDERS_REMAIN, ready(), BOTH, released_attachment="binding")
        self.assertIs(decision.stage, DisconnectStage.HOLDERS_REMAIN)
        self.assertFalse(decision.released)


class AfterReleaseTests(unittest.TestCase):
    """The distinction the sequence exists to preserve."""

    def test_released_but_unsafe_is_not_a_failed_release(self) -> None:
        """The state observed on hardware: holders clear, display retained."""
        decision = decide_disconnect(ReleaseOutcome.CLEAR, blocked(), BOTH, released_attachment="binding")
        self.assertIs(decision.stage, DisconnectStage.NOT_SAFE_AFTER_RELEASE)
        self.assertFalse(decision.may_remove)
        # The release worked. A caller must not tell a player it failed.
        self.assertTrue(decision.released)

    def test_the_blocking_fact_is_passed_through_untranslated(self) -> None:
        decision = decide_disconnect(ReleaseOutcome.CLEAR, blocked(), BOTH, released_attachment="binding")
        self.assertEqual(
            decision.code, "removal_safety.external_display_still_active"
        )

    def test_a_different_blocker_keeps_its_own_code(self) -> None:
        decision = decide_disconnect(
            ReleaseOutcome.CLEAR, blocked("removal_safety.game_running"), BOTH
        )
        self.assertEqual(decision.code, "removal_safety.game_running")

    def test_a_clear_release_with_a_ready_verdict_composes_a_plan(self) -> None:
        decision = decide_disconnect(ReleaseOutcome.CLEAR, ready(), BOTH, released_attachment="binding")
        self.assertIs(decision.stage, DisconnectStage.READY_TO_REMOVE)
        self.assertTrue(decision.may_remove)
        assert decision.plan is not None
        # Audio first, the order the successful supervised run used.
        self.assertEqual(decision.plan.addresses, ("0000:08:00.1", "0000:08:00.0"))

    def test_an_incomplete_function_set_is_not_ready(self) -> None:
        decision = decide_disconnect(ReleaseOutcome.CLEAR, ready(), (GPU,), released_attachment="binding")
        self.assertIs(decision.stage, DisconnectStage.NOT_SAFE_AFTER_RELEASE)
        self.assertFalse(decision.may_remove)

    def test_a_missing_readiness_after_a_clear_release_is_invalid(self) -> None:
        decision = decide_disconnect(ReleaseOutcome.CLEAR, None, BOTH, released_attachment="binding")
        self.assertIs(decision.stage, DisconnectStage.INVALID)
        self.assertFalse(decision.may_remove)


class InputTests(unittest.TestCase):
    def test_a_non_outcome_is_refused(self) -> None:
        decision = decide_disconnect("clear", ready(), BOTH, released_attachment="binding")
        self.assertIs(decision.stage, DisconnectStage.INVALID)

    def test_a_non_tuple_function_set_is_refused(self) -> None:
        decision = decide_disconnect(ReleaseOutcome.CLEAR, ready(), [GPU, AUDIO], released_attachment="binding")
        self.assertIs(decision.stage, DisconnectStage.INVALID)


class SafetyPropertyTests(unittest.TestCase):
    def test_only_ready_to_remove_permits_removal(self) -> None:
        for stage in DisconnectStage:
            if stage is DisconnectStage.READY_TO_REMOVE:
                continue
            decision = DisconnectDecision(stage, "code")
            self.assertFalse(
                decision.may_remove, f"{stage} must not permit removal"
            )

    def test_a_ready_decision_cannot_exist_without_a_usable_plan(self) -> None:
        with self.assertRaises(ValueError):
            DisconnectDecision(DisconnectStage.READY_TO_REMOVE, "code")

    def test_only_a_ready_decision_carries_a_plan(self) -> None:
        composed = decide_disconnect(
            ReleaseOutcome.CLEAR, ready(), BOTH, released_attachment="binding"
        ).plan
        with self.assertRaises(ValueError):
            DisconnectDecision(DisconnectStage.HOLDERS_REMAIN, "code", composed)


class AttachmentIdentityTests(unittest.TestCase):
    """Finding 4: a release carries no device identity of its own.

    A release performed on one eGPU, combined with ready evidence taken over
    another, previously composed a plan and reported that removal could
    proceed.
    """

    def test_a_release_for_a_different_device_is_refused(self) -> None:
        decision = decide_disconnect(
            ReleaseOutcome.CLEAR,
            ready(),
            BOTH,
            released_attachment="a-different-egpu",
        )
        self.assertIs(decision.stage, DisconnectStage.INVALID)
        self.assertEqual(decision.code, "disconnect.attachment_mismatch")
        self.assertFalse(decision.may_remove)

    def test_an_unstated_attachment_is_refused_rather_than_assumed(self) -> None:
        decision = decide_disconnect(ReleaseOutcome.CLEAR, ready(), BOTH)
        self.assertIs(decision.stage, DisconnectStage.INVALID)
        self.assertFalse(decision.may_remove)

    def test_the_same_device_still_composes(self) -> None:
        decision = decide_disconnect(
            ReleaseOutcome.CLEAR, ready(), BOTH, released_attachment="binding"
        )
        self.assertTrue(decision.may_remove)


if __name__ == "__main__":
    unittest.main()
