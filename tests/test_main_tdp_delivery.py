import asyncio
import json
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_main_process_delivery import load_main_module
from hdm.domain.models import EgpuPresence, GameState
from hdm.domain.serialization import snapshot_from_dict
from hdm.delivery.tdp_runtime import unavailable_status


class MainTdpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_main_module()

    def setUp(self):
        self.plugin = self.module.Plugin()
        fixture = Path(__file__).parent / "fixtures/portable.json"
        self.snapshot = snapshot_from_dict(json.loads(fixture.read_text()))
        self.plugin._api = SimpleNamespace(get_snapshot_report=lambda: SimpleNamespace(snapshot=self.snapshot))
        self.plugin._sleep_hardware = SimpleNamespace(observe_presence=lambda: EgpuPresence.ABSENT)
        self.plugin._transition_journal_service = lambda: SimpleNamespace(status=lambda: SimpleNamespace(durable=True, owner=SimpleNamespace(value="none")))
        self.plugin._tdp_user = lambda: SimpleNamespace(home=Path("/home/test-user"))

    def test_startup_does_not_construct_or_enable_power_runtime(self):
        self.assertIsNone(self.plugin._tdp_runtime)

    def test_rpc_only_forwards_exact_operations_and_arguments(self):
        calls = []
        def method(name):
            return lambda *args: calls.append((name, args)) or unavailable_status()
        runtime = SimpleNamespace(cancel_benchmark=lambda: None, **{name: method(name) for name in ("status", "set_enabled", "apply", "restore")})
        self.plugin._tdp_service = lambda: runtime
        asyncio.run(self.plugin.get_tdp_status())
        asyncio.run(self.plugin.set_tdp_enabled(True))
        asyncio.run(self.plugin.apply_tdp_limit(20))
        asyncio.run(self.plugin.restore_tdp_limit())
        self.assertEqual(calls, [("status", ()), ("set_enabled", (True,)), ("apply", (20,)), ("restore", ())])

    def test_closing_refuses_before_service_construction(self):
        self.plugin._tdp_closing.set()
        def fail():
            raise AssertionError("service must not be called")
        self.plugin._tdp_service = fail
        self.assertEqual(asyncio.run(self.plugin.apply_tdp_limit(20))["code"], "tdp.closing")

    def test_factory_error_is_redacted(self):
        def fail():
            raise OSError("private path and address")
        self.plugin._tdp_service = fail
        self.assertEqual(asyncio.run(self.plugin.get_tdp_status()), unavailable_status())

    def test_unload_during_construction_closes_new_runtime(self):
        closed = []
        def construct(**kwargs):
            self.plugin._tdp_closing.set()
            return SimpleNamespace(close=lambda: closed.append(True))
        with patch.object(self.module, "RootOwnedRuntimeState") as root, patch.object(self.module, "TdpRuntime", side_effect=construct):
            root.return_value.ensure.return_value = Path.cwd()
            with self.assertRaisesRegex(RuntimeError, "closing"):
                self.plugin._tdp_service()
        self.assertEqual(closed, [True])

    def test_preflight_allows_known_game_only_in_detached_portable(self):
        with patch.object(self.module, "KnownTdpControllerScan") as scan:
            scan.return_value.scan.return_value = SimpleNamespace(complete=True, conflicts=())
            for state in (GameState.IDLE, GameState.RUNNING):
                self.snapshot = replace(self.snapshot, game_state=state)
                self.assertEqual(self.plugin._tdp_preflight(), "tdp.ready")
            self.snapshot = replace(self.snapshot, game_state=GameState.UNKNOWN)
            self.assertEqual(self.plugin._tdp_preflight(), "tdp.game_unknown")
            self.snapshot = replace(self.snapshot, game_state=GameState.IDLE)
            self.plugin._sleep_hardware.observe_presence = lambda: EgpuPresence.PRESENT
            self.assertEqual(self.plugin._tdp_preflight(), "tdp.egpu_attached")

    def test_transition_and_unknown_conflict_scan_block(self):
        with patch.object(self.module, "KnownTdpControllerScan") as scan:
            scan.return_value.scan.return_value = SimpleNamespace(complete=False, conflicts=())
            self.assertEqual(self.plugin._tdp_preflight(), "tdp.conflict_scan_unavailable")
            scan.return_value.scan.return_value = SimpleNamespace(complete=True, conflicts=("process.hhd",))
            self.assertEqual(self.plugin._tdp_preflight(), "tdp.conflict")
        self.plugin._transition_journal_service = lambda: SimpleNamespace(status=lambda: SimpleNamespace(durable=False, owner=SimpleNamespace(value="unknown")))
        self.assertEqual(self.plugin._tdp_preflight(), "tdp.transition_active")
