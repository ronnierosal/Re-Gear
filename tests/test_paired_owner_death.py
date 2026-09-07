import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from scripts import probe_paired_owner_death as fixture
from hdm.delivery.cgroup_retention_map import MapIdentity
from hdm.delivery.device_receive_kernel import ReceiveIdentity, ReceivePinAbsent
from scripts.paired_receive_receipt import PairedReceipt, ReceiptBinding


class PairedOwnerDeathTests(unittest.TestCase):
    def setUp(self):
        self.events=[]
        self.map_id=MapIdentity(21)
        self.receive_id=ReceiveIdentity(3,7,9,5)
        self.map=Mock(map_fd=31)
        self.map.create.return_value=self.map_id
        self.map.identity.return_value=self.map_id
        self.map.recover.side_effect=lambda *a:self.events.append('map-recover')
        self.map.pin.side_effect=lambda *a:self.events.append('map-pin')
        self.map.release_entry.side_effect=[True,False]
        self.link=Mock(program_fd=41,link_fd=42)
        self.link.link_identity.return_value=self.receive_id
        self.link.load_attach.side_effect=lambda *a,**k:self.events.append('load')
        self.link.recover.side_effect=lambda *a:self.events.append('receive-recover')
        self.link.pin.side_effect=lambda *a:self.events.append('receive-pin')
        self.link.probe_program_present.return_value=False
        self.receipt=Mock()
        self.receipt.write_map.side_effect=lambda *a:self.events.append('map-receipt')
        self.receipt.write_receive.side_effect=lambda *a:self.events.append('receive-receipt')
        self.binding=ReceiptBinding('a'*64,'regear-paired-receive-fixture-'+'b'*32,1,2)
        self.record=PairedReceipt(self.binding,'a'*64,self.map_id,'b'*64,self.receive_id)

    def publish(self,before_receive_pin=False):
        def ready(packet):
            self.assertEqual(packet,b'before-receive-pin' if before_receive_pin else b'paired-live')
            self.map.close.assert_not_called();self.link.close.assert_not_called()
            self.events.append('ready')
        def wait():raise RuntimeError('simulated exit')
        def fstat(fd):self.events.append(('fstat',fd));return SimpleNamespace(st_ino=2)
        with patch.object(fixture.os,'major',lambda dev:1,create=True),patch.object(fixture.os,'minor',lambda dev:3,create=True):
            fixture.publish_pair(10,SimpleNamespace(file_inode_offset=1,inode_mode_offset=2,
                inode_rdev_offset=3,hook_btf_id=9),3,self.receipt,map_factory=lambda:self.map,
                link_factory=lambda:self.link,pins_factory=lambda **k:Mock(fd=12),
                compiler=lambda *a,**k:b'program',send_ready=ready,wait_for_death=wait,fstat=fstat,
                before_receive_pin=before_receive_pin)

    def test_receipts_before_pins_and_live_fds_before_fixed_readiness(self):
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual(self.events,['map-receipt','map-pin',('fstat',10),'load','receive-receipt',
            'receive-pin',('fstat',31),('fstat',41),('fstat',42),'ready'])

    def test_map_receipt_error_never_loads_filter(self):
        self.receipt.write_map.side_effect=OSError()
        with self.assertRaises(OSError):self.publish()
        self.map.pin.assert_not_called();self.link.load_attach.assert_not_called()

    def test_receive_receipt_error_never_pins_receive(self):
        self.receipt.write_receive.side_effect=OSError()
        with self.assertRaises(OSError):self.publish()
        self.link.pin.assert_not_called()
        self.map.release_entry.assert_not_called()

    def recover(self,**kwargs):
        defaults=dict(pin_fd=12,map_factory=lambda:self.map,link_factory=lambda:self.link,
            null_exchange=Mock(side_effect=[dict(received=0,truncated=True,device=None),
                                           dict(received=1,truncated=False,device=3)]),
            zero_exchange=lambda:dict(received=1,truncated=False,device=5),null_device=3,zero_device=5,
            unlink=lambda token,**k:self.events.append(('unlink',token)),
            stage=lambda value:self.events.append(value))
        defaults.update(kwargs)
        return fixture.recover_pair(self.record,**defaults)

    def test_recover_receives_before_releasing_retention(self):
        result=self.recover()
        self.assertTrue(result['receive_absence_observed'])
        self.assertLess(self.events.index(('unlink','b'*64)),self.events.index('receive_absence'))
        self.assertLess(self.events.index('receive_absence'),self.events.index('retention_release'))
        self.assertLess(self.events.index('retention_release'),self.events.index(('unlink','a'*64)))
        self.assertEqual(self.map.release_entry.call_count,2)

    def test_probe_error_or_live_reference_keeps_retention(self):
        self.link.probe_program_present.side_effect=PermissionError()
        with self.assertRaises(PermissionError):self.recover()
        self.map.release_entry.assert_not_called()
        self.link.probe_program_present.side_effect=None
        self.link.probe_program_present.return_value=True
        with self.assertRaises(TimeoutError):self.recover(clock=Mock(side_effect=[0,3]))
        self.map.release_entry.assert_not_called()

    def test_missing_receive_identity_never_infers_no_filter(self):
        self.record=PairedReceipt(self.binding,'a'*64,self.map_id)
        with self.assertRaises(ValueError):self.recover()
        self.map.recover.assert_not_called();self.map.release_entry.assert_not_called()

    def test_no_receipt_read_before_confirmed_kill(self):
        calls=[]
        result=fixture.verify_owner_death(ready=lambda:b'paired-live',deny=lambda:True,
            kill_controller=lambda:calls.append('killed'),
            read_receipt=lambda:calls.append('read') or self.record,
            recover=lambda record:calls.append('recover') or {})
        self.assertEqual(calls,['killed','read','recover'])
        self.assertTrue(result['live_bpf_fd_crash_verified'])
        reader=Mock()
        with self.assertRaises(OSError):fixture.verify_owner_death(ready=lambda:b'paired-live',deny=lambda:True,
            kill_controller=Mock(side_effect=OSError()),read_receipt=reader,recover=Mock())
        reader.assert_not_called()

    def test_mismatched_recovered_map_cannot_remove_receive_pin(self):
        self.map.identity.return_value=MapIdentity(22)
        with self.assertRaises(ValueError):self.recover()
        self.link.recover.assert_not_called()
        self.map.release_entry.assert_not_called()

    def test_unknown_presence_and_invalid_clock_never_release_map(self):
        self.link.probe_program_present.return_value=None
        with self.assertRaises(ValueError):self.recover()
        self.map.release_entry.assert_not_called()
        for ticks in ([float('nan')],[2,1],[0,float('inf')]):
            with self.subTest(ticks=ticks):
                with self.assertRaises(ValueError):self.recover(clock=Mock(side_effect=ticks))
                self.map.release_entry.assert_not_called()

    def test_controller_diagnostics_are_strict_and_bounded(self):
        import json
        packet=b'failed:'+json.dumps(dict(stage='receive_load',error_type='OSError',errno=22)).encode()
        self.assertEqual(fixture.controller_failure(packet)['errno'],22)
        for packet in (b'paired-live',b'failed:'+b'x'*129,
            b'failed:{"stage":"private path","error_type":"OSError","errno":22}',
            b'failed:{"stage":"map_pin","error_type":"OSError","errno":true}',
            b'failed:{"stage":"map_pin","error_type":"OSError","errno":22,"message":"pointer"}'):
            with self.subTest(packet=packet):
                with self.assertRaises(ValueError):fixture.controller_failure(packet)

    def test_close_failure_still_attempts_retention_and_pin_directory(self):
        first,second,third=Mock(),Mock(),Mock()
        first.close.side_effect=OSError('first close')
        with self.assertRaises(OSError):fixture.close_all(first,second,third)
        second.close.assert_called_once();third.close.assert_called_once()
        try:
            raise ValueError('original error')
        except ValueError:
            fixture.close_all(first,second,third)
        self.assertEqual(third.close.call_count,2)

    def test_recovery_link_close_failure_still_closes_retention(self):
        self.link.close.side_effect=OSError()
        with self.assertRaises(OSError):self.recover()
        self.map.close.assert_called()
        self.map.release_entry.assert_not_called()

    def test_before_pin_readiness_follows_full_receipt_without_receive_pin(self):
        with self.assertRaises(RuntimeError):self.publish(True)
        self.link.pin.assert_not_called()
        self.assertIn('receive-receipt',self.events)
        self.assertEqual(self.events[-4:],[('fstat',31),('fstat',41),('fstat',42),'ready'])

    def test_before_pin_enoent_requires_absence_and_both_restored_controls(self):
        import errno
        self.link.recover.side_effect=ReceivePinAbsent(errno.ENOENT,'missing')
        result=self.recover(before_receive_pin=True,
            null_exchange=lambda:dict(received=1,truncated=False,device=3))
        self.assertFalse(result['post_death_denial_observed'])
        self.assertTrue(result['receive_pin_absent_observed'])
        self.assertTrue(result['pin_not_published_checkpoint'])
        self.assertNotIn(('unlink','b'*64),self.events)
        self.assertIn(('unlink','a'*64),self.events)

    def test_missing_pin_default_and_permission_errors_always_refuse(self):
        import errno
        for mode,code in ((False,errno.ENOENT),(True,errno.EPERM)):
            with self.subTest(mode=mode,code=code):
                self.link.recover.side_effect=OSError(code,'refuse')
                with self.assertRaises(OSError):self.recover(before_receive_pin=mode)
                self.map.release_entry.assert_not_called()

    def test_before_pin_missing_receipt_or_live_program_refuses_release(self):
        import errno
        self.link.recover.side_effect=ReceivePinAbsent(errno.ENOENT,'missing')
        self.link.probe_program_present.return_value=True
        with self.assertRaises(TimeoutError):self.recover(before_receive_pin=True,clock=Mock(side_effect=[0,3]))
        self.map.release_entry.assert_not_called()
        self.record=PairedReceipt(self.binding,'a'*64,self.map_id)
        with self.assertRaises(ValueError):self.recover(before_receive_pin=True)
        self.map.release_entry.assert_not_called()

    def test_before_pin_marker_and_mode_are_exact(self):
        reader=Mock()
        with self.assertRaises(ValueError):fixture.verify_owner_death(ready=lambda:b'paired-live',deny=lambda:True,
            kill_controller=Mock(),read_receipt=reader,recover=Mock(),before_receive_pin=True)
        reader.assert_not_called()
        with self.assertRaises(ValueError):self.recover(before_receive_pin=1)
        self.map.recover.assert_not_called()

    def test_generic_metadata_enoent_is_not_pin_absence(self):
        self.link.recover.side_effect=FileNotFoundError(2,'metadata missing')
        with self.assertRaises(FileNotFoundError):self.recover(before_receive_pin=True)
        self.map.release_entry.assert_not_called()
        self.link.recover.side_effect=ReceivePinAbsent(2,'missing')
        with self.assertRaises(ReceivePinAbsent):self.recover()
        self.map.release_entry.assert_not_called()

    def test_before_pin_zero_failure_retains_map(self):
        self.link.recover.side_effect=ReceivePinAbsent(2,'missing')
        with self.assertRaises(ValueError):self.recover(before_receive_pin=True,
            null_exchange=lambda:dict(received=1,truncated=False,device=3),
            zero_exchange=lambda:dict(received=0,truncated=True,device=None))
        self.map.release_entry.assert_not_called()


if __name__=='__main__':unittest.main()
