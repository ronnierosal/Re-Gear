import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from scripts.probe_cgroup_filter_handoff import CHECKS, cleanup_fixture, close_filter, open_cgroup, valid_filtered


class CgroupFilterHandoffTests(unittest.TestCase):
    def test_complete_observations_include_descendant_and_retained_fd_limit(self):
        result = dict(stage="filtered", checks=dict.fromkeys(CHECKS, True))
        self.assertTrue(valid_filtered(result))
        for key in CHECKS:
            altered = dict(result, checks=dict(result["checks"], **{key: False}))
            self.assertFalse(valid_filtered(altered))

    def test_unknown_or_truthy_results_are_not_evidence(self):
        for value in (None, {}, [], {"stage": "ready"}):
            self.assertFalse(valid_filtered(value))
        for value in (1, "true", None):
            checks = dict.fromkeys(CHECKS, True)
            checks["null_denied"] = value
            self.assertFalse(valid_filtered(dict(stage="filtered", checks=checks)))

    def test_wrong_service_parent_or_traversal_rejected_before_open(self):
        unit = "regear-link-fixture-" + "a" * 32 + ".service"
        for path in ("/", "/user.slice/user-1000.slice/user@1000.service",
                     "/user.slice/user-1000.slice/user@1000.service/../" + unit,
                     "/user.slice/user-1000.slice/user@1000.service//" + unit,
                     "/user.slice/user-1001.slice/user@1001.service/app.slice/" + unit,
                     "/user.slice/user-1000.slice/user@1000.service/app.slice/steam-launcher.service"):
            with patch("scripts.probe_cgroup_filter_handoff.os.open") as opened:
                with self.assertRaises(ValueError):
                    open_cgroup(path, 1000, unit)
                opened.assert_not_called()

    def test_failed_component_closes_last_directory_fd(self):
        unit = "regear-link-fixture-" + "a" * 32 + ".service"
        path = "/user.slice/user-1000.slice/user@1000.service/app.slice/" + unit
        with patch("scripts.probe_cgroup_filter_handoff.os.O_DIRECTORY", 0x10000, create=True), \
             patch("scripts.probe_cgroup_filter_handoff.os.O_NOFOLLOW", 0x20000, create=True), \
             patch("scripts.probe_cgroup_filter_handoff.os.open", side_effect=[10, 11, OSError("changed")]), \
             patch("scripts.probe_cgroup_filter_handoff.os.close") as close:
            with self.assertRaises(OSError):
                open_cgroup(path, 1000, unit)
        self.assertEqual([call.args[0] for call in close.call_args_list], [10, 11])

    def test_exited_launcher_still_requires_service_cleanup(self):
        child = Mock()
        child.poll.return_value = 0
        control = Mock(side_effect=[SimpleNamespace(stdout="loaded"),
            SimpleNamespace(stdout=""), SimpleNamespace(stdout="not-found")])
        self.assertTrue(cleanup_fixture(control, child, "fixture.service"))
        self.assertIn((("stop", "fixture.service"), {}), control.call_args_list)
        child.wait.assert_not_called()

    def test_unreadable_cleanup_cannot_pass(self):
        self.assertFalse(cleanup_fixture(Mock(side_effect=OSError("unavailable")), Mock(), "fixture.service"))

    def test_verified_detach_survives_cgroup_collection(self):
        owner = Mock(link_fd=None)
        owner.query_program_ids.side_effect = OSError("cgroup no longer exists")
        self.assertTrue(close_filter(owner, 5, (7,), detach_verified=True))
        owner.close.assert_called_once()
        owner.query_program_ids.assert_not_called()

    def test_missing_detach_proof_cannot_use_collected_cgroup_as_success(self):
        owner = Mock(link_fd=None)
        owner.query_program_ids.side_effect = OSError("cgroup no longer exists")
        self.assertFalse(close_filter(owner, 5, (7,), detach_verified=False))

    def test_open_link_requires_fresh_cleanup_readback(self):
        owner = Mock(link_fd=9)
        owner.query_program_ids.return_value = (7, 8)
        self.assertFalse(close_filter(owner, 5, (7,), detach_verified=True))
        owner.query_program_ids.assert_called_once_with(5)

    def test_descriptor_close_failure_remains_inconclusive(self):
        owner = Mock(link_fd=None)
        owner.close.side_effect = OSError("close failed")
        self.assertFalse(close_filter(owner, 5, (7,), detach_verified=True))
