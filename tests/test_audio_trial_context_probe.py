import contextlib
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.probe_audio_trial_context import capture, portable_baseline, main
from hdm.adapters.steamos.audio_trial_observer import AudioTrialContext
from hdm.adapters.steamos.drm import DrmCardRecord, DrmConnectorRecord
from hdm.adapters.steamos.pci import PciDeviceRecord
from hdm.adapters.steamos.host import HostRecord


BDF='0000:64:00.6'
SINK='private.portable.sink'


class AudioTrialContextProbeTests(unittest.TestCase):
    def setUp(self):
        gpu=PciDeviceRecord('0000:64:00.0','0x1002','0x15bf','0x030000','amdgpu',
                           ('0000:00:08.1','0000:64:00.0'))
        audio=PciDeviceRecord(BDF,'0x1022','0x15e3','0x040300','snd_hda_intel',
                             ('0000:00:08.1',BDF))
        card=DrmCardRecord('card4',gpu.bdf,gpu.vendor,gpu.device,True,'amdgpu',
                          (DrmConnectorRecord('card4','eDP-1','connected','enabled'),))
        self.values=[
            {'id':50,'type':'PipeWire:Interface:Device','info':{'props':{
                'device.bus-path':'pci-'+BDF,'device.api':'alsa','device.bus':'pci'}}},
            {'id':62,'type':'PipeWire:Interface:Node','info':{'props':{
                'node.name':SINK,'device.id':50,'media.class':'Audio/Sink'}}},
            {'id':41,'type':'PipeWire:Interface:Metadata','props':{'metadata.name':'default'},
             'metadata':[{'subject':0,'key':'default.audio.sink','value':{'name':SINK}}]},
            {'id':70,'type':'PipeWire:Interface:Device','info':{'props':{
                'device.bus-path':'pci-0000:08:00.1','device.api':'alsa','device.bus':'pci'},
                'params':{'EnumProfile':[{'index':0,'name':'off','available':'yes'},
                    {'index':2,'name':'output:hdmi-stereo','available':'yes'}],
                    'Profile':[{'index':2,'name':'output:hdmi-stereo'}]}}}]
        self.commands=Mock()
        self.commands.dump.side_effect=lambda *args,**kwargs:SimpleNamespace(ok=True,output=json.dumps(self.values).encode())
        self.user=SimpleNamespace(uid=1000,username='private-user')
        self.context_calls=0
        def context():
            self.context_calls+=1
            return AudioTrialContext('a'*64,'b'*64,'0000:08:00.1',BDF,SINK,1000,'c'*32,True,True,10)
        self.factory=Mock(return_value=context)
        self.sources=dict(drm=SimpleNamespace(scan=lambda:(card,)),
            pci=SimpleNamespace(scan_pci=lambda:(gpu,audio)),
            host=SimpleNamespace(scan=lambda:HostRecord('ASUSTeK COMPUTER INC.','ROG Ally X RC72LA','RC72LA')),
            gamescope=SimpleNamespace(scan=lambda:object()),
            resolve_user=lambda _:SimpleNamespace(ok=True,context=self.user),
            commands=self.commands,context_factory=self.factory,clock=lambda:10)

    def test_real_live_observer_reads_fresh_dump_and_context_twice(self):
        result=capture(**self.sources)
        self.assertTrue(result['ready'])
        self.assertEqual(self.commands.dump.call_count,2)
        self.assertEqual(self.context_calls,2)
        self.assertEqual(self.factory.call_args.args,(self.user,SINK))
        self.assertEqual(self.factory.call_args.kwargs['deadline'],20)
        self.assertEqual(len(result['context_digest']),64)
        self.assertFalse(result['disconnect_clearance'])
        self.assertFalse(result['resources_released'])
        rendered=json.dumps(result)
        for secret in (SINK,'private-user',BDF,'0000:08:00.1'):
            self.assertNotIn(secret,rendered)
        self.assertEqual([call[0] for call in self.commands.method_calls],['dump','dump'])

    def test_baseline_validation_uses_actual_default_not_configured(self):
        self.values[2]['metadata'][0]['key']='default.configured.audio.sink'
        result=capture(**self.sources)
        self.assertEqual(result['code'],'baseline_unavailable')
        self.factory.assert_not_called()

    def test_duplicate_json_cannot_bypass_full_baseline_parser(self):
        raw=json.dumps(self.values).replace('"id": 50','"id": 51, "id": 50')
        with self.assertRaises(ValueError):portable_baseline(raw,BDF)

    def test_internal_bdf_mismatch_rejects_without_context(self):
        self.values[0]['info']['props']['device.bus-path']='pci-0000:65:00.6'
        result=capture(**self.sources)
        self.assertFalse(result['ready'])
        self.factory.assert_not_called()

    def test_context_failure_categorized_without_exception_leak(self):
        self.factory.return_value=Mock(side_effect=ValueError('private-user secret /path'))
        result=capture(**self.sources)
        self.assertEqual(result['code'],'context_unavailable')
        self.assertNotIn('secret',json.dumps(result))

    def test_actual_profile_failure_separate_from_baseline(self):
        del self.values[3]['info']['params']
        result=capture(**self.sources)
        self.assertEqual(result['code'],'actual_profile_unavailable')
        self.assertEqual(self.context_calls,1)

    def test_only_exact_value_error_context_reasons_are_categorized(self):
        self.factory.return_value=Mock(side_effect=ValueError('Gamescope owner changed or unverified'))
        self.assertEqual(capture(**self.sources)['code'],'context_owner_changed')
        self.factory.return_value=Mock(side_effect=OSError('Gamescope owner changed or unverified'))
        self.assertEqual(capture(**self.sources)['code'],'context_unavailable')

    def test_root_required_no_context(self):
        self.commands.dump.side_effect=None
        self.commands.dump.return_value=SimpleNamespace(ok=False,code='audio.root_required')
        result=capture(**self.sources)
        self.assertEqual(result['code'],'baseline_root_required')
        self.assertIn('elapsed_seconds',result)
        self.factory.assert_not_called()

    def test_linux_guard_no_capture(self):
        with patch('scripts.probe_audio_trial_context.sys.platform','win32'), \
             patch('scripts.probe_audio_trial_context.capture') as run, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(),1)
        run.assert_not_called()


if __name__=='__main__':unittest.main()
