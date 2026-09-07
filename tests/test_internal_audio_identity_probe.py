import contextlib
from dataclasses import replace
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.probe_internal_audio_identity import capture, main
from hdm.adapters.steamos.host import HostRecord
from hdm.adapters.steamos.pci import PciDeviceRecord


class InternalAudioIdentityProbeTests(unittest.TestCase):
    def setUp(self):
        self.gpu = PciDeviceRecord('0000:64:00.0', '0x1002', '0x15bf', '0x030000',
                                    'amdgpu', ('0000:00:08.1',))
        self.audio = PciDeviceRecord('0000:64:00.6', '0x1022', '0x15e3', '0x040300',
                                      'snd_hda_intel', ('0000:00:08.1',))
        self.device = {'id': 50, 'type': 'PipeWire:Interface:Device', 'info': {
            'props': {'device.bus-path': 'pci-' + self.audio.bdf, 'device.api': 'alsa',
                      'device.bus': 'pci', 'device.serial': 'SECRET-SERIAL',
                      'arbitrary.path': '/private/secret'},
            'params': {'EnumProfile': [{'index': 0, 'name': 'off', 'available': 'yes'},
                         {'index': 1, 'name': 'output:analog-stereo', 'available': 'yes'}],
                       'Profile': [{'index': 1, 'name': 'output:analog-stereo'}]}}}
        self.commands = Mock()
        self.commands.dump.return_value = SimpleNamespace(ok=True, output=json.dumps([self.device]).encode())
        self.sources = dict(
            pci=SimpleNamespace(scan_pci=lambda: (self.gpu, self.audio)),
            drm=SimpleNamespace(scan=lambda: (SimpleNamespace(boot_vga=True, pci_bdf=self.gpu.bdf,
                                                               connectors=(SimpleNamespace(internal=True),)),)),
            host=SimpleNamespace(scan=lambda: HostRecord('ASUSTeK COMPUTER INC.', 'ROG Ally X RC72LA', 'RC72LA')),
            gamescope=SimpleNamespace(scan=lambda: object()),
            resolve_user=lambda _: SimpleNamespace(ok=True, context=SimpleNamespace(username='SECRET-USER')),
            commands=self.commands)

    def test_relationship_evidence_never_certifies_internal_audio(self):
        report = capture(**self.sources)
        self.assertFalse(report['internal_audio_verified'])
        self.assertFalse(report['disconnect_clearance'])
        self.assertTrue(report['ally_x_host_match'])
        row = report['pipewire_audio_devices'][0]
        self.assertEqual(row['pci']['bdf'], self.audio.bdf)
        self.assertEqual(row['pci']['ancestry'], ['0000:00:08.1'])
        self.assertEqual(row['selected_profile']['name'], 'output:analog-stereo')
        self.assertEqual(row['same_pci_slot_as_gpu_candidates'], [self.gpu.bdf])
        self.assertEqual(self.commands.method_calls, [unittest.mock.call.dump(unittest.mock.ANY)])

    def test_no_raw_properties_paths_or_usernames(self):
        rendered = json.dumps(capture(**self.sources))
        for secret in ('SECRET-SERIAL', 'SECRET-USER', '/private/secret', 'device.serial', 'arbitrary.path'):
            self.assertNotIn(secret, rendered)

    def test_unprivileged_retains_pci_evidence(self):
        self.commands.dump.return_value = SimpleNamespace(ok=False, code='audio.root_required')
        report = capture(**self.sources)
        self.assertEqual(report['errors'], ['audio.root_required'])
        self.assertEqual(report['pci_audio_devices'][0]['bdf'], self.audio.bdf)
        self.assertEqual(report['internal_gpu_candidates'][0]['bdf'], self.gpu.bdf)
        self.assertEqual(report['pipewire_audio_devices'], [])

    def test_resolution_failure_does_not_dump(self):
        self.sources['resolve_user'] = lambda _: SimpleNamespace(ok=False, context=None)
        report = capture(**self.sources)
        self.assertIn('gamescope_user_unresolved', report['errors'])
        self.commands.dump.assert_not_called()

    def test_missing_exact_pipewire_bdf_no_guess(self):
        self.device['info']['props']['device.bus-path'] = 'pci-0000:63:00.6'
        self.commands.dump.return_value.output = json.dumps([self.device]).encode()
        report = capture(**self.sources)
        row = report['pipewire_audio_devices'][0]
        self.assertEqual(row['profile_observation_code'], 'audio_profile.device_ambiguous')
        self.assertNotIn('selected_profile', row)

    def test_duplicate_pci_fail_closed(self):
        self.sources['pci'] = SimpleNamespace(scan_pci=lambda: (self.gpu, self.audio, self.audio))
        report = capture(**self.sources)
        self.assertIn('pci_drm_observation_unavailable', report['errors'])
        self.commands.dump.assert_not_called()

    def test_audio_inventory_bound_prevents_repeated_dump_parsing(self):
        audio = tuple(replace(self.audio, bdf=f'0000:{index:02x}:00.6') for index in range(65))
        self.sources['pci'] = SimpleNamespace(scan_pci=lambda: (self.gpu, *audio))
        report = capture(**self.sources)
        self.assertIn('pci_drm_observation_unavailable', report['errors'])
        self.commands.dump.assert_not_called()

    def test_missing_internal_connector_not_a_gpu_candidate(self):
        self.sources['drm'] = SimpleNamespace(scan=lambda: (SimpleNamespace(boot_vga=True,
                                                    pci_bdf=self.gpu.bdf, connectors=()),))
        report = capture(**self.sources)
        self.assertEqual(report['internal_gpu_candidates'], [])
        self.assertEqual(report['pipewire_audio_devices'][0]['same_pci_slot_as_gpu_candidates'], [])

    def test_linux_guard_prevents_discovery(self):
        with patch('scripts.probe_internal_audio_identity.sys.platform', 'win32'), \
             patch('scripts.probe_internal_audio_identity.sys.argv', ['probe']), \
             patch('scripts.probe_internal_audio_identity.DrmDiscovery') as discovery, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(), 1)
        discovery.assert_not_called()
        self.assertFalse(json.loads(output.getvalue())['internal_audio_verified'])

    def test_unknown_arguments_never_start_discovery(self):
        with patch('scripts.probe_internal_audio_identity.sys.argv', ['probe', '--other']), \
             patch('scripts.probe_internal_audio_identity.DrmDiscovery') as discovery:
            with self.assertRaises(SystemExit):
                main()
            discovery.assert_not_called()


if __name__ == '__main__':
    unittest.main()
