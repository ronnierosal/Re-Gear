from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.control_plane import (  # noqa: E402
    CapabilitySupport,
    EgpuCapabilities,
    HostCapabilities,
    compose_capabilities,
)
from regear.domain.peripheral_handoff import (  # noqa: E402
    AudioDirective,
    AudioHandoffObservation,
    AudioOutput,
    ControllerDirective,
    ControllerHandoffObservation,
    ControllerHandoffPolicy,
    HandoffDirection,
    plan_audio_handoff,
    plan_controller_handoff,
)
from regear.profiles.ally_x import CAPABILITIES as ALLY_X  # noqa: E402
from regear.profiles.gpd_g1 import CAPABILITIES as GPD_G1  # noqa: E402


def capabilities(**host_changes):
    host = HostCapabilities(
        profile_id="test-host",
        audio_handoff=CapabilitySupport.VERIFIED,
        external_controller_promotion=CapabilitySupport.VERIFIED,
        internal_controller_suppression=CapabilitySupport.VERIFIED,
        external_controller_disconnect=CapabilitySupport.VERIFIED,
        external_controller_power_off=CapabilitySupport.VERIFIED,
    )
    return compose_capabilities(
        dataclasses.replace(host, **host_changes),
        EgpuCapabilities(
            profile_id="test-egpu",
            audio_output=CapabilitySupport.VERIFIED,
        ),
    )


def controller(**changes):
    return dataclasses.replace(
        ControllerHandoffObservation(
            builtin_available=True,
            builtin_input_verified=True,
            external_connected=True,
            external_input_verified=True,
            builtin_restore_verified=True,
        ),
        **changes,
    )


def audio(**changes):
    return dataclasses.replace(
        AudioHandoffObservation(
            current_output=AudioOutput.INTERNAL,
            current_output_usable_verified=True,
            external_output_available=True,
            external_output_verified=True,
            portable_output_available=True,
            portable_output_verified=True,
            rollback_output_verified=True,
        ),
        **changes,
    )


class ControllerHandoffTests(unittest.TestCase):
    def test_dock_promotes_external_and_suppresses_only_with_verified_recovery(self):
        promoted = plan_controller_handoff(
            HandoffDirection.DOCK,
            controller(),
            capabilities(),
            ControllerHandoffPolicy(suppress_builtin_when_docked=True),
        )
        self.assertEqual(
            promoted.directives,
            (
                ControllerDirective.PROMOTE_EXTERNAL,
                ControllerDirective.SUPPRESS_BUILTIN,
            ),
        )
        blocked = plan_controller_handoff(
            HandoffDirection.DOCK,
            controller(builtin_restore_verified=False),
            capabilities(),
            ControllerHandoffPolicy(suppress_builtin_when_docked=True),
        )
        self.assertEqual(blocked.directives, (ControllerDirective.PROMOTE_EXTERNAL,))
        self.assertEqual(
            blocked.blockers,
            ("controller.suppression_recovery_unverified",),
        )

    def test_dock_without_external_keeps_verified_builtin_active(self):
        decision = plan_controller_handoff(
            HandoffDirection.DOCK,
            controller(external_connected=False, external_input_verified=False),
            capabilities(),
        )
        self.assertEqual(decision.directives, (ControllerDirective.KEEP_CURRENT,))

    def test_undock_or_controller_loss_restores_builtin_first(self):
        for direction in (
            HandoffDirection.UNDOCK,
            HandoffDirection.EXTERNAL_CONTROLLER_LOST,
        ):
            with self.subTest(direction=direction):
                decision = plan_controller_handoff(
                    direction,
                    controller(),
                    capabilities(),
                )
                self.assertEqual(
                    decision.directives[:2],
                    (
                        ControllerDirective.RESTORE_BUILTIN,
                        ControllerDirective.PROMOTE_BUILTIN,
                    ),
                )

    def test_optional_power_off_falls_back_only_to_verified_disconnect(self):
        policy = ControllerHandoffPolicy(
            disconnect_external_when_undocked=True,
            power_off_external_when_undocked=True,
        )
        powered = plan_controller_handoff(
            HandoffDirection.UNDOCK, controller(), capabilities(), policy
        )
        self.assertIn(ControllerDirective.POWER_OFF_EXTERNAL, powered.directives)
        disconnected = plan_controller_handoff(
            HandoffDirection.UNDOCK,
            controller(),
            capabilities(external_controller_power_off=CapabilitySupport.UNKNOWN),
            policy,
        )
        self.assertIn(ControllerDirective.DISCONNECT_EXTERNAL, disconnected.directives)
        unsupported = plan_controller_handoff(
            HandoffDirection.UNDOCK,
            controller(),
            capabilities(
                external_controller_power_off=CapabilitySupport.UNKNOWN,
                external_controller_disconnect=CapabilitySupport.UNKNOWN,
            ),
            policy,
        )
        self.assertNotIn(ControllerDirective.POWER_OFF_EXTERNAL, unsupported.directives)
        self.assertNotIn(ControllerDirective.DISCONNECT_EXTERNAL, unsupported.directives)
        self.assertIn(
            "capability.external_controller_power_off_unverified",
            unsupported.blockers,
        )
        self.assertIn(
            "capability.external_controller_disconnect_unverified",
            unsupported.blockers,
        )

    def test_real_profile_never_promotes_or_suppresses_controller(self):
        decision = plan_controller_handoff(
            HandoffDirection.DOCK,
            controller(),
            compose_capabilities(ALLY_X, GPD_G1),
            ControllerHandoffPolicy(suppress_builtin_when_docked=True),
        )
        self.assertEqual(decision.directives, (ControllerDirective.ACTION_REQUIRED,))


class AudioHandoffTests(unittest.TestCase):
    def test_verified_dock_and_undock_select_expected_outputs(self):
        dock = plan_audio_handoff(HandoffDirection.DOCK, audio(), capabilities())
        undock = plan_audio_handoff(HandoffDirection.UNDOCK, audio(), capabilities())
        self.assertEqual(dock.directives, (AudioDirective.SELECT_EXTERNAL,))
        self.assertEqual(undock.directives, (AudioDirective.RESTORE_PORTABLE,))

    def test_missing_external_audio_preserves_current_verified_output(self):
        decision = plan_audio_handoff(
            HandoffDirection.DOCK,
            audio(external_output_available=False, external_output_verified=False),
            capabilities(),
        )
        self.assertEqual(decision.directives, (AudioDirective.KEEP_CURRENT,))
        self.assertTrue(decision.blockers)

    def test_unverified_rollback_or_portable_output_fails_closed(self):
        rollback = plan_audio_handoff(
            HandoffDirection.DOCK,
            audio(rollback_output_verified=False),
            capabilities(),
        )
        self.assertIn(AudioDirective.ACTION_REQUIRED, rollback.directives)
        portable = plan_audio_handoff(
            HandoffDirection.UNDOCK,
            audio(portable_output_verified=False),
            capabilities(),
        )
        self.assertIn(AudioDirective.ACTION_REQUIRED, portable.directives)

    def test_real_profile_keeps_current_audio_and_reports_unverified_capability(self):
        decision = plan_audio_handoff(
            HandoffDirection.DOCK,
            audio(),
            compose_capabilities(ALLY_X, GPD_G1),
        )
        self.assertEqual(
            decision.directives,
            (AudioDirective.KEEP_CURRENT, AudioDirective.ACTION_REQUIRED),
        )


if __name__ == "__main__":
    unittest.main()
