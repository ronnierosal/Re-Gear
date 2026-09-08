import asyncio
import tempfile
import unittest
from pathlib import Path

from test_main_process_delivery import load_main_module
from hdm.delivery.auto_tdp_preferences import FileAutoTdpPreferences


class MainAutoPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.plugin = load_main_module().Plugin()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        store = FileAutoTdpPreferences(Path(self.temp.name))
        self.plugin._auto_preferences_store = lambda: store
        self.plugin._tdp_service = lambda: self.fail("preferences must not construct power runtime")

    def test_preferences_persist_separately_by_mode_without_starting(self):
        for placement, target in (("portable", 40), ("docked_egpu", 60)):
            result = asyncio.run(self.plugin.save_auto_tdp_preference(placement, target, 7, 25))
            self.assertEqual(result["code"], "auto_tdp_preferences.saved")
        result = asyncio.run(self.plugin.get_auto_tdp_preferences())
        self.assertEqual({row["placement"]: row["target_fps"] for row in result["preferences"]}, {"portable": 40, "docked_egpu": 60})
        self.assertIsNone(self.plugin._tdp_runtime)

    def test_bad_input_is_categorical_and_preserves_saved_preferences(self):
        asyncio.run(self.plugin.save_auto_tdp_preference("portable", 40, 7, 25))
        for args in (("unknown", 40, 7, 25), ("portable", float("nan"), 7, 25), ("portable", 40, True, 25)):
            self.assertEqual(asyncio.run(self.plugin.save_auto_tdp_preference(*args))["code"], "auto_tdp_preferences.save_failed")
        self.assertEqual(len(asyncio.run(self.plugin.get_auto_tdp_preferences())["preferences"]), 1)
