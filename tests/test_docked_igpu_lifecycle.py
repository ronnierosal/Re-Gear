from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.docked_igpu_exit import (  # noqa: E402
    DockedIgpuExitArmResult,
    DockedIgpuExitStage,
    DockedIgpuExitWatch,
)
from regear.application.docked_igpu_lifecycle import (  # noqa: E402
    DockedIgpuLifecycleStage,
    DockedIgpuWatchLifecycle,
)
from regear.application.docked_igpu_promotion import (  # noqa: E402
    DockedIgpuPromotionPollResult,
    DockedIgpuPromotionPrepareResult,
)
from regear.application.supervised_transition import (  # noqa: E402
    SupervisedTransitionPreview,
)
from regear.delivery.docked_igpu_lifecycle import (  # noqa: E402
    lifecycle_inspection_to_payload,
    lifecycle_status_to_payload,
)
from regear.domain.control_plane import PlacementState  # noqa: E402
from regear.domain.game_session import ActiveGameIdentity  # noqa: E402


GAME = ActiveGameIdentity("1234", ("app-steam-app1234-test.scope",))


def watch(stage=DockedIgpuExitStage.WATCHING, reason="docked_igpu.watching_game_exit"):
    return DockedIgpuExitWatch(
        watch_id="docked-igpu-watch-private-1",
        stage=stage,
        game=GAME,
        host_profile_id="asus-rog-ally-x",
        egpu_profile_id="gpd-g1-rx7600m-xt",
        egpu_stable_id="gpd-g1:0123456789abcdef",
        armed_snapshot_generation="snapshot-generation-private",
        armed_snapshot_sample_id="snapshot-sample-private",
        armed_game_generation="game-generation-private",
        gamescope_session_generation="a" * 64,
        armed_at_ms=100,
        expires_at_ms=1000,
        reason_code=reason,
        ready_snapshot_generation=(
            "ready-generation-private"
            if stage is DockedIgpuExitStage.PROMOTION_READY
            else ""
        ),
    )


class PromotionFacade:
    def __init__(
        self,
        *,
        arms=(),
        polls=(),
        prepares=(),
        cancel=True,
        inspection_supported=True,
    ):
        self.arms = list(arms)
        self.polls = list(polls)
        self.prepares = list(prepares)
        self.cancel_result = cancel
        self.arm_calls = 0
        self.poll_calls = []
        self.prepare_calls = []
        self.cancel_calls = []
        self.inspection_supported = inspection_supported

    def arm(self):
        self.arm_calls += 1
        value = self.arms.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def poll(self, watch_id):
        self.poll_calls.append(watch_id)
        value = self.polls.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def cancel(self, watch_id):
        self.cancel_calls.append(watch_id)
        if isinstance(self.cancel_result, Exception):
            raise self.cancel_result
        return self.cancel_result

    def prepare(self, watch_id, *, user_confirmed):
        self.prepare_calls.append((watch_id, user_confirmed))
        value = self.prepares.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class DockedIgpuWatchLifecycleTests(unittest.TestCase):
    def test_arms_polls_and_retains_ready_without_automatic_authority(self):
        armed = watch()
        ready = replace(
            armed,
            stage=DockedIgpuExitStage.PROMOTION_READY,
            reason_code="docked_igpu.promotion_ready",
            ready_snapshot_generation="ready-generation-private",
        )
        facade = PromotionFacade(
            arms=(DockedIgpuExitArmResult(True, "docked_igpu.watch_armed", armed),),
            polls=(
                DockedIgpuPromotionPollResult(
                    True, "docked_igpu.promotion_ready", ready
                ),
            ),
        )
        lifecycle = DockedIgpuWatchLifecycle(facade)

        watching = lifecycle.tick()
        promotion_ready = lifecycle.tick()
        retained = lifecycle.tick()

        self.assertEqual(watching.stage, DockedIgpuLifecycleStage.WATCHING)
        self.assertEqual(
            promotion_ready.stage, DockedIgpuLifecycleStage.PROMOTION_READY
        )
        self.assertTrue(promotion_ready.inspection_available)
        self.assertIs(retained, promotion_ready)
        self.assertEqual(len(facade.poll_calls), 1)
        self.assertEqual(facade.cancel_calls, [])

    def test_ineligible_state_stays_idle_and_retries_without_retaining_identity(self):
        facade = PromotionFacade(
            arms=(
                DockedIgpuExitArmResult(
                    False, "docked_igpu.placement_unverified"
                ),
                DockedIgpuExitArmResult(
                    False, "docked_igpu.game_not_running"
                ),
            )
        )
        lifecycle = DockedIgpuWatchLifecycle(facade, poll_interval_ms=500)

        first = lifecycle.tick()
        second = lifecycle.tick()

        self.assertEqual(first.stage, DockedIgpuLifecycleStage.IDLE)
        self.assertEqual(second.stage, DockedIgpuLifecycleStage.IDLE)
        self.assertEqual(second.code, "docked_igpu.game_not_running")
        self.assertEqual(second.poll_after_ms, 15000)
        self.assertEqual(facade.arm_calls, 2)

    def test_cancelled_watch_is_released_before_later_rearm(self):
        first = watch()
        second = replace(first, watch_id="docked-igpu-watch-private-2")
        cancelled = replace(
            first,
            stage=DockedIgpuExitStage.CANCELLED,
            reason_code="docked_igpu.placement_changed",
        )
        facade = PromotionFacade(
            arms=(
                DockedIgpuExitArmResult(True, "docked_igpu.watch_armed", first),
                DockedIgpuExitArmResult(True, "docked_igpu.watch_armed", second),
            ),
            polls=(
                DockedIgpuPromotionPollResult(
                    True, "docked_igpu.placement_changed", cancelled
                ),
            ),
        )
        lifecycle = DockedIgpuWatchLifecycle(facade)

        lifecycle.tick()
        idle = lifecycle.tick()
        rearmed = lifecycle.tick()

        self.assertEqual(idle.stage, DockedIgpuLifecycleStage.IDLE)
        self.assertEqual(rearmed.stage, DockedIgpuLifecycleStage.WATCHING)
        self.assertEqual(facade.cancel_calls, [first.watch_id])

    def test_action_required_freezes_until_exact_acknowledgement_cleanup(self):
        armed = watch()
        action = replace(
            armed,
            stage=DockedIgpuExitStage.ACTION_REQUIRED,
            reason_code="docked_igpu.game_identity_unverified",
        )
        facade = PromotionFacade(
            arms=(DockedIgpuExitArmResult(True, "docked_igpu.watch_armed", armed),),
            polls=(
                DockedIgpuPromotionPollResult(
                    True, "docked_igpu.game_identity_unverified", action
                ),
            ),
        )
        lifecycle = DockedIgpuWatchLifecycle(facade)

        lifecycle.tick()
        required = lifecycle.tick()
        frozen = lifecycle.tick()
        acknowledged = lifecycle.acknowledge_action()

        self.assertEqual(required.stage, DockedIgpuLifecycleStage.ACTION_REQUIRED)
        self.assertTrue(required.acknowledgement_required)
        self.assertIs(frozen, required)
        self.assertTrue(acknowledged)
        self.assertEqual(lifecycle.status().stage, DockedIgpuLifecycleStage.IDLE)

    def test_poll_failure_and_lost_ownership_fail_closed(self):
        armed = watch()
        poll_failure = PromotionFacade(
            arms=(DockedIgpuExitArmResult(True, "docked_igpu.watch_armed", armed),),
            polls=(RuntimeError("private failure"),),
        )
        lifecycle = DockedIgpuWatchLifecycle(poll_failure)
        lifecycle.tick()
        failed = lifecycle.tick()

        lost = DockedIgpuWatchLifecycle(
            PromotionFacade(
                arms=(
                    DockedIgpuExitArmResult(
                        False, "docked_igpu.watch_already_active"
                    ),
                )
            )
        ).tick()

        self.assertEqual(failed.stage, DockedIgpuLifecycleStage.ACTION_REQUIRED)
        self.assertEqual(failed.code, "docked_igpu.poll_unavailable")
        self.assertEqual(lost.code, "docked_igpu.watch_ownership_lost")

    def test_close_is_idempotent_cancels_once_and_never_rearms(self):
        armed = watch()
        facade = PromotionFacade(
            arms=(DockedIgpuExitArmResult(True, "docked_igpu.watch_armed", armed),)
        )
        lifecycle = DockedIgpuWatchLifecycle(facade)
        lifecycle.tick()

        first = lifecycle.close()
        second = lifecycle.close()
        after = lifecycle.tick()

        self.assertEqual(first.stage, DockedIgpuLifecycleStage.CLOSED)
        self.assertIs(second, first)
        self.assertIs(after, first)
        self.assertEqual(facade.cancel_calls, [armed.watch_id])
        self.assertEqual(facade.arm_calls, 1)

    def test_close_retains_private_watch_for_bounded_cleanup_retry(self):
        armed = watch()
        facade = PromotionFacade(
            arms=(DockedIgpuExitArmResult(True, "docked_igpu.watch_armed", armed),),
            cancel=False,
        )
        lifecycle = DockedIgpuWatchLifecycle(facade)
        lifecycle.tick()

        incomplete = lifecycle.close()
        facade.cancel_result = True
        completed = lifecycle.close()

        self.assertEqual(incomplete.code, "docked_igpu.lifecycle_close_incomplete")
        self.assertEqual(completed.code, "docked_igpu.lifecycle_closed")
        self.assertEqual(facade.cancel_calls, [armed.watch_id, armed.watch_id])
        self.assertEqual(lifecycle.tick().stage, DockedIgpuLifecycleStage.CLOSED)

    def test_public_payload_is_identity_free_and_poll_bounds_are_enforced(self):
        status = DockedIgpuWatchLifecycle(
            PromotionFacade(
                arms=(
                    DockedIgpuExitArmResult(
                        False, "docked_igpu.placement_unverified"
                    ),
                )
            )
        ).tick()
        encoded = json.dumps(lifecycle_status_to_payload(status), sort_keys=True)

        for private in (
            "1234",
            "app-steam",
            "private",
            "asus",
            "gpd-g1:",
            "generation",
            "watch_id",
        ):
            self.assertNotIn(private, encoded)
        with self.assertRaisesRegex(ValueError, "poll interval"):
            DockedIgpuWatchLifecycle(PromotionFacade(), poll_interval_ms=100)

    def test_ready_inspection_is_non_authorizing_private_and_repeatable(self):
        armed = watch()
        ready = replace(
            armed,
            stage=DockedIgpuExitStage.PROMOTION_READY,
            reason_code="docked_igpu.promotion_ready",
            ready_snapshot_generation="ready-generation-private",
        )
        preview = SupervisedTransitionPreview(
            PlacementState.DOCKED_EGPU,
            PlacementState.DOCKED_IGPU,
        )
        facade = PromotionFacade(
            arms=(
                DockedIgpuExitArmResult(
                    True, "docked_igpu.watch_armed", armed
                ),
            ),
            polls=(
                DockedIgpuPromotionPollResult(
                    True, "docked_igpu.promotion_ready", ready
                ),
            ),
            prepares=(
                DockedIgpuPromotionPrepareResult(
                    True, "docked_igpu.preview_ready", preview
                ),
                DockedIgpuPromotionPrepareResult(
                    True, "docked_igpu.preview_ready", preview
                ),
            ),
        )
        lifecycle = DockedIgpuWatchLifecycle(facade)
        lifecycle.tick()
        lifecycle.tick()

        first = lifecycle.inspect_ready()
        second = lifecycle.inspect_ready()
        encoded = json.dumps(lifecycle_inspection_to_payload(first), sort_keys=True)

        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertEqual(
            facade.prepare_calls,
            [(armed.watch_id, False), (armed.watch_id, False)],
        )
        self.assertEqual(
            lifecycle.status().stage, DockedIgpuLifecycleStage.PROMOTION_READY
        )
        for private in ("watch", "private", "generation", "approval_token", "1234"):
            self.assertNotIn(private, encoded)

    def test_inspection_blockers_are_sanitized_and_watch_is_retained(self):
        armed = watch()
        ready = replace(
            armed,
            stage=DockedIgpuExitStage.PROMOTION_READY,
            reason_code="docked_igpu.promotion_ready",
            ready_snapshot_generation="ready-generation-private",
        )
        preview = SupervisedTransitionPreview(
            PlacementState.DOCKED_EGPU,
            PlacementState.DOCKED_IGPU,
            blockers=("integration.not_ready", "unsafe blocker detail"),
        )
        facade = PromotionFacade(
            arms=(
                DockedIgpuExitArmResult(
                    True, "docked_igpu.watch_armed", armed
                ),
            ),
            polls=(
                DockedIgpuPromotionPollResult(
                    True, "docked_igpu.promotion_ready", ready
                ),
            ),
            prepares=(
                DockedIgpuPromotionPrepareResult(
                    False, "docked_igpu.preview_blocked", preview
                ),
            ),
        )
        lifecycle = DockedIgpuWatchLifecycle(facade)
        lifecycle.tick()
        lifecycle.tick()

        result = lifecycle.inspect_ready()

        self.assertFalse(result.accepted)
        self.assertEqual(
            result.blockers,
            ("integration.not_ready", "transition.blocker_unavailable"),
        )
        self.assertEqual(
            lifecycle.status().stage, DockedIgpuLifecycleStage.PROMOTION_READY
        )

    def test_ready_watch_without_preview_authority_reports_no_inspection(self):
        armed = watch()
        ready = replace(
            armed,
            stage=DockedIgpuExitStage.PROMOTION_READY,
            reason_code="docked_igpu.promotion_ready",
            ready_snapshot_generation="ready-generation-private",
        )
        facade = PromotionFacade(
            arms=(
                DockedIgpuExitArmResult(
                    True, "docked_igpu.watch_armed", armed
                ),
            ),
            polls=(
                DockedIgpuPromotionPollResult(
                    True, "docked_igpu.promotion_ready", ready
                ),
            ),
            inspection_supported=False,
        )
        lifecycle = DockedIgpuWatchLifecycle(
            facade, poll_interval_ms=5000, idle_poll_interval_ms=15000
        )
        lifecycle.tick()

        ready_status = lifecycle.tick()
        inspection = lifecycle.inspect_ready()
        cleared = lifecycle.tick()

        self.assertFalse(ready_status.inspection_available)
        self.assertEqual(ready_status.poll_after_ms, 5000)
        self.assertFalse(inspection.accepted)
        self.assertEqual(inspection.code, "docked_igpu.inspection_unavailable")
        self.assertEqual(facade.prepare_calls, [])
        self.assertEqual(cleared.stage, DockedIgpuLifecycleStage.IDLE)
        self.assertEqual(cleared.code, "docked_igpu.promotion_observed")
        self.assertEqual(cleared.poll_after_ms, 15000)
        self.assertEqual(facade.cancel_calls, [armed.watch_id])
        self.assertIs(lifecycle.acknowledge_action(), False)

    def test_unexpected_authority_fails_closed_and_requires_acknowledgement(self):
        armed = watch()
        ready = replace(
            armed,
            stage=DockedIgpuExitStage.PROMOTION_READY,
            reason_code="docked_igpu.promotion_ready",
            ready_snapshot_generation="ready-generation-private",
        )
        preview = SupervisedTransitionPreview(
            PlacementState.DOCKED_EGPU,
            PlacementState.DOCKED_IGPU,
            approval_token="must-not-cross-boundary",
        )
        facade = PromotionFacade(
            arms=(
                DockedIgpuExitArmResult(
                    True, "docked_igpu.watch_armed", armed
                ),
            ),
            polls=(
                DockedIgpuPromotionPollResult(
                    True, "docked_igpu.promotion_ready", ready
                ),
            ),
            prepares=(
                DockedIgpuPromotionPrepareResult(
                    True, "docked_igpu.preview_ready", preview
                ),
            ),
        )
        lifecycle = DockedIgpuWatchLifecycle(facade)
        lifecycle.tick()
        lifecycle.tick()

        result = lifecycle.inspect_ready()

        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "docked_igpu.unexpected_transition_authority")
        self.assertEqual(
            lifecycle.status().stage, DockedIgpuLifecycleStage.ACTION_REQUIRED
        )
        self.assertTrue(lifecycle.acknowledge_action())


if __name__ == "__main__":
    unittest.main()
