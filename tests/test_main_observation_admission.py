"""Production entry points must refuse unsupported-host effects before composition."""

import asyncio
import inspect
import threading
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from tests.test_main_process_delivery import load_main_module
from regear.adapters.steamos.host import HostRecord
from regear.delivery import build_profile_config
from regear.delivery.observation_admission import ObservationDenied
from regear.delivery.observation_admission import observation_plugin


class InterceptorProvenanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_snapshot_dispatch_paths_report_literal_constructor_provenance(self):
        ally = HostRecord("ASUSTeK COMPUTER INC.", "ROG Ally X RC72LA", "RC72LA")
        mini = HostRecord("GPD", "G1617-01", "unknown")

        class Producer:
            def __init__(self):
                self.composed = True
                self._api = NS(get_snapshot_report=lambda: None)
                self._build_info = {}

            async def get_snapshot(self):
                return {"snapshot": {"schema_version": 3}, "normal_producer": True}

        def payload(_):
            return {"diagnostics": {}, "snapshot": {
                "sleep_guard": {}, "disconnect_readiness": {"ready": True}}}

        for profile in ("development", "production"):
            with self.subTest(profile=profile), patch.object(build_profile_config, "BUILD_PROFILE", profile):
                guarded = observation_plugin(Producer, passive_api=lambda: NS(get_snapshot_report=lambda: None),
                                             build_info=lambda: {}, render_snapshot=payload)
                for initial, expected in ((mini, "observation-only"), (ally, "supported-runtime")):
                    with patch("regear.adapters.steamos.host.HostDiscovery.scan", return_value=initial):
                        plugin = guarded()
                        result = await plugin.get_snapshot()
                    self.assertEqual(1, result["runtime_admission"]["schema_version"])
                    self.assertEqual(expected, result["runtime_admission"]["sleep_interceptor_admission"])
                    with patch("regear.adapters.steamos.host.HostDiscovery.scan", return_value=mini):
                        lost_evidence = await plugin.get_snapshot()
                    self.assertEqual(expected, lost_evidence["runtime_admission"]["sleep_interceptor_admission"])
                    if initial is mini:
                        self.assertNotIn("composed", plugin.__dict__)

    async def test_missing_or_nonliteral_constructor_provenance_never_grants_retirement(self):
        from regear.delivery.observation_admission import interceptor_admission
        for value in (None, 0, 1, "true", "false"):
            plugin = NS(_observation_started=value)
            self.assertEqual({}, interceptor_admission(plugin, {}))


class ObservationAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def plugin(self, profile):
        with patch.object(build_profile_config, "BUILD_PROFILE", profile):
            module = load_main_module(real_dock_gate=True, real_host_admission=True)
        plugin = module.Plugin.__new__(module.Plugin)
        plugin._unloading = False
        plugin._background_operations = set()
        plugin._retiring_tasks = set()
        plugin._tdp_closing = threading.Event()
        return module, plugin

    async def test_unknown_host_confirmation_never_reaches_authorization(self):
        for profile in ("development", "production"):
            with self.subTest(profile=profile), patch(
                "regear.adapters.steamos.host.HostDiscovery.scan",
                return_value=HostRecord("GPD", "G1617-01", "unknown"),
            ):
                module, plugin = self.plugin(profile)
                plugin._device_authorization = Mock()
                plugin._device_authorization.confirm.return_value = {"requested": True}
                await plugin.confirm_device_authorization("a" * 32, True, "authorize")
                plugin._device_authorization.confirm.assert_not_called()

    async def test_unknown_host_tdp_status_never_constructs_runtime(self):
        for profile in ("development", "production"):
            with self.subTest(profile=profile), patch(
                "regear.adapters.steamos.host.HostDiscovery.scan",
                return_value=HostRecord("", "", ""),
            ):
                module, plugin = self.plugin(profile)
                plugin._tdp_service = Mock()
                plugin._tdp_service.return_value.status.return_value = {"code": "tdp.disabled"}
                await plugin.get_tdp_status()
                plugin._tdp_service.assert_not_called()

    async def test_unknown_host_startup_never_recovers_or_schedules(self):
        for profile in ("development", "production"):
            with self.subTest(profile=profile), patch(
                "regear.adapters.steamos.host.HostDiscovery.scan",
                side_effect=OSError("unreadable"),
            ):
                module, plugin = self.plugin(profile)
                plugin._build_info = {}
                plugin._events = Mock()
                plugin._process_service = Mock()
                plugin._process_service.return_value.recover_interrupted.return_value = NS(action_required=False)
                plugin._reconcile_sleep_guard = AsyncMock()
                plugin.get_snapshot = AsyncMock(return_value={
                    "snapshot": {"blockers": [], "game_state": "idle", "support_tier": "unknown"},
                    "inference": {"mode": "unknown"},
                })
                plugin._append_journey_event = Mock()
                def close_task(coroutine):
                    coroutine.close()
                    return Mock()
                with patch.object(module, "LinuxTopologyWakeup") as topology, patch.object(
                    module.asyncio, "create_task", side_effect=close_task
                ) as schedule:
                    await plugin._main()
                plugin._process_service.assert_not_called()
                plugin._reconcile_sleep_guard.assert_not_called()
                topology.assert_not_called()
                schedule.assert_not_called()

    async def test_unknown_host_background_dispatch_never_invokes_operation(self):
        for profile in ("development", "production"):
            with self.subTest(profile=profile), patch(
                "regear.adapters.steamos.host.HostDiscovery.scan",
                return_value=HostRecord("GPD", "G1617-01", "unknown"),
            ):
                module, plugin = self.plugin(profile)
                operation = Mock(return_value="effect")
                try:
                    await plugin._run_background_operation(operation)
                except ValueError:
                    pass
                operation.assert_not_called()

    async def test_every_effectful_public_rpc_is_denied_before_implementation(self):
        from regear.domain.runtime_admission import PASSIVE_RPCS
        for profile in ("development", "production"):
            module, plugin = self.plugin(profile)
            for name, method in inspect.getmembers(module.Plugin, inspect.iscoroutinefunction):
                if name.startswith("_") or name in PASSIVE_RPCS:
                    continue
                with self.subTest(profile=profile, rpc=name):
                    # Admission precedes the original argument parsing and body.
                    result = await getattr(plugin, name)()
                    self.assertEqual("runtime.observation_only", result["code"])
                    self.assertFalse(result["safe_to_unplug"])
                    self.assertEqual("", result["approval_token"])

    async def test_new_public_rpc_defaults_to_denial_in_both_profiles(self):
        for profile in ("development", "production"):
            module, plugin = self.plugin(profile)
            sink = Mock()
            async def new_rpc(self):
                sink()
            module.Plugin.new_rpc = new_rpc
            result = await plugin.new_rpc()
            self.assertEqual("runtime.observation_only", result["code"])
            sink.assert_not_called()

    async def test_private_producers_and_factories_stop_before_root_or_effects(self):
        names = ("_automatic_dock_loop", "_native_portable_recovery_loop",
                 "_sleep_guard_loop", "_docked_igpu_supervisor_loop",
                 "_reconcile_sleep_guard", "_observe_automatic_link_recovery",
                 "_run_background_operation", "_run_dock_power_request",
                 "_process_service", "_tdp_service", "_dock_mutation_gate",
                 "_presentation_transition_service", "_audio_handoff_service",
                 "_saved_tv_search", "_automatic_dock_preferences",
                 "_reconcile_physically_disconnected_dock",
                 "_transition_journal_service")
        for profile in ("development", "production"):
            module, plugin = self.plugin(profile)
            with patch.object(module, "RootOwnedRuntimeState") as root, patch.object(
                module, "SystemPowerCommandRunner"
            ) as power, patch.object(module.asyncio, "create_task") as schedule:
                for name in names:
                    with self.subTest(profile=profile, entry=name), self.assertRaises(ObservationDenied):
                        entry = getattr(plugin, name)
                        if inspect.iscoroutinefunction(entry):
                            await entry()
                        else:
                            entry()
                root.assert_not_called()
                power.assert_not_called()
                schedule.assert_not_called()

    async def test_unknown_constructor_composes_only_passive_diagnostics(self):
        for profile in ("development", "production"):
            with patch.object(build_profile_config, "BUILD_PROFILE", profile):
                module = load_main_module(real_dock_gate=True, real_host_admission=True)
            with patch("regear.adapters.steamos.host.HostDiscovery.scan", return_value=HostRecord("GPD", "G1617-01", "unknown")), \
                 patch.object(module, "DeviceAuthorizationFacade") as authorization, \
                 patch.object(module, "SleepGuardController") as inhibitor, \
                 patch.object(module, "RootOwnedRuntimeState") as root, \
                 patch.object(module, "DiagnosticsApi") as passive, \
                 patch.object(module, "InputPlumberReadCommandRunner") as catalog_runner, \
                 patch.object(module, "InputPlumberReader") as catalog_reader:
                plugin = module.Plugin()
                await plugin._main()
                await plugin._unload()
                authorization.assert_not_called()
                inhibitor.assert_not_called()
                root.assert_not_called()
                passive.assert_called_once()
                catalog_runner.assert_not_called()
                catalog_reader.assert_not_called()

    async def test_initial_observation_mode_cannot_upgrade_on_later_identity(self):
        with patch.object(build_profile_config, "BUILD_PROFILE", "development"):
            module = load_main_module(real_host_admission=True)
        ally = HostRecord("ASUSTeK COMPUTER INC.", "ROG Ally X RC72LA", "RC72LA")
        with patch("regear.adapters.steamos.host.HostDiscovery.scan", return_value=ally):
            plugin = module.Plugin(observation_only=True)
            plugin._observation_only = False
            with patch.object(module, "RootOwnedRuntimeState") as root:
                result = await plugin.confirm_device_authorization("a" * 32, True, "authorize")
                self.assertEqual("runtime.observation_only", result["code"])
                with self.assertRaises(ObservationDenied):
                    plugin._process_service()
                root.assert_not_called()

    async def test_bound_rpc_rechecks_identity_at_invocation_not_attribute_lookup(self):
        module = load_main_module(real_host_admission=True)
        plugin = module.Plugin.__new__(module.Plugin)
        plugin._observation_only = False
        plugin._device_authorization = Mock()
        plugin._unloading = False
        ally = HostRecord("ASUSTeK COMPUTER INC.", "ROG Ally X RC72LA", "RC72LA")
        with patch("regear.adapters.steamos.host.HostDiscovery.scan", return_value=ally):
            retained = plugin.confirm_device_authorization
        with patch("regear.adapters.steamos.host.HostDiscovery.scan", side_effect=OSError("changed")):
            result = await retained("a" * 32, True, "authorize")
        self.assertEqual("runtime.observation_only", result["code"])
        plugin._device_authorization.confirm.assert_not_called()

    async def test_unknown_reconciliation_does_not_release_an_existing_owned_lease(self):
        module, plugin = self.plugin("development")
        plugin._sleep_guard = Mock()
        plugin._sleep_hardware = Mock()
        with self.assertRaises(ObservationDenied):
            await plugin._reconcile_sleep_guard()
        plugin._sleep_guard.reconcile.assert_not_called()
        plugin._sleep_guard.close.assert_not_called()
        plugin._sleep_hardware.observe_presence.assert_not_called()

    async def test_observation_runtime_cannot_register_cleanup_task_callbacks(self):
        module, plugin = self.plugin("development")
        plugin._observation_started = True
        task = Mock()
        collection = set()
        with self.assertRaises(ObservationDenied):
            plugin._retain_until_done(task, collection)
        task.add_done_callback.assert_not_called()
        self.assertEqual(set(), collection)

    async def test_known_runtime_unload_keeps_owned_cleanup_when_identity_becomes_unreadable(self):
        ally = HostRecord("ASUSTeK COMPUTER INC.", "ROG Ally X RC72LA", "RC72LA")
        for profile in ("development", "production"):
            with patch.object(build_profile_config, "BUILD_PROFILE", profile):
                module = load_main_module(real_host_admission=True)
            with patch("regear.adapters.steamos.host.HostDiscovery.scan", return_value=ally):
                plugin = module.Plugin()
            plugin._sleep_guard = Mock()
            plugin._sleep_guard.close.return_value = NS(active=False, error="")
            with patch("regear.adapters.steamos.host.HostDiscovery.scan", side_effect=OSError("unreadable")), \
                 patch.object(module, "RootOwnedRuntimeState") as root, \
                 patch.object(module, "SystemPowerCommandRunner") as power:
                await plugin._unload()
                plugin._sleep_guard.close.assert_called_once()
                root.assert_not_called()
                power.assert_not_called()
                self.assertTrue(plugin._unloading)

    async def test_passive_snapshot_cannot_schedule_or_claim_protection_or_clearance(self):
        import json
        from dataclasses import replace
        from pathlib import Path
        from regear.application.snapshot import SnapshotReport
        from regear.domain.inference import infer_operating_mode
        from regear.domain.serialization import snapshot_from_dict
        snapshot = snapshot_from_dict(json.loads((Path(__file__).parent / "fixtures" / "portable.json").read_text()))
        snapshot = replace(snapshot, host_profile="unknown")
        for profile in ("development", "production"):
            module, plugin = self.plugin(profile)
            plugin._api = NS(get_snapshot_report=Mock(return_value=SnapshotReport(snapshot, infer_operating_mode(snapshot))))
            plugin._build_info = {"version": "0.3.189"}
            with patch.object(module, "RootOwnedRuntimeState") as root, patch.object(module.asyncio, "create_task") as schedule, \
                 patch.object(module, "InputPlumberReadCommandRunner") as catalog_runner, \
                 patch.object(module, "InputPlumberReader") as catalog_reader:
                result = await plugin.get_snapshot()
                self.assertEqual("unknown", result["snapshot"]["sleep_guard"]["confidence"])
                self.assertFalse(result["snapshot"]["disconnect_readiness"]["ready"])
                self.assertFalse(result["runtime_admission"]["mutation_allowed"])
                self.assertFalse(result["runtime_admission"]["safe_to_unplug"])
                root.assert_not_called()
                schedule.assert_not_called()
                catalog_runner.assert_not_called()
                catalog_reader.assert_not_called()
