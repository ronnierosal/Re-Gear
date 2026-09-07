import unittest
import subprocess
from unittest.mock import patch

from scripts.probe_user_device_policy import classify, fixture_command, run_probe, service_sample


class DevicePolicyFixtureTests(unittest.TestCase):
    def setUp(self):
        self.baseline = dict(allowed_zero="opened", denied_null="opened",
            denied_null_alias="opened", no_new_privileges="0",
            capability_bound="000000ffffffffff", user_namespace="user:[fixture]", cgroup="0::/baseline", effective_uid=1000)
        self.restricted = dict(self.baseline, denied_null="denied", denied_null_alias="denied", cgroup="0::/fixture")

    def test_actual_denial_and_preserved_context_required(self):
        self.assertEqual(classify(self.baseline, self.restricted), "fixture_enforced")

    def test_accepted_but_ineffective_policy_is_not_success(self):
        self.assertEqual(classify(self.baseline, dict(self.baseline, cgroup="0::/fixture")), "not_enforced")
        self.restricted["denied_null_alias"] = "opened"
        self.assertEqual(classify(self.baseline, self.restricted), "not_enforced")

    def test_broken_baseline_or_allow_path_is_inconclusive(self):
        for key in ("allowed_zero", "denied_null", "denied_null_alias"):
            baseline = dict(self.baseline, **{key: "denied"})
            self.assertEqual(classify(baseline, self.restricted), "inconclusive")
        self.restricted["allowed_zero"] = "denied"
        self.assertEqual(classify(self.baseline, self.restricted), "inconclusive")

    def test_unrelated_open_error_is_not_denial(self):
        self.restricted["denied_null"] = "other_error"
        self.assertEqual(classify(self.baseline, self.restricted), "inconclusive")

    def test_changed_execution_context_rejected(self):
        for key in ("no_new_privileges", "capability_bound", "user_namespace"):
            after = dict(self.restricted, **{key: "changed"})
            self.assertEqual(classify(self.baseline, after), "context_changed")

    def test_unknown_evidence_shape_is_inconclusive(self):
        for value in (None, [], {}, {"result": "ok"}):
            self.assertEqual(classify(value, self.restricted), "inconclusive")
            self.assertEqual(classify(self.baseline, value), "inconclusive")

    def test_same_cgroup_does_not_prove_child_policy(self):
        self.restricted["cgroup"] = self.baseline["cgroup"]
        self.assertEqual(classify(self.baseline, self.restricted), "inconclusive")

    def test_root_or_different_user_does_not_prove_user_enforcement(self):
        for uid in (0, 1001, True, "1000"):
            self.assertEqual(classify(self.baseline, dict(self.restricted, effective_uid=uid)), "inconclusive")

    def test_only_disposable_unit_and_non_root_identity_can_be_built(self):
        unit = "regear-device-fixture-" + "a" * 32 + ".service"
        for uid in (0, -1, True, "1000", 2**32 - 1):
            with self.assertRaises(ValueError):
                fixture_command(unit, restricted=True, system_uid=uid)
        for name in ("steam-launcher.service", "gamescope-session.service", "regear-device-fixture-../x.service"):
            with self.assertRaises(ValueError):
                fixture_command(name, restricted=True)
        command = fixture_command(unit, restricted=True, system_uid=1000)
        self.assertIn("--property=User=1000", command)
        self.assertIn("--property=RuntimeMaxSec=5", command)
        self.assertNotIn("--user", command)

    def test_timeout_still_checks_exact_fixture_cleanup(self):
        missing = subprocess.CompletedProcess([], 0, stdout="not-found\n", stderr="")
        with patch("scripts.probe_user_device_policy.subprocess.run", side_effect=[
            subprocess.TimeoutExpired("fixture", 12), missing, missing,
        ]) as runner:
            sample, removed = service_sample(restricted=True)
        self.assertIsNone(sample)
        self.assertTrue(removed)
        unit = runner.call_args_list[0].args[0]
        name = next(value.split("=", 1)[1] for value in unit if value.startswith("--unit="))
        for call in runner.call_args_list[1:]:
            self.assertIn(name, call.args[0])
            self.assertIn("show", call.args[0])

    def test_unverified_cleanup_is_not_success(self):
        failed = subprocess.CompletedProcess([], 0, stdout="loaded\n", stderr="")
        with patch("scripts.probe_user_device_policy.subprocess.run", side_effect=[
            subprocess.TimeoutExpired("fixture", 12), *([failed] * 12),
        ]), patch("scripts.probe_user_device_policy.time.sleep"):
            sample, removed = service_sample(restricted=True)
        self.assertIsNone(sample)
        self.assertFalse(removed)

    def test_system_baseline_failure_does_not_start_restricted_service(self):
        with patch("scripts.probe_user_device_policy.sys.platform", "linux"), \
             patch("scripts.probe_user_device_policy.os.geteuid", return_value=0, create=True), \
             patch.dict("os.environ", {"SUDO_UID": "1000"}), \
             patch("scripts.probe_user_device_policy.service_sample", return_value=(None, False)) as sample:
            report = run_probe(system_fixture=True)
        self.assertEqual(report["status"], "inconclusive")
        self.assertFalse(report["disconnect_clearance"])
        sample.assert_called_once_with(restricted=False, system_uid=1000)

    def test_system_probe_requires_operator_sudo_context(self):
        with patch("scripts.probe_user_device_policy.sys.platform", "linux"), \
             patch("scripts.probe_user_device_policy.os.geteuid", return_value=1000, create=True), \
             patch.dict("os.environ", {"SUDO_UID": "1000"}), \
             patch("scripts.probe_user_device_policy.service_sample") as sample:
            report = run_probe(system_fixture=True)
        self.assertEqual(report["reason"], "operator_sudo_session_required")
        sample.assert_not_called()
