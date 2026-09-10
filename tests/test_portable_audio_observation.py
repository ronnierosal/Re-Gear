import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.adapters.steamos.portable_audio_observation import parse_portable_default


BDF, SINK = '0000:64:00.6', 'alsa_loopback_device.alsa_output.pci-0000_64_00.6.analog-stereo'


class PortableAudioObservationTests(unittest.TestCase):
    def setUp(self):
        self.values = [
            {'id': 0, 'type': 'PipeWire:Interface:Core'},
            {'id': 50, 'type': 'PipeWire:Interface:Device', 'info': {'props': {
                'device.bus-path': 'pci-' + BDF, 'device.api': 'alsa', 'device.bus': 'pci'}}},
            {'id': 62, 'type': 'PipeWire:Interface:Node', 'info': {'props': {
                'node.name': SINK, 'device.id': 50, 'media.class': 'Audio/Sink', 'alsa.loopback': True}}},
            {'id': 41, 'type': 'PipeWire:Interface:Metadata', 'props': {'metadata.name': 'default'},
             'metadata': [{'subject': 0, 'key': 'default.audio.sink', 'type': 'Spa:String:JSON',
                           'value': {'name': SINK}},
                          {'subject': 0, 'key': 'default.configured.audio.sink',
                           'value': {'name': 'different.configured.sink'}}]}]

    def parse(self, values=None, **kwargs):
        return parse_portable_default(json.dumps(self.values if values is None else values),
            sink_name=kwargs.get('sink_name', SINK), audio_bdf=kwargs.get('audio_bdf', BDF))

    def test_actual_default_with_exact_internal_binding(self):
        result = self.parse()
        self.assertTrue(result.ready)
        self.assertEqual((result.sink_name, result.device_bdf, result.device_id, result.sink_id),
                         (SINK, BDF, 50, 62))

    def test_configured_default_is_not_actual(self):
        self.values[3]['metadata'][0]['value']['name'] = 'external.sink'
        self.values[3]['metadata'][1]['value']['name'] = SINK
        self.assertFalse(self.parse().ready)
        self.values[3]['metadata'].pop(0)
        self.assertFalse(self.parse().ready)

    def test_non_g1_does_not_mean_internal(self):
        self.assertFalse(self.parse(audio_bdf='0000:65:00.6').ready)
        self.values[2]['info']['props']['device.id'] = 51
        self.assertFalse(self.parse().ready)

    def test_device_and_sink_duplicates_rejected(self):
        for index in (1, 2, 3):
            values = copy.deepcopy(self.values)
            duplicate = copy.deepcopy(values[index])
            duplicate['id'] = 99
            values.append(duplicate)
            self.assertFalse(self.parse(values).ready)

    def test_duplicate_object_ids_even_unrelated(self):
        self.values.append({'id': 50, 'type': 'PipeWire:Interface:Client'})
        self.assertFalse(self.parse().ready)

    def test_metadata_subject_and_identity_required(self):
        for subject in (True, '0', 1, -1, None):
            values = copy.deepcopy(self.values)
            values[3]['metadata'][0]['subject'] = subject
            self.assertFalse(self.parse(values).ready)
        for name in ('other', None):
            values = copy.deepcopy(self.values)
            values[3]['props']['metadata.name'] = name
            self.assertFalse(self.parse(values).ready)

    def test_metadata_info_properties_cannot_replace_actual_top_level_properties(self):
        self.values[3]['info'] = {'props': self.values[3].pop('props')}
        result = self.parse()
        self.assertFalse(result.ready)
        self.assertEqual(result.code, 'portable_audio.properties_unavailable')

    def test_duplicate_metadata_is_ambiguous_even_equal(self):
        self.values[3]['metadata'].append(copy.deepcopy(self.values[3]['metadata'][0]))
        self.assertFalse(self.parse().ready)

    def test_missing_properties_no_defaults(self):
        for index, key in ((1, 'device.api'), (1, 'device.bus'), (1, 'device.bus-path'),
                           (2, 'device.id'), (2, 'media.class'), (2, 'node.name')):
            values = copy.deepcopy(self.values)
            del values[index]['info']['props'][key]
            self.assertFalse(self.parse(values).ready)

    def test_boolean_and_malformed_numeric_ids(self):
        for value in (True, -1, '50', 2**32):
            values = copy.deepcopy(self.values)
            values[1]['id'] = value
            self.assertFalse(self.parse(values).ready)
            values = copy.deepcopy(self.values)
            values[2]['info']['props']['device.id'] = value
            self.assertFalse(self.parse(values).ready)

    def test_invalid_inputs_and_bounded_data(self):
        for raw in (b'\xff', '{}', 'null', '[{"id":0,"id":1}]', '[' * 1500,
                    'x' * (1024 * 1024 + 1)):
            self.assertFalse(parse_portable_default(raw, sink_name=SINK, audio_bdf=BDF).ready)
        self.assertFalse(self.parse([{'id': n} for n in range(4097)]).ready)
        for sink in (True, '', SINK + '\n'):
            self.assertFalse(self.parse(sink_name=sink).ready)
        for bdf in (True, '', '0000:64:ff.6', BDF + '\n'):
            self.assertFalse(self.parse(audio_bdf=bdf).ready)

    def test_sink_source_cannot_be_default_playback_evidence(self):
        self.values[2]['info']['props']['media.class'] = 'Audio/Source'
        self.assertFalse(self.parse().ready)


if __name__ == '__main__':
    unittest.main()
