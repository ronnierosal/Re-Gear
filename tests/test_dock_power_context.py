"""Button-context observation uses real RPC routing without power or state writes."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module


class PowerContextTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)
        self.plugin._unloading = False
        self.plugin._background_operations = set()
        self.plugin._dock_mutation_gate = Mock(side_effect=AssertionError('mutation gate'))
        self.plugin._run_whole_dock_trial = Mock(side_effect=AssertionError('teardown'))
        self.plugin._run_dock_power_request = Mock(side_effect=AssertionError('power'))

    def read(self):
        return asyncio.run(self.plugin.get_egpu_disconnect_status('power_context'))

    def test_absent_is_explicit_and_never_discovers_gpu_or_admits(self):
        with patch.object(self.module, 'verified_transport_absent', return_value=True), \
             patch.object(self.module, 'DrmDiscovery') as discovery:
            result = self.read()
        self.assertEqual((result['context'], result['attachment_token']), ('absent', ''))
        self.assertEqual(result['schema_version'], 1)
        self.assertIn('+00:00', result['observed_at'])
        discovery.assert_not_called()
        self.plugin._dock_mutation_gate.assert_not_called()

    def test_attached_identity_does_not_require_hdmi_or_game_readiness(self):
        with patch.object(self.module, 'verified_transport_absent', return_value=False), \
             patch.object(self.module, 'DrmDiscovery') as discovery, \
             patch.object(self.module, 'resolve_whole_dock', return_value=NS(
                 binding='binding', generation='generation')):
            discovery.return_value.scan.return_value = [NS(boot_vga=False, pci_bdf='gpu')]
            result = self.read()
        self.assertEqual((result['context'], result['attachment_token']),
                         ('attached', 'binding:generation'))

    def test_missing_gpu_or_resolver_error_is_unknown_not_absent(self):
        with patch.object(self.module, 'verified_transport_absent', return_value=False), \
             patch.object(self.module, 'DrmDiscovery') as discovery, \
             patch.object(self.module, 'resolve_whole_dock', side_effect=ValueError('private')):
            for cards in ([], [NS(boot_vga=False, pci_bdf='gpu')]):
                discovery.return_value.scan.return_value = cards
                result = self.read()
                self.assertEqual(result['context'], 'unknown')
                self.assertIsNone(result['attachment_token'])
                self.assertNotIn('private', str(result))

    def test_busy_or_unloading_does_not_start_observation(self):
        with patch.object(self.module, 'verified_transport_absent') as absent:
            self.plugin._background_operations = {'operation'}
            self.assertEqual(self.read()['context'], 'unknown')
            self.plugin._background_operations = set()
            self.plugin._unloading = True
            self.assertEqual(self.read()['context'], 'unknown')
            absent.assert_not_called()

    def test_already_down_requires_retained_preview_not_status_string(self):
        self.plugin._whole_dock_trial_status = {'code': 'dock_teardown.software_down'}
        with patch.object(self.module, 'verified_transport_absent', return_value=False), \
             patch.object(self.module, 'DrmDiscovery') as discovery:
            discovery.return_value.scan.return_value = []
            self.assertEqual(self.read()['context'], 'unknown')
            runtime = NS(preview_power_continuation=Mock(return_value=True))
            admission = {'held': False}
            self.plugin._whole_dock_trial_runtime = (runtime, admission)
            result = self.read()
            self.assertEqual((result['context'], result['attachment_token']), ('already_down', ''))
            self.assertFalse(admission['held'])
            self.plugin._dock_mutation_gate.assert_not_called()


class ContinuationPreviewTests(unittest.TestCase):
    def setUp(self):
        from regear.delivery.whole_dock_runtime import WholeDockRuntime
        from regear.delivery.whole_dock_claim import WholeDockClaim
        self.runtime = WholeDockRuntime.__new__(WholeDockRuntime)
        self.runtime._operation = 'operation'
        self.runtime.binding = NS(binding='binding', generation='generation')
        self.claim = WholeDockClaim('operation', 'binding', 'generation', 'software_down')
        self.runtime._store = Mock()
        self.runtime._store.read_snapshot.return_value = self.claim
        self.runtime._idle = lambda: True
        self.runtime.observe = Mock(return_value=NS(binding='binding', generation='generation', topology_complete=True,
            gpu_scan_complete=True, gpu_functions_present=(),
            usb=NS(present=False, scan_complete=True, storage_scan_complete=True,
                   mounted_storage=(), storage_in_use=()), tunnel=NS(authorized=False)))

    def test_preview_requires_same_claim_before_and_after_without_admission(self):
        self.assertTrue(self.runtime.preview_power_continuation(portable_verified=lambda: True))
        self.runtime._store.load.assert_not_called()
        self.runtime._store.read_snapshot.side_effect = [self.claim, None]
        self.assertFalse(self.runtime.preview_power_continuation(portable_verified=lambda: True))

    def test_incomplete_observation_or_changed_portable_state_refuses(self):
        portable = Mock(side_effect=[True, False])
        self.assertFalse(self.runtime.preview_power_continuation(portable_verified=portable))
        self.runtime.observe.return_value.usb.storage_scan_complete = False
        self.assertFalse(self.runtime.preview_power_continuation(portable_verified=lambda: True))

    def test_changed_observation_identity_refuses(self):
        self.runtime.observe.return_value.generation = 'replacement'
        self.assertFalse(self.runtime.preview_power_continuation(portable_verified=lambda: True))


@unittest.skipUnless(sys.platform == 'linux', 'Linux directory-fd filesystem contract')
class ClaimSnapshotReadOnlyTests(unittest.TestCase):
    def test_existing_claim_read_creates_no_files_and_opens_no_write_descriptors(self):
        from regear.delivery.whole_dock_claim import WholeDockClaim, WholeDockClaimStore, FILENAME
        with tempfile.TemporaryDirectory() as root:
            os.chmod(root, 0o700)
            claim = WholeDockClaim('operation', 'binding', 'generation', 'software_down')
            path = Path(root) / FILENAME
            path.write_bytes(WholeDockClaimStore._encode(claim))
            os.chmod(path, 0o600)
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                store = WholeDockClaimStore(Path(root), owner_uid=os.geteuid(), trusted_directory_fd=fd)
                original = os.open
                def readonly_open(path, flags, *args, **kwargs):
                    self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                    return original(path, flags, *args, **kwargs)
                with patch('os.open', side_effect=readonly_open):
                    self.assertEqual(store.read_snapshot(), claim)
                self.assertEqual(list(Path(root).iterdir()), [path])
            finally:
                os.close(fd)
