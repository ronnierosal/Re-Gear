import json
import unittest
from unittest.mock import Mock,patch
from scripts import probe_disconnect_runtime_prerequisites as probe


class RuntimePrerequisiteTests(unittest.TestCase):
    def test_report_never_contains_symbol_values_or_claims_filter(self):
        secret=12345678901234567890
        with patch.object(probe.platform,'system',return_value='Linux'), \
             patch.object(probe.platform,'machine',return_value='x86_64'), \
             patch.object(probe,'parse_dma_buf_receive_btf'):
            result=probe.capture(read_btf=lambda:b'fixture',read_symbols=lambda:probe.ReceiveSymbols(secret,secret+8),
                audio=lambda:dict(ready=True))
        self.assertEqual(result['code'],'prerequisites_observed')
        self.assertNotIn(str(secret),json.dumps(result))
        self.assertIs(result['dma_filter_verified'],False)
        self.assertIs(result['disconnect_clearance'],False)

    def test_unavailable_symbols_preserve_independent_audio_evidence(self):
        with patch.object(probe.platform,'system',return_value='Linux'), \
             patch.object(probe.platform,'machine',return_value='x86_64'), \
             patch.object(probe,'parse_dma_buf_receive_btf'):
            result=probe.capture(read_btf=lambda:b'fixture',read_symbols=Mock(side_effect=ValueError('hidden')),
                                 audio=lambda:dict(ready=False,code='context_unavailable'))
        self.assertEqual(result['code'],'prerequisites_incomplete')
        self.assertEqual(result['audio']['code'],'context_unavailable')
        self.assertFalse(result['dma_symbols_ready'])

    def test_unsupported_platform_does_not_read(self):
        read=Mock()
        with patch.object(probe.platform,'system',return_value='Windows'):
            result=probe.capture(read_btf=read,read_symbols=read,audio=read)
        self.assertEqual(result['code'],'unsupported_platform')
        read.assert_not_called()
