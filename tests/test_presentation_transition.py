from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.adapters.presentation_transition import (  # noqa: E402
    PresentationTransitionMechanism,
)
from hdm.adapters.steamos.commands import UserServiceOperation  # noqa: E402
from hdm.adapters.steamos.gamescope_user import (  # noqa: E402
    GamescopeUserContext,
    GamescopeUserResolution,
)
from hdm.domain.control_plane import (  # noqa: E402
    PlacementState,
    PlannedStep,
    TransitionBinding,
    TransitionStepCode,
)
from hdm.domain.serialization import snapshot_from_dict  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"
BOOT_ID = "12345678-1234-1234-1234-123456789abc"


def observed(name="connected-internal.json"):
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    old_ids = {gpu["stable_id"] for gpu in value["gpus"] if gpu["role"] == "external"}
    for gpu in value["gpus"]:
        if gpu["role"] == "external":
            gpu["stable_id"] = "gpd-g1:0123456789abcdef"
    if value["gamescope"].get("render_gpu_stable_id") in old_ids:
        value["gamescope"]["render_gpu_stable_id"] = "gpd-g1:0123456789abcdef"
    return snapshot_from_dict(value)


def observed_docked_igpu():
    value = json.loads((FIXTURES / "tv-docked.json").read_text(encoding="utf-8"))
    for gpu in value["gpus"]:
        gpu["selected_for_render"] = gpu["role"] == "internal"
        if gpu["role"] == "external":
            gpu["stable_id"] = "gpd-g1:0123456789abcdef"
    for display in value["displays"]:
        display["active"] = display["kind"] == "external"
    value["gamescope"]["render_gpu_stable_id"] = "internal-gpu"
    value["gamescope"]["render_vendor_device"] = "1002:0000"
    value["gamescope"]["output_order"] = ["HDMI-A-1"]
    return snapshot_from_dict(value)


def binding():
    return TransitionBinding(
        "asus-rog-ally-x",
        "gpd-g1-rx7600mxt-titan-ridge",
        "gpd-g1:0123456789abcdef",
        "internal-gpu",
        "gpd-g1:0123456789abcdef",
        "internal-panel",
        "external-tv",
    )


USER = GamescopeUserContext(
    "deck",
    1000,
    1000,
    Path("/home/deck"),
    Path("/run/user/1000"),
    Path("/run/user/1000/bus"),
)


class FakeIntegration:
    def __init__(self, *, ready=True, user=USER, events=None):
        self.user = user
        self.ready = ready
        self.events = events if events is not None else []

    def status(self):
        self.events.append("integration.status")
        return SimpleNamespace(ready=self.ready)


class FakeConfig:
    def __init__(self, events, fail_on_call=0):
        self.events = events
        self.targets = []
        self.fail_on_call = fail_on_call

    def write_target(self, **values):
        self.targets.append(values["target"])
        self.events.append(f"config.{values['target'].value}")
        if self.fail_on_call == len(self.targets):
            raise OSError("injected private config failure")


class FakeCommands:
    def __init__(self, events, fail=()):
        self.events = events
        self.fail = set(fail)

    def run(self, operation, **identity):
        self.events.append(f"command.{operation.value}")
        return SimpleNamespace(ok=operation not in self.fail)


class FakeAudio:
    def __init__(self, events, *, fail=False, rollback=True):
        self.events = events
        self.fail = fail
        self.rollback_ok = rollback

    def prepare_docked(self, user):
        self.events.append("audio.prepare")
        return SimpleNamespace(succeeded=True, code="audio.rollback_prepared")

    def switch(self, target, user):
        self.events.append(f"audio.{target.value}")
        return SimpleNamespace(
            succeeded=not self.fail,
            code="audio.injected_failure" if self.fail else "audio.default_verified",
            receipt=SimpleNamespace(
                changed=True,
                previous_sink_name="portable",
                created_portable_state=True,
            ),
        )

    def rollback(self, receipt, user):
        self.events.append("audio.rollback")
        return self.rollback_ok


def mechanism(*, fail=(), ready=True, user=USER, resolved_user=USER, config_fail=0):
    events = []
    config = FakeConfig(events, config_fail)
    value = PresentationTransitionMechanism(
        integration=FakeIntegration(ready=ready, user=user, events=events),
        config=config,
        commands=FakeCommands(events, fail),
        resolve_user=lambda: GamescopeUserResolution(resolved_user),
        read_boot_id=lambda: BOOT_ID,
    )
    return value, config, events


class PresentationTransitionMechanismTests(unittest.TestCase):
    def test_audio_preparation_failure_prevents_config_and_restart(self):
        value, config, events = mechanism()
        value._audio = SimpleNamespace(prepare_docked=lambda _: SimpleNamespace(
            succeeded=False, code="audio.rollback_state_failed"))
        result = value.apply(
            PlannedStep(TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                        10_000, expected_placement=PlacementState.DOCKED_EGPU),
            binding(), observed(),
        )
        self.assertEqual(result.code, "audio.rollback_state_failed")
        self.assertEqual(config.targets, [])
        self.assertNotIn("command.restart_gamescope_session", events)

    def test_portable_recovery_restarts_and_verifies_audio_even_at_source(self):
        value, config, events = mechanism()
        value._audio = FakeAudio(events)
        result = value.recover(PlacementState.PORTABLE, binding(), observed())
        self.assertTrue(result.succeeded)
        self.assertIn("command.restart_gamescope_session", events)
        self.assertIn("audio.portable", events)
        value._audio = FakeAudio(events, fail=True)
        self.assertFalse(value.recover(PlacementState.PORTABLE, binding(), observed()).succeeded)

    def test_audio_is_verified_after_restart_is_durably_queued(self):
        events = []
        config = FakeConfig(events)
        value = PresentationTransitionMechanism(
            integration=FakeIntegration(events=events),
            config=config,
            commands=FakeCommands(events),
            resolve_user=lambda: GamescopeUserResolution(USER),
            read_boot_id=lambda: BOOT_ID,
            audio=FakeAudio(events),
        )
        result = value.apply(
            PlannedStep(
                TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                10_000,
                expected_placement=PlacementState.DOCKED_EGPU,
            ),
            binding(),
            observed(),
        )
        self.assertTrue(result.succeeded)
        self.assertLess(events.index("audio.prepare"), events.index("command.restart_gamescope_session"))
        self.assertGreater(
            events.index("audio.docked_egpu"),
            events.index("command.restart_gamescope_session"),
        )

    def test_restart_failure_does_not_change_audio(self):
        events = []
        config = FakeConfig(events)
        value = PresentationTransitionMechanism(
            integration=FakeIntegration(events=events),
            config=config,
            commands=FakeCommands(
                events, (UserServiceOperation.RESTART_GAMESCOPE_SESSION,)
            ),
            resolve_user=lambda: GamescopeUserResolution(USER),
            read_boot_id=lambda: BOOT_ID,
            audio=FakeAudio(events),
        )
        result = value.apply(
            PlannedStep(
                TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                10_000,
                expected_placement=PlacementState.DOCKED_EGPU,
            ),
            binding(),
            observed(),
        )
        self.assertEqual(result.code, "presentation.restart_failed")
        self.assertNotIn("audio.docked_egpu", events)

    def test_audio_failure_after_queued_restart_restores_source_config(self):
        events = []
        config = FakeConfig(events)
        value = PresentationTransitionMechanism(
            integration=FakeIntegration(events=events),
            config=config,
            commands=FakeCommands(events),
            resolve_user=lambda: GamescopeUserResolution(USER),
            read_boot_id=lambda: BOOT_ID,
            audio=FakeAudio(events, fail=True),
        )
        result = value.apply(
            PlannedStep(
                TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                10_000,
                expected_placement=PlacementState.DOCKED_EGPU,
            ),
            binding(),
            observed(),
        )
        self.assertEqual(result.code, "audio.injected_failure")
        self.assertEqual(
            config.targets, [PlacementState.DOCKED_EGPU, PlacementState.PORTABLE]
        )

    def test_apply_orders_reload_verify_config_and_restart(self):
        value, config, events = mechanism()
        result = value.apply(
            PlannedStep(
                TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                10_000,
                expected_placement=PlacementState.DOCKED_EGPU,
            ),
            binding(),
            observed(),
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.code, "presentation.restart_queued")
        self.assertEqual(config.targets, [PlacementState.DOCKED_EGPU])
        self.assertEqual(
            events,
            [
                "integration.status",
                "command.daemon_reload",
                "command.verify_gamescope_unit",
                "config.docked_egpu",
                "command.restart_gamescope_session",
            ],
        )

    def test_restart_failure_restores_current_config_without_second_restart(self):
        value, config, events = mechanism(
            fail=(UserServiceOperation.RESTART_GAMESCOPE_SESSION,)
        )
        result = value.apply(
            PlannedStep(
                TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                10_000,
                expected_placement=PlacementState.DOCKED_EGPU,
            ),
            binding(),
            observed(),
        )
        self.assertFalse(result.succeeded)
        self.assertEqual(result.code, "presentation.restart_failed")
        self.assertEqual(
            config.targets,
            [PlacementState.DOCKED_EGPU, PlacementState.PORTABLE],
        )
        self.assertEqual(events.count("command.restart_gamescope_session"), 1)

    def test_config_rollback_failure_is_reported_separately(self):
        value, _, _ = mechanism(
            fail=(UserServiceOperation.RESTART_GAMESCOPE_SESSION,), config_fail=2
        )
        result = value.apply(
            PlannedStep(
                TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                10_000,
                expected_placement=PlacementState.DOCKED_EGPU,
            ),
            binding(),
            observed(),
        )
        self.assertEqual(result.code, "presentation.config_rollback_failed")

    def test_initial_config_failure_restores_current_safe_target(self):
        value, config, _ = mechanism(config_fail=1)
        result = value.apply(
            PlannedStep(
                TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                10_000,
                expected_placement=PlacementState.DOCKED_EGPU,
            ),
            binding(),
            observed(),
        )
        self.assertEqual(result.code, "presentation.config_failed")
        self.assertEqual(
            config.targets,
            [PlacementState.DOCKED_EGPU, PlacementState.PORTABLE],
        )

    def test_reload_and_unit_failure_stop_before_config(self):
        cases = (
            (UserServiceOperation.DAEMON_RELOAD, "presentation.daemon_reload_failed"),
            (
                UserServiceOperation.VERIFY_GAMESCOPE_UNIT,
                "presentation.unit_unavailable",
            ),
        )
        for operation, expected in cases:
            with self.subTest(operation=operation):
                value, config, events = mechanism(fail=(operation,))
                result = value.apply(
                    PlannedStep(
                        TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                        10_000,
                        expected_placement=PlacementState.DOCKED_EGPU,
                    ),
                    binding(),
                    observed(),
                )
                self.assertEqual(result.code, expected)
                self.assertEqual(config.targets, [])
                self.assertNotIn("command.restart_gamescope_session", events)

    def test_unready_integration_or_changed_user_never_reloads(self):
        other = GamescopeUserContext(
            "other",
            1001,
            1001,
            Path("/home/other"),
            Path("/run/user/1001"),
            Path("/run/user/1001/bus"),
        )
        for options, code in (
            ({"ready": False}, "presentation.integration_not_ready"),
            ({"resolved_user": other}, "presentation.user_changed"),
        ):
            with self.subTest(code=code):
                value, config, events = mechanism(**options)
                result = value.apply(
                    PlannedStep(
                        TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                        10_000,
                        expected_placement=PlacementState.DOCKED_EGPU,
                    ),
                    binding(),
                    observed(),
                )
                self.assertEqual(result.code, code)
                self.assertEqual(config.targets, [])
                self.assertFalse(any(item.startswith("command.") for item in events))

    def test_user_change_after_staging_restores_source_without_restart(self):
        other = GamescopeUserContext(
            "other",
            1001,
            1001,
            Path("/home/other"),
            Path("/run/user/1001"),
            Path("/run/user/1001/bus"),
        )
        resolutions = iter((USER, USER, other))
        events = []
        config = FakeConfig(events)
        value = PresentationTransitionMechanism(
            integration=FakeIntegration(user=USER, events=events),
            config=config,
            commands=FakeCommands(events),
            resolve_user=lambda: GamescopeUserResolution(next(resolutions)),
            read_boot_id=lambda: BOOT_ID,
        )
        result = value.apply(
            PlannedStep(
                TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                10_000,
                expected_placement=PlacementState.DOCKED_EGPU,
            ),
            binding(),
            observed(),
        )
        self.assertEqual(result.code, "presentation.user_changed")
        self.assertEqual(
            config.targets,
            [PlacementState.DOCKED_EGPU, PlacementState.PORTABLE],
        )
        self.assertNotIn("command.restart_gamescope_session", events)

    def test_interrupted_recovery_derives_exact_binding(self):
        value, config, _ = mechanism()
        result = value.recover(PlacementState.PORTABLE, None, observed())
        self.assertTrue(result.succeeded)
        self.assertEqual(result.code, "recovery.restart_queued")
        self.assertEqual(config.targets, [PlacementState.PORTABLE])

    def test_recovery_can_restore_docked_igpu_source(self):
        value, config, _ = mechanism()
        result = value.recover(
            PlacementState.DOCKED_IGPU, None, observed_docked_igpu()
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(result.code, "recovery.restart_queued")
        self.assertEqual(config.targets, [PlacementState.DOCKED_IGPU])

    def test_changed_binding_fails_before_integration_or_command(self):
        value, config, events = mechanism()
        changed = TransitionBinding(
            "asus-rog-ally-x",
            "gpd-g1-rx7600mxt-titan-ridge",
            "gpd-g1:different",
            "internal-gpu",
            "gpd-g1:different",
            "internal-panel",
            "external-tv",
        )
        result = value.recover(PlacementState.PORTABLE, changed, observed())
        self.assertEqual(result.code, "recovery.binding_changed")
        self.assertEqual(config.targets, [])
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
