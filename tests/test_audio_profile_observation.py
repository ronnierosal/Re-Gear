import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from hdm.adapters.steamos.audio_profile_observation import parse_audio_profile_observation


BDF = '0000:08:00.1'


class AudioProfileObservationTests(unittest.TestCase):
    def setUp(self):
        self.device = {'id': 42, 'type': 'PipeWire:Interface:Device', 'info': {
            'props': {'device.bus-path': 'pci-' + BDF, 'device.api': 'alsa', 'device.bus': 'pci'},
            'params': {'EnumProfile': [
                {'index': 0, 'name': 'off', 'available': 'yes'},
                {'index': 2, 'name': 'output:hdmi-stereo-extra1', 'available': 'yes'}],
                'Profile': [{'index': 2, 'name': 'output:hdmi-stereo-extra1'}]}}}

    def parse(self, values=None, bdf=BDF):
        return parse_audio_profile_observation(json.dumps(values if values is not None else [self.device]), audio_bdf=bdf)

    def test_observed_profile_names_indexes_and_core_zero(self):
        result = self.parse([{'id': 0, 'type': 'PipeWire:Interface:Core'}, self.device])
        self.assertTrue(result.ready)
        self.assertEqual(result.device_id, 42)
        self.assertEqual(result.device_bdf, BDF)
        self.assertEqual((result.current_profile.name, result.current_profile.index),
                         ('output:hdmi-stereo-extra1', 2))
        self.assertEqual(result.off_profile.name, 'off')

    def test_no_hardcoded_indexes(self):
        params = self.device['info']['params']
        params['EnumProfile'][0]['index'] = 5
        params['EnumProfile'][1]['index'] = 9
        params['Profile'][0]['index'] = 9
        result = self.parse()
        self.assertTrue(result.ready)
        self.assertEqual(result.off_profile.index, 5)
        self.assertEqual(result.current_profile.index, 9)

    def test_exact_bdf_required(self):
        self.assertFalse(self.parse(bdf='0000:09:00.1').ready)
        for bdf in ('', True, 'pci-' + BDF, BDF + '\n'):
            self.assertFalse(self.parse(bdf=bdf).ready)

    def test_ambiguous_devices_and_ids(self):
        other = copy.deepcopy(self.device)
        other['id'] = 43
        self.assertFalse(self.parse([self.device, other]).ready)
        other['info']['props']['device.bus-path'] = 'pci-0000:09:00.1'
        other['id'] = 42
        self.assertFalse(self.parse([self.device, other]).ready)

    def test_no_fabricated_defaults(self):
        for key in ('device.api', 'device.bus', 'device.bus-path'):
            device = copy.deepcopy(self.device)
            del device['info']['props'][key]
            self.assertFalse(self.parse([device]).ready)
        for key in ('EnumProfile', 'Profile'):
            device = copy.deepcopy(self.device)
            del device['info']['params'][key]
            self.assertFalse(self.parse([device]).ready)

    def test_invalid_or_duplicate_profiles(self):
        for key, value in (('index', True), ('index', -1), ('index', '0'),
                           ('index', 2**32), ('name', ''), ('name', 'off\n'),
                           ('available', True), ('available', None)):
            device = copy.deepcopy(self.device)
            device['info']['params']['EnumProfile'][0][key] = value
            self.assertFalse(self.parse([device]).ready)
        for key, value in (('index', 0), ('name', 'off')):
            device = copy.deepcopy(self.device)
            device['info']['params']['EnumProfile'][1][key] = value
            self.assertFalse(self.parse([device]).ready)

    def test_current_profile_exact_and_unique(self):
        for selected in ([], [{}, {}], [{'index': True, 'name': 'off'}],
                         [{'index': 2, 'name': 'off'}], [{'index': 7, 'name': 'missing'}]):
            device = copy.deepcopy(self.device)
            device['info']['params']['Profile'] = selected
            self.assertFalse(self.parse([device]).ready)

    def test_unavailable_off_rejected_and_already_off_observed(self):
        for available in ('no', 'unknown'):
            self.device['info']['params']['EnumProfile'][0]['available'] = available
            self.assertFalse(self.parse().ready)
        self.device['info']['params']['EnumProfile'][0]['available'] = 'yes'
        self.device['info']['params']['Profile'] = [{'index': 0, 'name': 'off'}]
        self.assertTrue(self.parse().ready)

    def test_strict_device_id(self):
        for value in (True, '42', -1, 0, 2**32):
            self.device['id'] = value
            self.assertFalse(self.parse().ready)

    def test_dump_bounds_and_malformed(self):
        for raw in (b'\xff', '{', '{}', 'x' * (1024 * 1024 + 1),
                    '[{"id":42,"id":43}]', '[' * 1500, 'null'):
            self.assertFalse(parse_audio_profile_observation(raw, audio_bdf=BDF).ready)
        self.assertFalse(self.parse([{'id': i} for i in range(4097)]).ready)
        self.device['info']['params']['EnumProfile'] *= 129
        self.assertFalse(self.parse().ready)


if __name__ == '__main__':
    unittest.main()
