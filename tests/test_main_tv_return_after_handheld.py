"""Regression coverage for an explicit TV return after Portable handoff."""

from __future__ import annotations

import asyncio
import types
import unittest
from unittest.mock import AsyncMock, patch

from tests.test_automatic_dock import current
from tests.test_main_process_delivery import load_main_module
from regear.application.connection_readiness import ConnectionReadinessStage
from regear.application.presentation_completion import PresentationCompletion
from regear.application.supervised_transition import SupervisedTransitionExecution
from regear.domain.control_plane import (
    PlacementState,
    TransitionOutcome,
    TransitionOutcomeKind,
    WorkflowState,
)


def presentation_status(
    *,
    target: PlacementState = PlacementState.UNKNOWN,
    acknowledgement_required: bool = False,
    action_required: bool = False,
    code: str = "transition.idle",
):
    return types.SimpleNamespace(
        acknowledgement_required=acknowledgement_required,
        action_required=action_required,
        target=target,
        operation_id="portable-operation" if acknowledgement_required else "",
        code=code,
    )


class MainTvReturnAfterHandheldTests(unittest.IsolatedAsyncioTestCase):
    async def test_tv_press_retires_exact_portable_result_before_preview(self):
        module = load_main_module()
        plugin = module.Plugin()
        calls = []

        class Service:
            def status(self):
                calls.append("status")
                return presentation_status(
                    target=PlacementState.PORTABLE,
                    acknowledgement_required=True,
                    code="transition.committed",
                )

            def acknowledge(self, operation_id):
                calls.append(("acknowledge", operation_id))
                return True

            def preview(self, target, *, user_confirmed):
                calls.append(("preview", target, user_confirmed))
                return types.SimpleNamespace(
                    approval_token="tv-approval",
                    blockers=(),
                )

        plugin._presentation_transition_service = lambda: Service()
        plugin._automatic_dock.suppress_current_attachment_after_portable_return()

        approval = await plugin.approve_supervised_tv_switch()

        self.assertEqual(approval["approval_token"], "tv-approval")
        self.assertEqual(
            calls,
            [
                "status",
                ("acknowledge", "portable-operation"),
                ("preview", PlacementState.DOCKED_EGPU, True),
            ],
        )
        self.assertEqual(
            plugin._automatic_dock.status().code,
            "automatic_dock.rearmed_after_acknowledgement",
        )

    async def test_missing_hdmi_rearms_existing_automatic_tv_loop(self):
        module = load_main_module()
        plugin = module.Plugin()
        observed = current("connected-internal.json")
        wakeups = []

        class Service:
            def status(self):
                return presentation_status(
                    target=PlacementState.PORTABLE,
                    acknowledgement_required=True,
                    code="transition.committed",
                )

            def acknowledge(self, operation_id):
                return operation_id == "portable-operation"

            def preview(self, target, *, user_confirmed):
                return types.SimpleNamespace(
                    approval_token="",
                    blockers=(
                        "display.external_unready",
                        "identity.transition_binding_incomplete",
                    ),
                )

        plugin._presentation_transition_service = lambda: Service()
        plugin._topology_wakeup = types.SimpleNamespace(
            invalidate=lambda: wakeups.append("wake")
        )
        plugin._automatic_dock.suppress_current_attachment_after_portable_return()

        approval = await plugin.approve_supervised_tv_switch()

        self.assertEqual(approval["approval_token"], "")
        self.assertEqual(
            approval["blockers"],
            [
                "display.external_unready",
                "identity.transition_binding_incomplete",
            ],
        )
        self.assertEqual(wakeups, ["wake"])
        self.assertEqual(
            plugin._automatic_dock.status().code,
            "automatic_dock.rearmed_after_acknowledgement",
        )

        dispatches = []
        connection = types.SimpleNamespace(
            stage=ConnectionReadinessStage.READY_IDLE,
            code="connection.ready_idle",
            poll_after_ms=1000,
            window_age_ms=0,
        )
        plugin._observe_connection_readiness = AsyncMock(return_value=connection)
        plugin._maybe_automatic_link_recovery = AsyncMock(return_value=False)
        plugin._update_saved_tv = AsyncMock()
        plugin._automatic_dock_preferences = lambda: types.SimpleNamespace(
            load=lambda: True
        )
        plugin._presentation_transition_service = lambda: types.SimpleNamespace(
            reconcile_completion=lambda _current: PresentationCompletion(
                "completion.test",
                hold_portable=False,
            )
        )

        async def run_background(fn):
            return fn()

        def dispatch(generation, consent):
            dispatches.append((generation, consent))
            return SupervisedTransitionExecution(
                True,
                "transition.succeeded",
                outcome=TransitionOutcome(
                    TransitionOutcomeKind.SUCCEEDED,
                    PlacementState.DOCKED_EGPU,
                    WorkflowState.IDLE,
                ),
                durable=True,
            )

        async def stop_after_dispatch(_delay):
            raise asyncio.CancelledError

        plugin._run_background_operation = run_background
        plugin._run_automatic_tv_transition = dispatch
        plugin._wait_for_topology = stop_after_dispatch
        plugin._topology_wakeup = None
        with patch.object(
            module,
            "SnapshotTransitionObservationAdapter",
            return_value=types.SimpleNamespace(observe=lambda: observed),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await plugin._automatic_dock_loop()

        self.assertEqual(dispatches, [(observed.generation, True)])

    async def test_other_or_unsuccessful_presentation_results_are_not_acknowledged(self):
        for status in (
            presentation_status(),
            presentation_status(
                target=PlacementState.DOCKED_EGPU,
                acknowledgement_required=True,
                code="transition.committed",
            ),
            presentation_status(
                target=PlacementState.PORTABLE,
                acknowledgement_required=True,
                action_required=True,
                code="transition.blocked",
            ),
            presentation_status(
                target=PlacementState.PORTABLE,
                acknowledgement_required=True,
                action_required=True,
                code="transition.failed",
            ),
            presentation_status(
                target=PlacementState.PORTABLE,
                acknowledgement_required=True,
                code="recovery.verified",
            ),
            presentation_status(
                target=PlacementState.PORTABLE,
                acknowledgement_required=True,
                code="portable_trial.application_unverified",
            ),
        ):
            with self.subTest(status=status):
                module = load_main_module()
                plugin = module.Plugin()
                service = types.SimpleNamespace(
                    status=lambda status=status: status,
                    acknowledge=AsyncMock(),
                    preview=lambda *_args, **_kwargs: types.SimpleNamespace(
                        approval_token="",
                        blockers=("journal.acknowledgement_required",),
                    ),
                )
                plugin._presentation_transition_service = lambda: service
                plugin._automatic_dock.suppress_current_attachment_after_portable_return()

                approval = await plugin.approve_supervised_tv_switch()

                self.assertEqual(approval["approval_token"], "")
                self.assertEqual(
                    approval["blockers"],
                    ["journal.acknowledgement_required"],
                )
                service.acknowledge.assert_not_awaited()
                self.assertEqual(
                    plugin._automatic_dock.status().code,
                    "automatic_dock.suppressed_for_safe_disconnect",
                )


if __name__ == "__main__":
    unittest.main()
