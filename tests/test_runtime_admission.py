"""Pure admission fails closed and never confers hardware qualification."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.domain.runtime_admission import (
    RuntimeAdmission, passive_rpc_allowed, runtime_admission,
)


class RuntimeAdmissionTests(unittest.TestCase):
    def test_only_exact_host_and_explicit_nonforced_mode_reach_existing_guards(self):
        self.assertEqual(RuntimeAdmission.PROFILE_GATED,
                         runtime_admission(exact_host=True, observation_only=False))
        for host in (False, None, 1, "true", object()):
            for forced in (False, True, None, 0, "false"):
                with self.subTest(host=host, forced=forced):
                    self.assertEqual(RuntimeAdmission.OBSERVATION_ONLY,
                                     runtime_admission(exact_host=host, observation_only=forced))

    def test_forced_or_missing_mode_never_upgrades_exact_host(self):
        for forced in (True, None, 0, "false", object()):
            self.assertEqual(RuntimeAdmission.OBSERVATION_ONLY,
                             runtime_admission(exact_host=True, observation_only=forced))

    def test_allowlist_does_not_round_getters_or_new_methods_down_to_passive(self):
        self.assertTrue(passive_rpc_allowed("get_snapshot"))
        self.assertTrue(passive_rpc_allowed("classify_offline_details"))
        for method in ("get_tdp_status", "get_egpu_disconnect_status",
                       "get_device_authorization_status", "take_pending_sleep",
                       "confirm_device_authorization", "future_rpc", "get_future_status"):
            self.assertFalse(passive_rpc_allowed(method))
