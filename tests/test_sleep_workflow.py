from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.control_plane import (  # noqa: E402
    CapabilitySupport,
    EgpuCapabilities,
    HostCapabilities,
    PlacementState,
    RemovalBehavior,
    SleepBehavior,
    compose_capabilities,
)
from regear.domain.game_compatibility import GameSaveCapability  # noqa: E402
from regear.domain.models import (  # noqa: E402
    EgpuClientKind,
    EgpuClientObservation,
    EgpuPresence,
    EgpuResourceKind,
    GameState,
)
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.domain.sleep_workflow import (  # noqa: E402
    SleepDirective,
    SleepFlowEvent,
    SleepFlowStage,
    SleepWorkflowContext,
    advance_sleep_flow,
    start_sleep_flow,
)
from regear.profiles.ally_x import CAPABILITIES as ALLY_X  # noqa: E402
from regear.profiles.gpd_g1 import CAPABILITIES as GPD_G1  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def readiness(*clients, applicable=True, complete=True):
    value = json.loads((FIXTURES / "portable.json").read_text(encoding="utf-8"))
    snapshot = snapshot_from_dict(value)
    return dataclasses.replace(
        snapshot.disconnect_readiness,
        applicable=applicable,
        scan_complete=complete,
        ready=complete and not clients,
        egpu_stable_id="gpd-g1:ephemeral" if applicable else "",
        clients=tuple(clients),
    )


def context(
    *,
    presence=EgpuPresence.PRESENT,
    capabilities=None,
    game_state=GameState.IDLE,
    save=GameSaveCapability.UNTESTED,
    disconnect=None,
    placement=PlacementState.DOCKED_EGPU,
    identity=True,
    removal_ready=False,
):
    return SleepWorkflowContext(
        egpu_presence=presence,
        exact_egpu_identity_verified=identity,
        capabilities=capabilities or compose_capabilities(ALLY_X, GPD_G1),
        game_state=game_state,
        save_capability=save,
        disconnect_readiness=disconnect or readiness(),
        placement=placement,
        removal_readiness_verified=removal_ready,
    )


def live_removal_capabilities(sleep_behavior=SleepBehavior.SLEEP_UNRELIABLE):
    return compose_capabilities(
        HostCapabilities(
            "test-host",
            egpu_support=CapabilitySupport.VERIFIED,
            display_handoff=CapabilitySupport.VERIFIED,
        ),
        EgpuCapabilities(
            "test-egpu",
            display_output=CapabilitySupport.VERIFIED,
            sleep_behavior=sleep_behavior,
            removal_behavior=RemovalBehavior.LIVE_REMOVAL_VERIFIED,
        ),
    )


def user_client():
    return EgpuClientObservation(
        "instance-1",
        100,
        "test-client",
        EgpuClientKind.USER,
        (EgpuResourceKind.DRM_RENDER,),
        True,
        "test fixture",
    )


def protected_client():
    return dataclasses.replace(
        user_client(),
        kind=EgpuClientKind.PROTECTED,
        close_eligible=False,
    )


class SleepWorkflowTests(unittest.TestCase):
    def test_absent_or_verified_sleep_safe_egpu_keeps_normal_sleep(self):
        absent = start_sleep_flow(
            "sleep-request-1", context(presence=EgpuPresence.ABSENT)
        )
        self.assertEqual(absent.stage, SleepFlowStage.NORMAL_SLEEP_ALLOWED)
        sleep_safe = start_sleep_flow(
            "sleep-request-2",
            context(
                capabilities=live_removal_capabilities(
                    SleepBehavior.SLEEP_SAFE_VERIFIED
                )
            ),
        )
        self.assertEqual(sleep_safe.stage, SleepFlowStage.NORMAL_SLEEP_ALLOWED)

    def test_unknown_presence_identity_or_game_fails_closed(self):
        cases = (
            context(presence=EgpuPresence.UNKNOWN),
            context(identity=False),
            context(game_state=GameState.UNKNOWN),
        )
        for index, value in enumerate(cases):
            with self.subTest(index=index):
                flow = start_sleep_flow(f"sleep-request-{index}", value)
                self.assertEqual(flow.stage, SleepFlowStage.ACTION_REQUIRED)
                self.assertIn(SleepDirective.KEEP_AWAKE, flow.directives)

    def test_current_g1_never_claims_safe_live_disconnect(self):
        flow = start_sleep_flow("sleep-request-g1", context())
        self.assertEqual(flow.stage, SleepFlowStage.SHUTDOWN_REQUIRED)
        self.assertIn(SleepDirective.SHUTDOWN_BEFORE_DISCONNECT, flow.directives)
        self.assertNotIn(SleepDirective.SHOW_SAFE_TO_DISCONNECT, flow.directives)
        self.assertFalse(flow.original_request_pending)

    def test_game_consent_and_save_warning_are_mandatory(self):
        initial = start_sleep_flow(
            "sleep-request-game",
            context(
                game_state=GameState.RUNNING,
                save=GameSaveCapability.MANUAL_SAVE_REQUIRED,
            ),
        )
        self.assertEqual(initial.stage, SleepFlowStage.AWAITING_GAME_CONSENT)
        self.assertIn(SleepDirective.WARN_SAVE_UNVERIFIED, initial.directives)
        denied = advance_sleep_flow(
            initial,
            SleepFlowEvent.GAME_CONSENT_DENIED,
            context(game_state=GameState.RUNNING),
        )
        self.assertEqual(denied.stage, SleepFlowStage.CANCELLED)
        self.assertFalse(denied.original_request_pending)

    def test_verified_autosave_is_attempted_only_after_consent(self):
        value = context(
            game_state=GameState.RUNNING,
            save=GameSaveCapability.VERIFIED_TRIGGERABLE_AUTOSAVE,
        )
        initial = start_sleep_flow("sleep-request-save", value)
        self.assertNotIn(SleepDirective.ATTEMPT_VERIFIED_SAVE, initial.directives)
        closing = advance_sleep_flow(
            initial, SleepFlowEvent.GAME_CONSENT_GRANTED, value
        )
        self.assertIn(SleepDirective.ATTEMPT_VERIFIED_SAVE, closing.directives)
        self.assertIn(SleepDirective.CLOSE_GAME_GRACEFULLY, closing.directives)

    def test_consent_cannot_upgrade_unverified_save_capability(self):
        initial = start_sleep_flow(
            "sleep-request-bound-save",
            context(
                game_state=GameState.RUNNING,
                save=GameSaveCapability.UNTESTED,
            ),
        )
        closing = advance_sleep_flow(
            initial,
            SleepFlowEvent.GAME_CONSENT_GRANTED,
            context(
                game_state=GameState.RUNNING,
                save=GameSaveCapability.VERIFIED_TRIGGERABLE_AUTOSAVE,
            ),
        )
        self.assertNotIn(SleepDirective.ATTEMPT_VERIFIED_SAVE, closing.directives)
        self.assertIn(SleepDirective.CLOSE_GAME_GRACEFULLY, closing.directives)

    def test_game_exit_then_user_client_routes_to_release_preview(self):
        initial = start_sleep_flow(
            "sleep-request-release", context(game_state=GameState.RUNNING)
        )
        closing = advance_sleep_flow(
            initial,
            SleepFlowEvent.GAME_CONSENT_GRANTED,
            context(game_state=GameState.RUNNING),
        )
        releasing = advance_sleep_flow(
            closing,
            SleepFlowEvent.GAME_EXIT_VERIFIED,
            context(game_state=GameState.IDLE, disconnect=readiness(user_client())),
        )
        self.assertEqual(releasing.stage, SleepFlowStage.RELEASING_CLIENTS)
        self.assertIn(SleepDirective.PREVIEW_PROCESS_RELEASE, releasing.directives)

    def test_protected_client_stops_the_workflow(self):
        flow = start_sleep_flow(
            "sleep-request-protected",
            context(disconnect=readiness(protected_client())),
        )
        self.assertEqual(flow.stage, SleepFlowStage.ACTION_REQUIRED)
        self.assertEqual(flow.reason_code, "disconnect.protected_client")

    def test_live_removal_requires_portable_recovery_before_original_sleep(self):
        capabilities = live_removal_capabilities()
        waiting = start_sleep_flow(
            "sleep-request-live",
            context(capabilities=capabilities, removal_ready=True),
        )
        self.assertEqual(waiting.stage, SleepFlowStage.AWAITING_DISCONNECT)
        self.assertIn(SleepDirective.SHOW_SAFE_TO_DISCONNECT, waiting.directives)

        restoring = advance_sleep_flow(
            waiting,
            SleepFlowEvent.EGPU_REMOVAL_VERIFIED,
            context(
                presence=EgpuPresence.ABSENT,
                capabilities=capabilities,
                placement=PlacementState.UNKNOWN,
                removal_ready=True,
            ),
        )
        self.assertEqual(restoring.stage, SleepFlowStage.RESTORING_PORTABLE)
        self.assertNotIn(SleepDirective.CONTINUE_ORIGINAL_SLEEP, restoring.directives)

        ready = advance_sleep_flow(
            restoring,
            SleepFlowEvent.PORTABLE_RECOVERY_VERIFIED,
            context(
                presence=EgpuPresence.ABSENT,
                capabilities=capabilities,
                placement=PlacementState.PORTABLE,
                removal_ready=True,
            ),
        )
        self.assertEqual(ready.stage, SleepFlowStage.READY_TO_CONTINUE_SLEEP)
        self.assertEqual(
            ready.directives, (SleepDirective.CONTINUE_ORIGINAL_SLEEP,)
        )
        complete = advance_sleep_flow(
            ready,
            SleepFlowEvent.ORIGINAL_SLEEP_CONTINUED,
            context(
                presence=EgpuPresence.ABSENT,
                capabilities=capabilities,
                placement=PlacementState.PORTABLE,
                removal_ready=True,
            ),
        )
        self.assertEqual(complete.stage, SleepFlowStage.COMPLETED)
        self.assertFalse(complete.original_request_pending)

    def test_live_removal_capability_alone_cannot_show_safe_to_disconnect(self):
        flow = start_sleep_flow(
            "sleep-request-proof",
            context(capabilities=live_removal_capabilities(), removal_ready=False),
        )
        self.assertEqual(flow.stage, SleepFlowStage.ACTION_REQUIRED)
        self.assertEqual(
            flow.reason_code, "disconnect.removal_readiness_unverified"
        )
        self.assertNotIn(SleepDirective.SHOW_SAFE_TO_DISCONNECT, flow.directives)

    def test_original_sleep_request_expires_fail_closed(self):
        capabilities = live_removal_capabilities()
        waiting = start_sleep_flow(
            "sleep-request-expiry",
            context(capabilities=capabilities, removal_ready=True),
            now_ms=100,
            request_ttl_ms=500,
        )
        expired = advance_sleep_flow(
            waiting,
            SleepFlowEvent.EGPU_REMOVAL_VERIFIED,
            context(
                presence=EgpuPresence.ABSENT,
                capabilities=capabilities,
                removal_ready=True,
            ),
            now_ms=601,
        )
        self.assertEqual(expired.stage, SleepFlowStage.CANCELLED)
        self.assertEqual(expired.reason_code, "sleep.request_expired")
        self.assertFalse(expired.original_request_pending)

    def test_game_start_race_after_client_release_fails_closed(self):
        capabilities = live_removal_capabilities()
        releasing = start_sleep_flow(
            "sleep-request-race",
            context(
                capabilities=capabilities,
                disconnect=readiness(user_client()),
            ),
        )
        raced = advance_sleep_flow(
            releasing,
            SleepFlowEvent.SOFTWARE_CLIENTS_RELEASED,
            context(
                capabilities=capabilities,
                game_state=GameState.RUNNING,
                removal_ready=True,
            ),
        )
        self.assertEqual(raced.stage, SleepFlowStage.ACTION_REQUIRED)
        self.assertEqual(raced.reason_code, "game.started_during_disconnect")
        self.assertNotIn(SleepDirective.SHOW_SAFE_TO_DISCONNECT, raced.directives)

    def test_out_of_order_event_never_continues_sleep(self):
        flow = start_sleep_flow("sleep-request-order", context())
        invalid = advance_sleep_flow(
            flow,
            SleepFlowEvent.ORIGINAL_SLEEP_CONTINUED,
            context(),
        )
        self.assertEqual(invalid.stage, SleepFlowStage.ACTION_REQUIRED)
        self.assertNotIn(SleepDirective.CONTINUE_ORIGINAL_SLEEP, invalid.directives)
        self.assertFalse(invalid.original_request_pending)


if __name__ == "__main__":
    unittest.main()
