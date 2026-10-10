"""Fixed-category tunnel diagnostics preserve failures and never replay writes."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from regear.delivery.whole_dock_runtime import TopologyRefused, WholeDockRuntime


class TunnelStageDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.runtime = object.__new__(WholeDockRuntime)
        self.runtime.binding = SimpleNamespace(
            binding="binding", generation="generation", router_target="router")
        self.runtime._operation = "operation"
        self.runtime._before_deauthorize = Mock(return_value=True)
        self.runtime._guard = Mock(return_value=True)
        self.runtime._writer = SimpleNamespace(deauthorize=Mock())
        self.runtime._admission = Mock(return_value=True)
        self.runtime._idle = Mock(return_value=True)
        self.runtime._owned = Mock(return_value=True)
        self.runtime.observe = Mock(return_value=object())
        self.runtime._monotonic = Mock(return_value=0)
        self.runtime._wait = Mock()
        self.observation = object()

    def assert_failure(self, error, stage, code, writes):
        with self.assertRaises(type(error)) as caught:
            self.runtime.deauthorize(self.observation)
        self.assertIs(caught.exception, error)
        self.assertEqual(self.runtime.tunnel_stage, stage)
        self.assertEqual(self.runtime.tunnel_code, code)
        self.assertNotIn("private-detail", self.runtime.tunnel_code)
        self.assertEqual(self.runtime._writer.deauthorize.call_count, writes)

    def test_hold_exception_is_categorical_and_never_writes(self):
        error = RuntimeError("private-detail UUID/path")
        self.runtime._before_deauthorize.side_effect = error
        self.assert_failure(error, "authorization_hold",
                            "dock_teardown.authorization_hold_unverified", 0)
        self.runtime.observe.assert_not_called()

    def test_write_exception_is_preserved_and_never_replayed(self):
        error = OSError("private-detail UUID/path")
        self.runtime._writer.deauthorize.side_effect = error
        self.assert_failure(error, "deauthorization_write",
                            "dock_teardown.deauthorization_write_unverified", 1)
        self.runtime.observe.assert_not_called()

    def test_unexpected_topology_failure_does_not_wait_or_replay(self):
        error = TopologyRefused("private-detail UUID/path")
        self.runtime.observe.side_effect = error
        self.assert_failure(error, "settle",
                            "dock_teardown.tunnel_settle_unverified", 1)
        self.runtime._wait.assert_not_called()

    def test_unknown_exception_text_is_not_exposed_as_reason(self):
        self.runtime.observe.side_effect = OSError('private-detail path UUID')
        with self.assertRaises(OSError):
            self.runtime.deauthorize(self.observation)
        self.assertEqual(self.runtime.tunnel_reason, 'dock_teardown.observation_unknown')

    def test_identity_refusal_is_preserved_as_fixed_reason(self):
        self.runtime.observe.side_effect = TopologyRefused('dock_topology.anchor_changed')
        with self.assertRaises(TopologyRefused):
            self.runtime.deauthorize(self.observation)
        self.assertEqual(self.runtime.tunnel_reason, 'dock_topology.anchor_changed')
        self.runtime._wait.assert_not_called()

    def test_existing_settle_timeout_and_original_cause_are_preserved(self):
        error = TopologyRefused("dock_topology.pci_branch_remains")
        error.remaining_pci = {'bridges': 3, 'endpoints': 0, 'unreadable': 0}
        self.runtime.observe.side_effect = error
        self.runtime._monotonic.side_effect = [0, 35]
        with self.assertRaisesRegex(ValueError, "tunnel_settle_timeout") as caught:
            self.runtime.deauthorize(self.observation)
        self.assertIs(caught.exception.__cause__, error)
        self.assertEqual(self.runtime.remaining_pci, error.remaining_pci)
        self.assertEqual(self.runtime.tunnel_stage, "settle")
        self.assertEqual(self.runtime.tunnel_code,
                         "dock_teardown.tunnel_settle_unverified")
        self.assertEqual(self.runtime.tunnel_reason, 'dock_teardown.tunnel_settle_timeout')
        self.runtime._writer.deauthorize.assert_called_once()
        self.runtime._wait.assert_not_called()

    def test_observed_28_second_bridge_cleanup_finishes_without_replaying_write(self):
        clock = [0.0]
        error = TopologyRefused('dock_topology.pci_branch_remains')
        error.remaining_pci = {'bridges': 6, 'endpoints': 0, 'unreadable': 0}
        def observe():
            if clock[0] < 28.075:
                raise error
            return object()
        self.runtime._monotonic = lambda: clock[0]
        self.runtime._wait = Mock(side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
        self.runtime.observe.side_effect = observe
        self.runtime.deauthorize(self.observation)
        self.assertEqual(clock[0], 28.5)
        self.assertEqual(self.runtime.tunnel_stage, 'completed')
        self.runtime._writer.deauthorize.assert_called_once()

    def test_persistent_bridges_stop_at_35_seconds(self):
        clock = [0.0]
        self.runtime._monotonic = lambda: clock[0]
        self.runtime._wait = Mock(side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
        self.runtime.observe.side_effect = TopologyRefused('dock_topology.pci_branch_remains')
        with self.assertRaisesRegex(ValueError, 'tunnel_settle_timeout'):
            self.runtime.deauthorize(self.observation)
        self.assertEqual(clock[0], 35.0)
        self.assertEqual(self.runtime._wait.call_count, 70)
        self.runtime._writer.deauthorize.assert_called_once()

    def test_success_clears_previous_failure_and_keeps_boundary_order(self):
        self.runtime.tunnel_code = "old_failure"
        stages = []
        self.runtime._before_deauthorize.side_effect = lambda *args: (
            stages.append(self.runtime.tunnel_stage) or True)
        self.runtime._writer.deauthorize.side_effect = lambda *args: (
            stages.append(self.runtime.tunnel_stage))
        self.runtime.observe.side_effect = lambda: (
            stages.append(self.runtime.tunnel_stage))
        self.runtime.deauthorize(self.observation)
        self.assertEqual(stages, ["authorization_hold", "deauthorization_write", "settle"])
        self.assertEqual(self.runtime.tunnel_stage, "completed")
        self.assertEqual(self.runtime.tunnel_code, "")
        self.runtime._writer.deauthorize.assert_called_once()


if __name__ == "__main__":
    unittest.main()
