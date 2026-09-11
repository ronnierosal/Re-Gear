"""Composition fixtures only: no hardware or privileged filesystem writes."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from regear.delivery import whole_dock_runtime as module
from regear.adapters.steamos.dock_branch import DockUsbReading, DockStorageReading
from regear.domain.dock_teardown import TeardownApproval
from regear.ports.whole_dock_teardown import WholeDockApproval
from regear.application.live_disconnect import LiveDisconnectResult, LiveDisconnectStage


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.binding = SimpleNamespace(binding='bound', generation='generation',
            gpu_bdf='gpu', audio_bdf='audio', usb_bdf='usb', router_id='router',
            usb_target='usb-target', router_target='router-target')
        self.names = {'usb'}
        self.authorized = True
        self.admitted = True
        self.claim = None
        self.events = []
        self.devices = ()
        self.storage = DockStorageReading((), (), True)
        self.store = Mock()
        self.store.load.side_effect = lambda: self.claim
        def claim(operation, binding, generation):
            if self.claim is not None:
                return False
            self.claim = SimpleNamespace(operation=operation, binding=binding,
                                         generation=generation, stage='claimed')
            return True
        self.store.claim.side_effect = claim
        def record(operation, stage):
            self.claim.stage = stage
            self.events.append(stage)
        self.store.record.side_effect = record
        discovery = Mock()
        discovery.observe_usb.side_effect = lambda bdf: DockUsbReading(
            bdf, 'usb' in self.names, True, self.devices)
        discovery.observe_storage.side_effect = lambda bdf: self.storage
        self.writer = Mock()
        def remove(target, guard):
            if guard() is not True:
                raise ValueError('refused')
            self.events.append('remove')
            self.names.remove('usb')
        def deauthorize(target, guard):
            if guard() is not True:
                raise ValueError('refused')
            self.events.append('deauthorize')
            self.authorized = False
        self.writer.remove_usb.side_effect = remove
        self.writer.deauthorize.side_effect = deauthorize
        patches = {
            'WholeDockClaimStore': Mock(return_value=self.store),
            'WholeDockSysfsWriter': Mock(return_value=self.writer),
            'DockBranchDiscovery': Mock(return_value=discovery),
            '_pci_names': Mock(side_effect=lambda: set(self.names)),
            '_authorization': Mock(side_effect=lambda b: (self.authorized, True)),
            'revalidate_retained': Mock(return_value=True),
        }
        patcher = patch.multiple(module, **patches)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runtime = module.WholeDockRuntime(self.binding, '/unused',
            idle=lambda: True, admission_held=lambda: self.admitted)
        self.approval = WholeDockApproval('bound', 'generation',
            TeardownApproval('usb', 'router'))

    def test_ordered_post_gpu_success_retains_claim(self):
        result = self.runtime.execute('operation', self.approval)
        self.assertTrue(result.software_down)
        self.assertFalse(result.safe_to_unplug)
        self.assertEqual(self.events, ['prepared', 'usb_remove_intent', 'remove',
            'usb_removed', 'tunnel_remove_intent', 'deauthorize', 'software_down'])
        self.assertIsNotNone(self.claim)

    def test_denied_admission_prevents_claim(self):
        self.admitted = False
        self.assertFalse(self.runtime.execute('operation', self.approval).software_down)
        self.store.claim.assert_not_called()

    def test_any_peripheral_blocks_even_with_no_mount(self):
        self.devices = (object(),)
        self.assertFalse(self.runtime.execute('operation', self.approval).software_down)
        self.store.claim.assert_not_called()

    def test_mounted_or_incomplete_storage_blocks(self):
        for storage in (DockStorageReading(('/mount',), (), True),
                        DockStorageReading((), (), False)):
            self.storage = storage
            self.assertFalse(self.runtime.execute('operation', self.approval).software_down)
        self.store.claim.assert_not_called()

    def test_wrong_claim_refuses_writer_guard(self):
        observation = self.runtime.observe()
        self.assertTrue(self.runtime.claim('operation', observation))
        self.runtime.record('operation', 'usb_remove_intent')
        self.claim.generation = 'replacement'
        with self.assertRaises(ValueError):
            self.runtime.remove_usb(observation)
        self.assertNotIn('remove', self.events)

    def test_gpu_arrival_at_write_guard_blocks(self):
        observation = self.runtime.observe()
        self.runtime.claim('operation', observation)
        self.runtime.record('operation', 'usb_remove_intent')
        self.names.add('gpu')
        with self.assertRaises(ValueError):
            self.runtime.remove_usb(observation)
        self.assertNotIn('remove', self.events)

    def test_admission_lost_after_claim_blocks_record(self):
        self.runtime.claim('operation', self.runtime.observe())
        self.admitted = False
        with self.assertRaises(ValueError):
            self.runtime.record('operation', 'prepared')

    def test_observer_failure_is_unresolved_no_write(self):
        with patch.object(module, '_pci_names', side_effect=PermissionError()):
            self.assertEqual(self.runtime.execute('operation', self.approval).code,
                             'dock_teardown.unresolved')
        self.writer.remove_usb.assert_not_called()

    def begin(self):
        self.names.update(('gpu', 'audio'))
        self.runtime.begin_before_release('operation', self.approval)

    def removed_result(self):
        return LiveDisconnectResult(LiveDisconnectStage.REMOVED, 'removed',
                                    removed=('gpu', 'audio'))

    def test_preclaim_release_and_one_use_continuation(self):
        self.begin()
        self.assertEqual(self.claim.stage, 'release_intent')
        self.names.difference_update(('gpu', 'audio'))
        self.runtime.verify_gpu_release(self.removed_result())
        result = self.runtime.execute_claimed('operation', self.approval)
        self.assertTrue(result.software_down)
        self.assertEqual(self.store.claim.call_count, 1)
        with self.assertRaises(ValueError):
            self.runtime.execute_claimed('operation', self.approval)

    def test_begin_requires_present_functions(self):
        with self.assertRaises(ValueError):
            self.runtime.begin_before_release('operation', self.approval)
        self.store.claim.assert_not_called()

    def test_release_receipt_does_not_override_present_gpu(self):
        self.begin()
        with self.assertRaises(ValueError):
            self.runtime.verify_gpu_release(self.removed_result())
        self.assertEqual(self.claim.stage, 'release_intent')

    def test_failed_or_wrong_release_result_refused(self):
        self.begin()
        self.names.difference_update(('gpu', 'audio'))
        for result in (LiveDisconnectResult(LiveDisconnectStage.PRIOR_REMOVAL_COMPLETE, 'prior'),
                       LiveDisconnectResult(LiveDisconnectStage.REMOVED, 'wrong', removed=('other',)),
                       SimpleNamespace(ok=True)):
            with self.assertRaises(ValueError):
                self.runtime.verify_gpu_release(result)

    def test_continuation_cannot_adopt_existing_claim(self):
        self.begin()
        self.names.difference_update(('gpu', 'audio'))
        self.runtime.verify_gpu_release(self.removed_result())
        fresh = module.WholeDockRuntime(self.binding, '/unused',
            idle=lambda: True, admission_held=lambda: True)
        with self.assertRaises(ValueError):
            fresh.execute_claimed('operation', self.approval)

    def test_wrong_consent_and_lost_admission_refuse_continuation(self):
        self.begin()
        self.names.difference_update(('gpu', 'audio'))
        self.runtime.verify_gpu_release(self.removed_result())
        with self.assertRaises(ValueError):
            self.runtime.execute_claimed('operation', WholeDockApproval('wrong', 'generation',
                                        self.approval.teardown))
        self.admitted = False
        with self.assertRaises(ValueError):
            self.runtime.execute_claimed('operation', self.approval)


if __name__ == '__main__':
    unittest.main()
