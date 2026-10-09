"""Actual passive delivery and real private catalog reduction; no device commands."""

import asyncio
import json
import subprocess
import sys
import threading
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module
from tests.test_controller_catalog_adapter import fixture, known
from regear.adapters.steamos.controller_catalog import (
    COMPOSITE, DBUS, MANAGER, TARGETS, InputPlumberCatalogAdapter, parse_provider_frame,
)
from regear.adapters.steamos.host import HostRecord
from regear.adapters.steamos.peripherals import (
    PeripheralInventory, SteamOsPeripheralObservationAdapter, peripheral_status_to_public_payload,
)
from regear.delivery import build_profile_config
from regear.domain.controller_catalog import CatalogCode, ControllerCatalog, EvidenceState, DeviceObservation, DeviceKind, ProviderInterface
from regear.ports.controller_catalog import PropertyRead, ProviderReadFrame
from regear.adapters.steamos import commands
from tests.test_inputplumber_catalog import FakeRunner


UNKNOWN = {"schema_version": 1, "provider": "unknown", "profile_metadata": "unknown",
           "virtual_target": "unknown", "relationships": "unknown"}


class DeckyControllerImportTests(unittest.TestCase):
    def test_missing_decky_xml_does_not_prevent_backend_or_snapshot_delivery(self):
        # Fresh process: a cached host ElementTree/reader must not hide the
        # actual Decky 3.11.7 missing-module startup failure.
        script = r'''
import asyncio, builtins, json, sys
from pathlib import Path
from unittest.mock import Mock, patch
from tests.test_main_process_delivery import load_main_module, SnapshotApi
from regear.domain.serialization import snapshot_from_dict
from regear.adapters.steamos.peripherals import (
    PeripheralInventory, SteamOsPeripheralObservationAdapter,
)
from regear.delivery import build_profile_config
original_import = builtins.__import__
attempts = []
deny_reader = False
deny_expat = False
def decky_import(name, *args, **kwargs):
    if name == 'xml.etree' or name.startswith('xml.etree.'):
        attempts.append(name)
        raise ModuleNotFoundError("No module named 'xml.etree'", name='xml.etree')
    if deny_reader and name == 'regear.adapters.steamos.inputplumber_catalog':
        raise ModuleNotFoundError('optional reader unavailable', name=name)
    if deny_expat and name == 'xml.parsers':
        raise ModuleNotFoundError('optional parser unavailable', name=name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = decky_import
for profile in ('development', 'production'):
    deny_reader = deny_expat = False
    build_profile_config.BUILD_PROFILE = profile
    module = load_main_module()
    assert not attempts, 'startup imported the optional controller reader'
    plugin = module.Plugin()
    snapshot = snapshot_from_dict(json.loads(Path('tests/fixtures/portable.json').read_text()))
    plugin._api = SnapshotApi(snapshot)
    payload = asyncio.run(plugin.get_snapshot())
    assert payload['snapshot']['schema_version'] == 3
    assert payload['runtime_admission']['schema_version'] == 1
    inventory = Mock()
    inventory.scan.return_value = PeripheralInventory(True, (), audio_complete=True)
    plugin._peripherals = SteamOsPeripheralObservationAdapter(inventory)
    from tests.test_inputplumber_catalog import FakeRunner
    fake = FakeRunner()
    with patch.object(module.InputPlumberReadCommandRunner, 'run', lambda runner, argv: fake.run(argv)):
        result = asyncio.run(plugin.get_peripheral_status())
    assert result['catalog'] == dict(schema_version=1, provider='known',
        profile_metadata='partial', virtual_target='unknown', relationships='unknown'), result['catalog']
    assert fake.calls and not attempts, 'functional read borrowed ElementTree'
    deny_reader = True
    with patch.object(module.InputPlumberReadCommandRunner, 'run') as run:
        result = asyncio.run(plugin.get_peripheral_status())
        run.assert_not_called()
    assert result['catalog'] == dict(schema_version=1, provider='unavailable',
        profile_metadata='unknown', virtual_target='unknown', relationships='unknown')
    assert 'xml' not in json.dumps(result)
    deny_reader = False
    deny_expat = True
    with patch.object(module.InputPlumberReadCommandRunner, 'run') as run:
        result = asyncio.run(plugin.get_peripheral_status())
        run.assert_not_called()
    assert result['catalog'] == dict(schema_version=1, provider='unknown',
        profile_metadata='unknown', virtual_target='unknown', relationships='unknown')
    attempts.clear()
'''
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)


def observer():
    inventory = Mock()
    inventory.scan.return_value = PeripheralInventory(True, (), audio_complete=True)
    return SteamOsPeripheralObservationAdapter(inventory)


def catalog(frame=None):
    return parse_provider_frame(frame or fixture())


class ControllerCatalogProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_main_module(real_host_admission=True)

    def project(self, value):
        project = getattr(self.module, "controller_catalog_to_public_facts", None)
        self.assertTrue(callable(project), "the actual delivery projection must exist")
        return project(value)

    def test_current_positive_catalog_reduces_to_only_four_closed_facts(self):
        result = self.project(catalog())
        self.assertEqual({**UNKNOWN, **{key: "known" for key in UNKNOWN if key != "schema_version"}}, result)
        text = json.dumps(result)
        for private in ("connection:1", "Identical", "Xbox", "profile.yaml", "source0", "target0", "count", "key", "epoch"):
            self.assertNotIn(private, text)

    def test_missing_stale_forged_and_rejected_inputs_have_no_known_facts(self):
        for value in (None, {}, SimpleNamespace(availability=EvidenceState.KNOWN),
                      replace(catalog(), connection_epoch=""),
                      replace(catalog(), enumeration_complete=1),
                      replace(catalog(), issues=(CatalogCode.BOUNDS,)),
                      replace(catalog(), issues=(CatalogCode.MALFORMED,)),
                      replace(catalog(), devices=list(catalog().devices))):
            with self.subTest(value=type(value).__name__):
                self.assertEqual(UNKNOWN, self.project(value))

    def test_direct_catalog_rejects_malformed_roles_and_duplicate_interface_evidence(self):
        original = catalog()
        for devices in ((DeviceObservation("not/a/dbus/path", DeviceKind.TARGET, (COMPOSITE,)),),
                        (DeviceObservation("/target0", DeviceKind.TARGET, (COMPOSITE,)),)):
            self.assertEqual(UNKNOWN, self.project(replace(original, devices=devices)))
        self.assertEqual(UNKNOWN, self.project(replace(original, interfaces=(
            ProviderInterface(COMPOSITE, EvidenceState.KNOWN),
            ProviderInterface(COMPOSITE, EvidenceState.UNSUPPORTED)))))

    def test_partial_frame_does_not_promote_category_completeness(self):
        result = self.project(catalog(replace(fixture(), enumeration_complete=False)))
        self.assertEqual({**UNKNOWN, "provider": "known", "profile_metadata": "partial",
                          "virtual_target": "partial", "relationships": "partial"}, result)

    def test_denied_properties_stay_unknown_and_rows_are_independent(self):
        frame = fixture()
        for key in ("ProfileName", "ProfilePath"):
            frame.objects["/composite0"][COMPOSITE][key] = PropertyRead(EvidenceState.ERROR)
        result = self.project(catalog(frame))
        self.assertEqual("unknown", result["profile_metadata"])
        # The inherited parser clears aggregate completeness on a denied read.
        # Preserve independent positives without inventing lost completeness.
        self.assertEqual("partial", result["virtual_target"])
        self.assertEqual("partial", result["relationships"])

    def test_known_empty_is_not_positive_profile_target_or_relation_evidence(self):
        frame = ProviderReadFrame("current:1", {"/manager": {MANAGER: {}}}, enumeration_complete=True)
        self.assertEqual({**UNKNOWN, "provider": "known"}, self.project(catalog(frame)))
        frame = fixture()
        for key in ("ProfileName", "ProfilePath"):
            frame.objects["/composite0"][COMPOSITE][key] = known("")
        self.assertEqual("unknown", self.project(catalog(frame))["profile_metadata"])

    def test_unavailable_requires_positive_unsupported_evidence(self):
        self.assertEqual({**UNKNOWN, "provider": "unavailable"}, self.project(
            ControllerCatalog(EvidenceState.UNSUPPORTED)))
        self.assertEqual(UNKNOWN, self.project(ControllerCatalog(EvidenceState.ERROR)))
        frame = ProviderReadFrame("current:1", {"/manager": {MANAGER: {}}}, enumeration_complete=True,
                                  interface_states={name: EvidenceState.UNSUPPORTED for name in TARGETS | {COMPOSITE, DBUS}})
        self.assertEqual({**UNKNOWN, "provider": "known", "profile_metadata": "unavailable",
                          "virtual_target": "unavailable", "relationships": "unavailable"}, self.project(catalog(frame)))

    def test_missing_or_shared_relationships_remain_partial_not_effective_target(self):
        frame = fixture()
        frame.objects["/composite0"][COMPOSITE]["TargetDevices"] = known(["/missing0"])
        result = self.project(catalog(frame))
        self.assertEqual("partial", result["relationships"])
        self.assertEqual("known", result["virtual_target"])
        self.assertEqual(set(UNKNOWN), set(result))


class ControllerCatalogGetterTests(unittest.IsolatedAsyncioTestCase):
    def plugin(self, profile, *, forced=False):
        with patch.object(build_profile_config, "BUILD_PROFILE", profile):
            module = load_main_module(real_host_admission=True)
        plugin = module.Plugin.__new__(module.Plugin)
        plugin._observation_only = forced
        plugin._observation_started = True
        plugin._unloading = False
        return module, plugin

    async def test_default_getter_composes_real_reader_with_fresh_bounded_runner(self):
        ally = HostRecord("ASUSTeK COMPUTER INC.", "ROG Ally X RC72LA", "RC72LA")
        mini = HostRecord("GPD", "G1617-01", "unknown")
        for profile in ("development", "production"):
            for host in (mini, ally):
                with self.subTest(profile=profile, host=host.product_name):
                    module, plugin = self.plugin(profile)
                    plugin._observation_started = host is mini
                    plugin._peripherals = observer()
                    fake = FakeRunner()
                    runners = []

                    def read(runner, argv):
                        if not any(runner is previous for previous in runners):
                            runners.append(runner)
                            self.assertEqual(512, runner._remaining_calls)
                            self.assertEqual(1048576, runner._remaining_bytes)
                            self.assertFalse(runner._failed)
                        return fake.run(argv)

                    with patch("regear.adapters.steamos.host.HostDiscovery.scan", return_value=host), \
                         patch.object(commands.InputPlumberReadCommandRunner, "run", read), \
                         patch.object(commands.subprocess, "Popen") as spawn, \
                         patch.object(module, "RootOwnedRuntimeState") as root, \
                         patch.object(module, "SystemPowerCommandRunner") as power, \
                         patch.object(module.asyncio, "create_task") as schedule:
                        for _ in range(2):
                            result = await plugin.get_peripheral_status({"runner": "forged", "catalog": {"provider": "unavailable"}})
                            self.assertEqual({**UNKNOWN, "provider": "known", "profile_metadata": "partial"}, result["catalog"])
                            self.assertEqual(set(UNKNOWN), set(result["catalog"]))
                        fake.hook = lambda tail, reply: commands.CommandResult(reply.argv, 1, "", "private failure")
                        unavailable = await plugin.get_peripheral_status()
                        self.assertEqual(UNKNOWN, unavailable["catalog"])
                        self.assertNotIn("private", json.dumps(unavailable))
                        spawn.assert_not_called()
                        root.assert_not_called()
                        power.assert_not_called()
                        schedule.assert_not_called()
                    self.assertEqual(3, len(runners))

    async def test_unload_during_read_discards_late_catalog(self):
        module, plugin = self.plugin("development")
        plugin._peripherals = observer()
        started, release = threading.Event(), threading.Event()

        def collect():
            started.set()
            if not release.wait(2):
                raise TimeoutError("test fixture was not released")
            return catalog()

        with patch.object(module, "_controller_catalog_factory", return_value=SimpleNamespace(collect_catalog=collect)):
            task = asyncio.create_task(plugin.get_peripheral_status())
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                await plugin._unload()
            finally:
                release.set()
            self.assertEqual(UNKNOWN, (await task)["catalog"])

    async def test_unload_before_queued_worker_starts_never_constructs_reader(self):
        module, plugin = self.plugin("development")
        plugin._peripherals = observer()
        queued, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def queued_thread(function, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                queued.set()
                await release.wait()
            return function(*args, **kwargs)

        with patch.object(module.asyncio, "to_thread", queued_thread), \
             patch.object(module, "_controller_catalog_factory", return_value=SimpleNamespace(collect_catalog=lambda: catalog())) as factory:
            task = asyncio.create_task(plugin.get_peripheral_status())
            try:
                await asyncio.wait_for(queued.wait(), 1)
                await plugin._unload()
            finally:
                release.set()
            self.assertEqual(UNKNOWN, (await task)["catalog"])
            factory.assert_not_called()

    async def test_cancelled_getter_leaves_only_deadline_bounded_read_and_reaps_child(self):
        module, plugin = self.plugin("development")
        plugin._peripherals = observer()
        real_spawn = subprocess.Popen
        runner_type = commands.InputPlumberReadCommandRunner
        started = threading.Event()
        processes = []

        def spawn(argv, **kwargs):
            runner_type.validate(argv)
            self.assertEqual("GetId", argv[-1])
            process = real_spawn((sys.executable, "-c", "import time; time.sleep(20)"), **kwargs)
            processes.append(process)
            started.set()
            return process

        with patch.object(module, "InputPlumberReadCommandRunner", side_effect=lambda: runner_type(timeout_seconds=.15), create=True), \
             patch.object(commands.subprocess, "Popen", side_effect=spawn):
            task = asyncio.create_task(plugin.get_peripheral_status())
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                for _ in range(200):
                    if (processes and processes[0].poll() is not None
                            and processes[0].stdout.closed and processes[0].stderr.closed):
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(1, len(processes))
                self.assertIsNotNone(processes[0].poll())
                self.assertTrue(processes[0].stdout.closed)
                self.assertTrue(processes[0].stderr.closed)
            finally:
                task.cancel()
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait()

    async def test_unknown_and_forced_modes_allow_only_passive_getter_composition(self):
        for profile in ("development", "production"):
            for forced in (False, True):
                with self.subTest(profile=profile, forced=forced):
                    module, plugin = self.plugin(profile, forced=forced)
                    passive = observer()
                    legacy = peripheral_status_to_public_payload(passive.observe())
                    reader = Mock()
                    reader.read_snapshot.return_value = fixture()
                    factory = Mock(return_value=InputPlumberCatalogAdapter(reader))
                    with patch.object(module, "_controller_catalog_factory", factory, create=True), \
                         patch.object(module, "SteamOsPeripheralObservationAdapter", return_value=passive), \
                         patch.object(module, "RootOwnedRuntimeState") as root, \
                         patch.object(module, "SystemPowerCommandRunner") as power, \
                         patch.object(module.asyncio, "create_task") as schedule:
                        result = await plugin.get_peripheral_status({"catalog": {"provider": "forged"}})
                    self.assertEqual(legacy, {key: result[key] for key in legacy})
                    self.assertEqual("known", result["catalog"]["provider"])
                    reader.read_snapshot.assert_called_once()
                    factory.assert_called_once_with()
                    root.assert_not_called()
                    power.assert_not_called()
                    schedule.assert_not_called()

    async def test_missing_reader_and_failures_clear_previous_known_facts(self):
        module, plugin = self.plugin("development")
        passive = observer()
        plugin._peripherals = passive
        for factory in (None, Mock(side_effect=RuntimeError("private path/secret")),
                        Mock(return_value=SimpleNamespace(collect_catalog=Mock(return_value=None)))):
            with patch.object(module, "_controller_catalog_factory", factory, create=True):
                result = await plugin.get_peripheral_status()
            self.assertEqual(UNKNOWN, result["catalog"])
            self.assertNotIn("secret", json.dumps(result))

    async def test_reader_never_constructs_on_startup_snapshot_or_unload(self):
        module, plugin = self.plugin("development")
        with patch.object(module, "_controller_catalog_factory", Mock(), create=True) as factory:
            await plugin._main()
            await plugin._unload()
            factory.assert_not_called()

    async def test_unloading_getter_never_dispatches_reader(self):
        module, plugin = self.plugin("development")
        plugin._unloading = True
        with patch.object(module, "_controller_catalog_factory", Mock(), create=True) as factory:
            result = await plugin.get_peripheral_status()
        self.assertEqual(UNKNOWN, result["catalog"])
        factory.assert_not_called()
