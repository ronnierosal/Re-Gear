from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.control_plane import PlacementState, WorkflowState  # noqa: E402
from regear.domain.event_policy import (  # noqa: E402
    RecoveryDirective,
    TopologyEvent,
    decide_topology_event,
)


class EventPolicyTests(unittest.TestCase):
    def test_unexpected_unplug_recovers_portable_and_never_sleeps(self):
        decision = decide_topology_event(
            event=TopologyEvent.EGPU_REMOVED,
            placement=PlacementState.DOCKED_EGPU,
            workflow=WorkflowState.IDLE,
        )
        self.assertEqual(
            decision.directives, (RecoveryDirective.RECOVER_PORTABLE,)
        )
        self.assertEqual(decision.reason_code, "egpu.removed_unexpected_recover")

    def test_sleep_pending_removal_only_starts_portable_recovery(self):
        decision = decide_topology_event(
            event=TopologyEvent.EGPU_REMOVED,
            placement=PlacementState.DOCKED_EGPU,
            workflow=WorkflowState.SLEEP_PENDING_DISCONNECT,
        )
        self.assertEqual(
            decision.directives,
            (RecoveryDirective.RECOVER_PORTABLE,),
        )
        self.assertEqual(decision.next_workflow, WorkflowState.RETURNING_TO_PORTABLE)
        self.assertEqual(
            decision.reason_code,
            "egpu.removed_sleep_pending_recover",
        )

    def test_raw_removal_event_never_authorizes_sleep_for_any_workflow(self):
        for workflow in WorkflowState:
            with self.subTest(workflow=workflow):
                decision = decide_topology_event(
                    event=TopologyEvent.EGPU_REMOVED,
                    placement=PlacementState.DOCKED_EGPU,
                    workflow=workflow,
                )
                self.assertEqual(
                    decision.directives,
                    (RecoveryDirective.RECOVER_PORTABLE,),
                )

    def test_duplicate_or_unverified_removal_does_not_guess_recovery(self):
        portable = decide_topology_event(
            event=TopologyEvent.EGPU_REMOVED,
            placement=PlacementState.PORTABLE,
            workflow=WorkflowState.IDLE,
        )
        self.assertEqual(
            portable.directives,
            (RecoveryDirective.OBSERVE_STABILITY,),
        )
        for placement in (PlacementState.UNKNOWN, PlacementState.DEGRADED):
            with self.subTest(placement=placement):
                unknown = decide_topology_event(
                    event=TopologyEvent.EGPU_REMOVED,
                    placement=placement,
                    workflow=WorkflowState.SLEEP_PENDING_DISCONNECT,
                )
                self.assertEqual(
                    unknown.directives,
                    (RecoveryDirective.ACTION_REQUIRED,),
                )

    def test_controller_loss_restores_builtin_only_when_verified_available(self):
        restored = decide_topology_event(
            event=TopologyEvent.EXTERNAL_CONTROLLER_LOST,
            placement=PlacementState.DOCKED_EGPU,
            workflow=WorkflowState.IDLE,
            builtin_controller_available=True,
        )
        self.assertEqual(
            restored.directives, (RecoveryDirective.RESTORE_BUILTIN_CONTROLLER,)
        )
        unknown = decide_topology_event(
            event=TopologyEvent.EXTERNAL_CONTROLLER_LOST,
            placement=PlacementState.DOCKED_EGPU,
            workflow=WorkflowState.IDLE,
            builtin_controller_available=None,
        )
        self.assertEqual(unknown.next_workflow, WorkflowState.ACTION_REQUIRED)

    def test_external_display_loss_recovers_from_both_docked_placements(self):
        for placement in (PlacementState.DOCKED_IGPU, PlacementState.DOCKED_EGPU):
            with self.subTest(placement=placement):
                decision = decide_topology_event(
                    event=TopologyEvent.EXTERNAL_DISPLAY_LOST,
                    placement=placement,
                    workflow=WorkflowState.IDLE,
                )
                self.assertEqual(
                    decision.directives, (RecoveryDirective.RECOVER_PORTABLE,)
                )


if __name__ == "__main__":
    unittest.main()
