import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from tests.test_main_process_delivery import load_main_module


class GraphicsTrialApprovalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plugin = load_main_module().Plugin()
        self.ready = Mock(return_value=True)
        self.preview = Mock(return_value=SimpleNamespace(approval_token="fresh-token", blockers=()))
        self.plugin._steam_trial_integration = lambda: SimpleNamespace(verify_effective=self.ready)
        self.plugin._presentation_transition_service = lambda: SimpleNamespace(preview=self.preview)

    async def test_graphics_endpoint_explicitly_requests_schema_two(self):
        result = await self.plugin.approve_supervised_portable_graphics_trial()
        self.assertEqual(result["approval_token"], "fresh-token")
        self.assertFalse(result["safe_to_unplug"])
        self.assertEqual(self.preview.call_args.kwargs["portable_trial_schema_version"], 2)
        self.assertTrue(self.preview.call_args.kwargs["portable_vulkan_trial"])

    async def test_old_endpoint_never_upgrades_approval(self):
        await self.plugin.approve_supervised_portable_vulkan_trial()
        self.assertNotIn("portable_trial_schema_version", self.preview.call_args.kwargs)

    async def test_missing_steam_wrapper_cannot_issue_approval(self):
        self.ready.return_value = False
        result = await self.plugin.approve_supervised_portable_graphics_trial()
        self.assertEqual(result["approval_token"], "")
        self.preview.assert_not_called()
