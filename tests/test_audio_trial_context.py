from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.adapters.steamos.audio_trial_context import AudioTrialContextSource
from regear.adapters.steamos.drm import DrmCardRecord, DrmConnectorRecord
from regear.adapters.steamos.pci import PciDeviceRecord, Usb4DeviceRecord
from regear.adapters.steamos.host import HostRecord
from regear.adapters.steamos.gamescope import GamescopeScan, GamescopeProcessRecord
from regear.domain.serialization import snapshot_from_dict
from regear.domain.models import GameState, Confidence


class AudioTrialContextTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.wall = datetime(2026, 9, 6, tzinfo=timezone.utc)
        self.boot = '11111111-2222-3333-4444-555555555555'
        self.user = SimpleNamespace(uid=1000, username='deck')
        self.host = HostRecord('ASUSTeK COMPUTER INC.', 'ROG Ally X RC72LA', 'RC72LA')
        gpu = PciDeviceRecord('0000:64:00.0','0x1002','0x15bf','0x030000','amdgpu',
                              ('0000:00:08.1','0000:64:00.0'))
        analog = PciDeviceRecord('0000:64:00.6','0x1022','0x15e3','0x040300','snd_hda_intel',
                                 ('0000:00:08.1','0000:64:00.6'))
        root = PciDeviceRecord('0000:04:00.0','0x8086','0x15ef','0x060400','pcieport',
                               ('0000:00:03.1','0000:04:00.0'),True)
        external = PciDeviceRecord('0000:08:00.0','0x1002','0x7480','0x030000','amdgpu',
                                   (*root.ancestry,'0000:08:00.0'))
        audio = PciDeviceRecord('0000:08:00.1','0x1002','0xab30','0x040300','snd_hda_intel',
                                (*root.ancestry,'0000:08:00.1'))
        usb = PciDeviceRecord('0000:09:00.0','0x8086','0x15f0','0x0c0330','xhci_hcd',
                              (*root.ancestry,'0000:09:00.0'))
        self.devices = (gpu,analog,root,external,audio,usb)
        self.cards = (DrmCardRecord('card4',gpu.bdf,gpu.vendor,gpu.device,True,'amdgpu',
                                    (DrmConnectorRecord('card4','eDP-1','connected','enabled'),)),
                      DrmCardRecord('card9',external.bdf,external.vendor,external.device,False,'amdgpu'))
        self.transport = (Usb4DeviceRecord('0-2','Intel','Tapex Creek',True,'a'*64),)
        self.process = GamescopeProcessRecord(50436,('/usr/bin/gamescope',),uid=1000,start_time_ticks=77)
        self.unit = dict(MainPID='50000',InvocationID='c'*32,ActiveState='active',
            ControlGroup='/user.slice/user-1000.slice/user@1000.service/session.slice/gamescope-session.service')
        raw = json.loads((Path(__file__).parent/'fixtures'/'portable.json').read_text())
        raw['observed_at'] = self.wall.isoformat()
        raw['gpus'][0]['vendor_device'] = '1002:15bf'
        raw['gamescope']['render_vendor_device'] = '1002:15bf'
        self.snapshot = snapshot_from_dict(raw)
        self.snapshot_calls = 0
        self.after_snapshot = lambda: None
        self.resolve = lambda scan: SimpleNamespace(ok=True,context=self.user)
        self.cgroup = self.unit['ControlGroup']
        self.complete = True

    def collect(self):
        self.snapshot_calls += 1
        self.after_snapshot()
        return self.snapshot

    def source(self, **kwargs):
        options = dict(deadline=20, drm=SimpleNamespace(scan=lambda:self.cards),
            pci=SimpleNamespace(scan_pci=lambda:self.devices, scan_usb4_checked=lambda:(self.transport,self.complete)),
            host=SimpleNamespace(scan=lambda:self.host),
            gamescope=SimpleNamespace(scan=lambda:GamescopeScan(self.process,1)),
            collect_snapshot=self.collect, resolve_user=lambda scan:self.resolve(scan),
            observe_unit=lambda unit:dict(self.unit), read_boot=lambda:self.boot,
            read_process_cgroup=lambda pid:self.cgroup, clock=lambda:self.now, wall_clock=lambda:self.wall)
        options.update(kwargs)
        return AudioTrialContextSource(self.user,'portable.sink',**options)

    def test_real_matchers_and_snapshot_produce_fresh_context(self):
        result = self.source()()
        self.assertEqual(result.audio_bdf,'0000:08:00.1')
        self.assertEqual(result.portable_audio_bdf,'0000:64:00.6')
        self.assertTrue(result.portable_ready)
        self.assertTrue(result.no_game)
        self.assertEqual(result.observed_at,10)
        self.assertEqual(len(result.topology_hash),64)
        self.assertEqual(self.snapshot_calls,1)

    def test_unknown_game_and_nonportable_snapshot_reject(self):
        for state in (GameState.UNKNOWN,GameState.RUNNING):
            self.snapshot = replace(self.snapshot,game_state=state)
            with self.assertRaises(ValueError):self.source()()

    def test_changed_pid_start_boot_and_invocation_reject(self):
        for field in ('pid','start','boot','invocation'):
            with self.subTest(field=field):
                self.setUp()
                def change():
                    if field=='pid':self.process=replace(self.process,pid=12345)
                    elif field=='start':self.process=replace(self.process,start_time_ticks=99)
                    elif field=='boot':self.boot='aaaaaaaa-2222-3333-4444-555555555555'
                    else:self.unit['InvocationID']='d'*32
                self.after_snapshot=change
                with self.assertRaises(ValueError):self.source()()

    def test_topology_change_rejects(self):
        self.after_snapshot=lambda:setattr(self,'transport',(replace(self.transport[0],unique_id_sha256='b'*64),))
        with self.assertRaises(ValueError):self.source()()

    def test_analog_identity_not_inferred_from_other_audio(self):
        self.devices=tuple(p for p in self.devices if p.bdf!='0000:64:00.6')
        with self.assertRaises(ValueError):self.source()()
        self.assertEqual(self.snapshot_calls,0)

    def test_owner_and_service_membership_required(self):
        self.resolve=lambda scan:SimpleNamespace(ok=True,context=SimpleNamespace(uid=1001,username='other'))
        with self.assertRaises(ValueError):self.source()()
        self.resolve=lambda scan:SimpleNamespace(ok=True,context=self.user)
        self.cgroup='/unrelated'
        with self.assertRaises(ValueError):self.source()()

    def test_cached_or_future_snapshot_rejected(self):
        for delta in (-1,1):
            self.snapshot=replace(self.snapshot,observed_at=(self.wall+timedelta(seconds=delta)).isoformat())
            with self.assertRaises(ValueError):self.source()()

    def test_duration_and_deadline_rejected(self):
        self.after_snapshot=lambda:setattr(self,'now',12.1)
        with self.assertRaises(ValueError):self.source()()
        for deadline in (12.1,True,float('nan'),99):
            with self.assertRaises(TimeoutError):self.source(deadline=deadline)()

    def test_incomplete_usb4_and_unknown_process_identity_reject(self):
        self.complete=False
        with self.assertRaises(ValueError):self.source()()
        self.complete=True
        self.process=replace(self.process,start_time_ticks=0)
        with self.assertRaises(ValueError):self.source()()

    def test_snapshot_pid_and_gpu_must_match_bracket(self):
        self.snapshot=replace(self.snapshot,gamescope=replace(self.snapshot.gamescope,pid=123))
        with self.assertRaises(ValueError):self.source()()

    def test_unverified_placement_and_mismatched_renderer_reject(self):
        original=self.snapshot
        self.snapshot=replace(original,gamescope=replace(original.gamescope,confidence=Confidence.UNKNOWN))
        with self.assertRaises(ValueError):self.source()()
        self.snapshot=replace(original,gpus=(replace(original.gpus[0],vendor_device='1002:0000'),))
        with self.assertRaises(ValueError):self.source()()

    def test_returned_timestamp_is_collection_start(self):
        self.after_snapshot=lambda:setattr(self,'now',10.5)
        result=self.source()()
        self.assertEqual(result.observed_at,10)
        self.assertEqual(self.now,10.5)


if __name__ == '__main__':unittest.main()
