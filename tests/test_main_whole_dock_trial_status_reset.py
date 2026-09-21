import asyncio
import threading
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module


TOKEN_A = "a" * 64 + ":" + "b" * 64
TOKEN_B = "c" * 64 + ":" + "d" * 64


class WholeDockTrialStatusResetTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)
        self.plugin._whole_dock_trial_worker_alive = False
        self.plugin._unloading = False
        self.plugin._whole_dock_trial_status = {
            "schema_version": 1,
            "code": "dock_teardown.software_down",
            "busy": False,
            "ok": True,
            "software_down": True,
            "safe_to_unplug": False,
            "request_id": "old-request",
        }

    def read(self):
        return asyncio.run(
            self.plugin.get_egpu_disconnect_status("whole_dock_trial")
        )

    def patches(self, *, claims=(None, None, None), tokens=(TOKEN_A, TOKEN_A)):
        store = Mock()
        store.load.side_effect = list(claims)
        cards = [NS(boot_vga=False, pci_bdf="0000:08:00.0")]
        discovery = Mock()
        discovery.scan.return_value = cards
        bindings = [NS(binding=value.split(":")[0], generation=value.split(":")[1])
                    for value in tokens]
        return (
            patch.object(self.module, "WholeDockClaimStore", return_value=store),
            patch.object(self.module, "DrmDiscovery", return_value=discovery),
            patch.object(self.module, "resolve_whole_dock", side_effect=bindings),
        )

    def test_retired_claim_and_stable_new_attachment_reset_terminal_view(self):
        p1, p2, p3 = self.patches()
        with p1, p2, p3:
            result = self.read()
        self.assertEqual(result, {
            "schema_version": 1,
            "code": "dock_teardown.no_trial",
            "busy": False,
            "safe_to_unplug": False,
            "in_flight": False,
            "attachment_token": TOKEN_A,
        })
        self.assertIs(self.plugin._whole_dock_trial_status, result)
        self.assertNotIn("request_id", result)

    def test_claim_must_stay_absent_before_between_and_after_observations(self):
        cases = (
            (NS(stage="software_down"),),
            (None, NS(stage="claimed")),
            (None, None, NS(stage="claimed")),
        )
        for claims in cases:
            with self.subTest(claims=claims):
                self.setUp()
                p1, p2, p3 = self.patches(claims=claims)
                with p1, p2, p3:
                    result = self.read()
                self.assertEqual(result["code"], "dock_teardown.software_down")
                self.assertEqual(result["request_id"], "old-request")

    def test_attachment_identity_must_match_twice(self):
        p1, p2, p3 = self.patches(tokens=(TOKEN_A, TOKEN_B))
        with p1, p2, p3:
            result = self.read()
        self.assertEqual(result["code"], "dock_teardown.software_down")

    def test_only_exact_successful_software_down_is_considered(self):
        malformed = (
            {"schema_version": 2},
            {"code": "dock_teardown.gpu_removed"},
            {"busy": True},
            {"ok": False},
            {"software_down": False},
            {"safe_to_unplug": True},
        )
        original = dict(self.plugin._whole_dock_trial_status)
        for change in malformed:
            with self.subTest(change=change):
                status = {**original, **change}
                self.plugin._whole_dock_trial_status = status
                self.plugin._fresh_unclaimed_whole_dock_attachment_token = Mock()
                result = self.read()
                self.plugin._fresh_unclaimed_whole_dock_attachment_token.assert_not_called()
                self.assertNotEqual(result.get("code"), "dock_teardown.no_trial")

    def test_new_status_started_during_observation_wins_compare_and_set(self):
        entered = threading.Event()
        release = threading.Event()

        def observe():
            entered.set()
            self.assertTrue(release.wait(2))
            return TOKEN_A

        self.plugin._fresh_unclaimed_whole_dock_attachment_token = observe

        async def interleave():
            read = asyncio.create_task(
                self.plugin.get_egpu_disconnect_status("whole_dock_trial")
            )
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            running = {
                "schema_version": 1,
                "code": "dock_teardown.trial_running",
                "busy": True,
                "safe_to_unplug": False,
                "request_id": "new-request",
            }
            self.plugin._whole_dock_trial_worker_alive = True
            self.plugin._whole_dock_trial_status = running
            release.set()
            return await read, running

        result, running = asyncio.run(interleave())
        self.assertEqual(result["code"], "dock_teardown.trial_running")
        self.assertIs(result["busy"], True)
        self.assertIs(result["in_flight"], True)
        self.assertIs(self.plugin._whole_dock_trial_status, running)

    def test_in_place_busy_update_and_unload_both_prevent_reset(self):
        for change in ("busy", "unloading"):
            with self.subTest(change=change):
                self.setUp()

                def observe():
                    if change == "busy":
                        self.plugin._whole_dock_trial_status["busy"] = True
                    else:
                        self.plugin._unloading = True
                    return TOKEN_A

                self.plugin._fresh_unclaimed_whole_dock_attachment_token = observe
                result = self.read()
                self.assertEqual(result["code"], "dock_teardown.software_down")
                self.assertIs(self.plugin._whole_dock_trial_status["busy"],
                              change == "busy")


if __name__ == "__main__":
    unittest.main()
