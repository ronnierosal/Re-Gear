import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.delivery.portable_vulkan_trial import TrialEvidence, build_candidate, restore_environment


class PortableVulkanTrialTests(unittest.TestCase):
    def setUp(self):
        self.evidence = TrialEvidence("boot", "generation", "1002:15bf", "eDP-1", True, False, True)

    def build(self, evidence=None, env=None, **changes):
        args = dict(evidence=evidence or self.evidence, current_boot="boot",
                    current_generation="generation", present_gpus=("1002:15bf", "1002:7480"),
                    internal_connectors=("eDP-1",))
        args.update(changes)
        return build_candidate(("--prefer-vk-device", "1002:7480"), env or {}, **args)

    def test_selects_internal_and_restricts_enumeration_without_mutating_original(self):
        original = {"MESA_VK_DEVICE_SELECT": "1002:7480", "OTHER": "kept"}
        argv, env = self.build(env=original)
        self.assertIn("1002:15bf", argv)
        self.assertNotIn("1002:7480", argv)
        self.assertEqual(env["MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE"], "1")
        self.assertEqual(original["MESA_VK_DEVICE_SELECT"], "1002:7480")
        self.assertEqual(restore_environment(env, original), original)

    def test_rejects_stale_boot_or_generation(self):
        for changes in ({"current_boot": "other"}, {"current_generation": "other"}, {"current_boot": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.build(**changes)

    def test_rejects_unknown_identity_game_or_layer(self):
        for changes in ({"identity_verified": False}, {"game_running": None},
                        {"game_running": True}, {"mesa_layer_verified": False}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.build(evidence=replace(self.evidence, **changes))

    def test_rejects_ambiguous_or_absent_internal_gpu(self):
        for gpus in ((), ("1002:15bf", "1002:15bf")):
            with self.assertRaises(ValueError):
                self.build(present_gpus=gpus)

    def test_rejects_missing_internal_connector(self):
        with self.assertRaises(ValueError):
            self.build(internal_connectors=())

    def test_does_not_override_conflicting_layer_or_prime_policy(self):
        for key in ("DRI_PRIME", "NODEVICE_SELECT", "VK_DRIVER_FILES", "VK_LOADER_LAYERS_DISABLE"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.build(env={key: "1"})

    def test_rollback_removes_new_keys_and_preserves_unrelated_changes(self):
        _, env = self.build()
        env["OTHER"] = "new"
        self.assertEqual(restore_environment(env, {}), {"OTHER": "new"})
