import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.auto_tdp import AutoTdpPolicy  # noqa: E402
from regear.domain.power_modes import (  # noqa: E402
    LastVerifiedPowerReceipt,
    PassivePowerEvent,
    PowerMode,
    PowerModePhase,
    PowerModePreference,
    PowerModeRequest,
    PowerModeState,
    PowerRequestKind,
    RestorationBaseline,
    explicit_power_request,
    observe_passive_power_event,
)


class PowerModeIntentTests(unittest.TestCase):
    def test_all_power_intentions_are_distinct_from_graphics_profiles(self):
        self.assertEqual(
            set(PowerMode),
            {
                PowerMode.BATTERY_SAVER,
                PowerMode.BALANCED,
                PowerMode.PERFORMANCE,
                PowerMode.AUTO,
                PowerMode.SYSTEM_CONTROL,
            },
        )
        self.assertNotIn("quality", {mode.value for mode in PowerMode})

    def test_auto_preference_requires_validated_policy_but_never_starts_it(self):
        policy = AutoTdpPolicy(7, 18, 40)
        preference = PowerModePreference(PowerMode.AUTO, policy)
        request = explicit_power_request(preference, observed_generation=4)
        self.assertIs(request.requested_mode, PowerMode.AUTO)
        self.assertEqual(request.observed_generation, 4)
        self.assertFalse(preference.authorizes_activation)
        self.assertFalse(request.authorizes_activation)
        with self.assertRaises(ValueError):
            PowerModePreference(PowerMode.AUTO)
        with self.assertRaises(ValueError):
            PowerModePreference(PowerMode.BALANCED, policy)

    def test_manual_and_system_preferences_have_no_hidden_watt_target(self):
        for mode in (
            PowerMode.BATTERY_SAVER,
            PowerMode.BALANCED,
            PowerMode.PERFORMANCE,
            PowerMode.SYSTEM_CONTROL,
        ):
            with self.subTest(mode=mode):
                value = PowerModePreference(mode)
                self.assertFalse(value.authorizes_activation)
                self.assertFalse(hasattr(value, "watts"))

    def test_stop_disable_and_restore_are_separate_explicit_requests(self):
        kinds = (
            PowerRequestKind.STOP_AUTO_KEEP_LIMIT,
            PowerRequestKind.DISABLE_REGEAR_CONDITIONAL_RESTORE,
            PowerRequestKind.RESTORE_PREVIOUS,
        )
        requests = tuple(PowerModeRequest(kind, 9) for kind in kinds)
        self.assertEqual(tuple(item.kind for item in requests), kinds)
        self.assertTrue(all(item.requested_mode is None for item in requests))
        self.assertTrue(all(not item.authorizes_activation for item in requests))
        with self.assertRaises(ValueError):
            PowerModeRequest(PowerRequestKind.RESTORE_PREVIOUS, 9, PowerMode.SYSTEM_CONTROL)

    def test_requests_reject_bool_zero_negative_and_wrong_mode_types(self):
        for generation in (True, 0, -1, 1.0):
            with self.subTest(generation=generation), self.assertRaises(ValueError):
                PowerModeRequest(PowerRequestKind.STOP_AUTO_KEEP_LIMIT, generation)
        with self.assertRaises(ValueError):
            PowerModeRequest(PowerRequestKind.ACTIVATE_SELECTED, 1)
        with self.assertRaises(ValueError):
            PowerModeRequest(PowerRequestKind.ACTIVATE_SELECTED, 1, "balanced")

    def test_persistence_refresh_resume_and_context_events_never_create_requests(self):
        state = PowerModeState(PowerMode.BALANCED, 3)
        for event in PassivePowerEvent:
            with self.subTest(event=event):
                update = observe_passive_power_event(
                    state,
                    event,
                    selected=PowerMode.AUTO if event is PassivePowerEvent.PREFERENCE_LOADED else None,
                    new_generation=(4 if event in {
                        PassivePowerEvent.RESUMED,
                        PassivePowerEvent.CONTEXT_CHANGED,
                    } else None),
                )
                self.assertIsNone(update.request)
                self.assertFalse(update.authorizes_activation)
                self.assertIsNone(update.state.requested)
                self.assertIsNone(update.state.observed_effective)
                self.assertIsNone(update.state.verified_effective)

    def test_resume_and_context_change_invalidate_current_verified_claim(self):
        baseline = RestorationBaseline(6, 13, "original")
        receipt = LastVerifiedPowerReceipt("verified-6", 6, PowerMode.BALANCED, 15)
        state = PowerModeState(
            PowerMode.AUTO,
            6,
            phase=PowerModePhase.ACTIVE,
            requested=PowerMode.AUTO,
            observed_effective=PowerMode.BALANCED,
            verified_effective=PowerMode.BALANCED,
            configured_limit_watts=15,
            measured_package_watts=12.5,
            last_verified=receipt,
            restoration_baseline=baseline,
        )
        for event in (PassivePowerEvent.RESUMED, PassivePowerEvent.CONTEXT_CHANGED):
            with self.subTest(event=event):
                update = observe_passive_power_event(state, event, new_generation=7)
                self.assertEqual(update.state.generation, 7)
                self.assertIs(update.state.phase, PowerModePhase.PAUSED)
                self.assertIs(update.state.selected, PowerMode.AUTO)
                self.assertIs(update.state.requested, PowerMode.AUTO)
                self.assertIsNone(update.state.observed_effective)
                self.assertIsNone(update.state.verified_effective)
                self.assertIsNone(update.state.last_verified)
                self.assertEqual(update.state.restoration_baseline, baseline)
                self.assertIsNone(update.request)

    def test_passive_generation_change_is_strict_and_context_bound(self):
        state = PowerModeState(PowerMode.BALANCED, 3)
        for generation in (None, True, 0, 3, 2, 3.5):
            with self.subTest(generation=generation), self.assertRaises(ValueError):
                observe_passive_power_event(
                    state,
                    PassivePowerEvent.CONTEXT_CHANGED,
                    new_generation=generation,
                )
        with self.assertRaises(ValueError):
            observe_passive_power_event(
                state,
                PassivePowerEvent.MENU_REFRESHED,
                new_generation=4,
            )


class PowerModeStateTests(unittest.TestCase):
    def test_requested_effective_configured_and_measured_values_are_separate(self):
        receipt = LastVerifiedPowerReceipt("write-8", 8, PowerMode.BALANCED, 15)
        state = PowerModeState(
            selected=PowerMode.AUTO,
            generation=8,
            phase=PowerModePhase.PAUSED,
            requested=PowerMode.AUTO,
            observed_effective=PowerMode.BALANCED,
            verified_effective=PowerMode.BALANCED,
            configured_limit_watts=15,
            measured_package_watts=11.25,
            last_verified=receipt,
            reason="Auto unavailable",
        )
        self.assertIs(state.selected, PowerMode.AUTO)
        self.assertIs(state.requested, PowerMode.AUTO)
        self.assertIs(state.observed_effective, PowerMode.BALANCED)
        self.assertIs(state.verified_effective, PowerMode.BALANCED)
        self.assertEqual(state.configured_limit_watts, 15)
        self.assertEqual(state.measured_package_watts, 11.25)
        self.assertFalse(state.authorizes_activation)

    def test_failed_or_partial_application_is_unknown_recovery_not_effective(self):
        baseline = RestorationBaseline(4, 13, "initial-readback")
        receipt = LastVerifiedPowerReceipt("last-good", 4, PowerMode.BALANCED, 15)
        state = PowerModeState(
            PowerMode.PERFORMANCE,
            5,
            phase=PowerModePhase.RECOVERY,
            requested=PowerMode.PERFORMANCE,
            observed_effective=PowerMode.PERFORMANCE,
            verified_effective=None,
            configured_limit_watts=15,
            last_verified=receipt,
            restoration_baseline=baseline,
            reason="write outcome unknown",
        )
        self.assertIs(state.observed_effective, PowerMode.PERFORMANCE)
        self.assertIsNone(state.verified_effective)
        self.assertEqual(state.last_verified, receipt)
        self.assertEqual(state.restoration_baseline, baseline)
        with self.assertRaises(ValueError):
            PowerModeState(
                PowerMode.PERFORMANCE,
                5,
                phase=PowerModePhase.RECOVERY,
                verified_effective=PowerMode.PERFORMANCE,
                last_verified=receipt,
            )

    def test_verified_effective_mode_requires_matching_receipt(self):
        with self.assertRaises(ValueError):
            PowerModeState(
                PowerMode.BALANCED,
                2,
                verified_effective=PowerMode.BALANCED,
            )
        with self.assertRaises(ValueError):
            PowerModeState(
                PowerMode.PERFORMANCE,
                2,
                verified_effective=PowerMode.PERFORMANCE,
                last_verified=LastVerifiedPowerReceipt(
                    "balanced", 2, PowerMode.BALANCED, 15
                ),
            )

    def test_receipts_and_baselines_cannot_claim_future_generation(self):
        receipt = LastVerifiedPowerReceipt("future", 3, PowerMode.BALANCED, 15)
        baseline = RestorationBaseline(3, 12, "future-baseline")
        with self.assertRaises(ValueError):
            PowerModeState(PowerMode.BALANCED, 2, last_verified=receipt)
        with self.assertRaises(ValueError):
            PowerModeState(PowerMode.BALANCED, 2, restoration_baseline=baseline)
        with self.assertRaises(ValueError):
            PowerModeState(
                PowerMode.BALANCED,
                4,
                verified_effective=PowerMode.BALANCED,
                last_verified=receipt,
            )

    def test_numeric_readbacks_reject_bool_nonfinite_zero_and_negative(self):
        for value in (True, 0, -1, 2.5):
            with self.subTest(configured=value), self.assertRaises(ValueError):
                PowerModeState(PowerMode.BALANCED, 1, configured_limit_watts=value)
        for value in (True, 0, -1.0, float("nan"), float("inf")):
            with self.subTest(measured=value), self.assertRaises(ValueError):
                PowerModeState(PowerMode.BALANCED, 1, measured_package_watts=value)

    def test_contracts_are_immutable(self):
        state = PowerModeState(PowerMode.BALANCED, 1)
        with self.assertRaises(FrozenInstanceError):
            state.selected = PowerMode.PERFORMANCE


if __name__ == "__main__":
    unittest.main()
