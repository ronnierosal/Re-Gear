import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from scripts import probe_retained_receive_fixture as fixture
from hdm.delivery.cgroup_retention_map import MapIdentity
from hdm.delivery.device_receive_kernel import ReceiveIdentity


class RetainedReceiveTests(unittest.TestCase):
    def setUp(self):
        self.events=[]
        self.expected=MapIdentity(41)
        self.owner=Mock()
        self.owner.create.side_effect=lambda fd:self.event('create',self.expected)
        self.owner.identity.return_value=self.expected
        self.owner.pin.side_effect=lambda *args:self.event('pin')
        self.owner.close.side_effect=lambda:self.event('close')
        self.owner.recover.side_effect=lambda *args:self.event('recover')
        self.owner.release_entry.side_effect=lambda *args:self.event('delete',self.events.count('delete')==0)
        self.pins=Mock(fd=12)
        self.coordinator=fixture.RetainedReceiveCoordinator(map_factory=lambda:self.owner,
            pins_factory=lambda **kwargs:self.pins,journal=lambda *args:self.event('journal'),
            unlink=lambda *args:self.event('unlink'))
        self.receive=Mock()
        self.receive.probe_program_present.return_value=False
        self.receive_identity=ReceiveIdentity(3,7,9,5)

    def event(self,name,result=None):
        self.events.append(name)
        return result

    def prepare(self):
        self.coordinator.prepare(17,'regear-receive-pin-fixture-'+'a'*32,
                                 SimpleNamespace(st_dev=1,st_ino=2))

    def test_prepare_durably_records_before_pin_then_closes_and_recovers(self):
        self.prepare()
        self.assertEqual(self.events,['create','journal','pin','close','recover'])
        self.assertEqual(self.coordinator.phase,'prepared')
        self.assertTrue(self.coordinator.pin_may_remain)
        self.owner.recover.assert_called_once_with(12,self.coordinator.token,self.expected)

    def test_journal_failure_never_pins(self):
        self.coordinator.journal=Mock(side_effect=OSError('private'))
        with self.assertRaises(OSError):self.prepare()
        self.owner.pin.assert_not_called()
        self.assertFalse(self.coordinator.pin_may_remain)
        self.coordinator.close()
        self.owner.release_entry.assert_not_called()

    def test_recovery_mismatch_retains_pin(self):
        self.owner.identity.side_effect=[self.expected,MapIdentity(42)]
        with self.assertRaises(ValueError):self.prepare()
        self.assertTrue(self.coordinator.pin_may_remain)
        self.assertNotIn('unlink',self.events)
        self.owner.release_entry.assert_not_called()

    def test_absence_required_before_any_entry_mutation(self):
        for result in (True,None,0):
            with self.subTest(result=result):
                self.setUp();self.prepare()
                self.receive.probe_program_present.return_value=result
                with self.assertRaises(ValueError):self.coordinator.release(self.receive,self.receive_identity)
                self.owner.release_entry.assert_not_called()
                self.assertTrue(self.coordinator.pin_may_remain)
        self.receive.probe_program_present.side_effect=PermissionError()
        with self.assertRaises(PermissionError):self.coordinator.release(self.receive,self.receive_identity)
        self.owner.release_entry.assert_not_called()

    def test_success_releases_entry_before_unpin_and_cannot_replay(self):
        self.prepare()
        self.assertTrue(self.coordinator.release(self.receive,self.receive_identity))
        self.assertEqual(self.events[-4:],['delete','delete','unlink','close'])
        self.assertEqual(self.coordinator.phase,'released')
        self.assertFalse(self.coordinator.pin_may_remain)
        with self.assertRaises(ValueError):self.coordinator.release(self.receive,self.receive_identity)
        with self.assertRaises(ValueError):self.prepare()

    def test_missing_entry_and_unlink_error_fail_closed(self):
        self.prepare()
        self.owner.release_entry.side_effect=None
        self.owner.release_entry.return_value=False
        with self.assertRaises(ValueError):self.coordinator.release(self.receive,self.receive_identity)
        self.assertNotIn('unlink',self.events)
        self.assertTrue(self.coordinator.pin_may_remain)

    def test_changed_map_or_untyped_receive_identity_cannot_release(self):
        self.prepare()
        with self.assertRaises(ValueError):self.coordinator.release(self.receive,SimpleNamespace(program_id=7))
        self.owner.identity.return_value=MapIdentity(42)
        with self.assertRaises(ValueError):self.coordinator.release(self.receive,self.receive_identity)
        self.owner.release_entry.assert_not_called()

    def test_unlink_error_preserves_pin_uncertainty_after_entry_deletion(self):
        self.prepare()
        self.coordinator.unlink=Mock(side_effect=PermissionError())
        with self.assertRaises(PermissionError):
            self.coordinator.release(self.receive,self.receive_identity)
        self.assertEqual(self.owner.release_entry.call_count,2)
        self.assertEqual(self.coordinator.phase,'releasing')
        self.assertTrue(self.coordinator.pin_may_remain)
        self.coordinator.close()
        self.assertTrue(self.coordinator.pin_may_remain)

    def test_wrapper_passes_coordinator_and_retains_categorical_failure(self):
        def fail(*,retention):
            retention.phase='preparing';retention.pin_may_remain=True
            return dict(state='fixture_failed',cgroup_retained=True,disconnect_clearance=False)
        with patch.object(fixture,'receive_fixture',side_effect=fail):report=fixture.run_fixture()
        self.assertTrue(report['retention_pin_may_remain'])
        self.assertTrue(report['cgroup_retained'])
        self.assertFalse(report['id_nonreuse_certified'])




class RunnerRetentionIntegrationTests(unittest.TestCase):
    def exercise(self,release_error=False):
        from contextlib import ExitStack
        from scripts import probe_receive_pin_fixture as runner
        events=[]
        directory=SimpleNamespace(st_uid=0,st_mode=0o700,st_ino=33,st_dev=1)
        null=SimpleNamespace(st_mode=0o20600,st_rdev=3)
        zero=SimpleNamespace(st_mode=0o20600,st_rdev=5)
        socket=Mock();socket.recv.return_value=b'ready'
        owner=Mock();owner.link_identity.return_value=ReceiveIdentity(3,7,9,5)
        owner.load_attach.side_effect=lambda *a,**k:events.append('load')
        retention=Mock()
        retention.prepare.side_effect=lambda *a:events.append('prepare')
        def release(*args):
            events.append('release')
            if release_error:raise ValueError('unresolved')
            return True
        retention.release.side_effect=release
        def cleanup(*args):events.append(('cleanup',args[-1]))
        with ExitStack() as stack:
            def mocked(name,**kwargs):return stack.enter_context(patch.object(runner,name,**kwargs))
            stack.enter_context(patch('builtins.open',unittest.mock.mock_open(read_data=b'btf')))
            for name,value in [('geteuid',lambda:0),('O_DIRECTORY',0),('O_NOFOLLOW',0),
                               ('fork',lambda:123),('major',lambda dev:1),('minor',lambda dev:dev)]:
                stack.enter_context(patch.object(runner.os,name,value,create=True))
            for name,kwargs in [('open',dict(return_value=10)),('close',{}),('mkdir',{}),
                ('fstat',dict(side_effect=[directory,directory,null,zero])),('read',dict(return_value=b'123'))]:
                stack.enter_context(patch.object(runner.os,name,**kwargs))
            stack.enter_context(patch.object(runner.platform,'system',return_value='Linux'))
            stack.enter_context(patch.object(runner.platform,'machine',return_value='x86_64'))
            stack.enter_context(patch.object(runner.socket,'AF_UNIX',1,create=True))
            stack.enter_context(patch.object(runner.socket,'SOCK_SEQPACKET',5,create=True))
            stack.enter_context(patch.object(runner.socket,'socketpair',return_value=(socket,Mock())))
            mocked('parse_file_receive_btf',return_value=SimpleNamespace(file_inode_offset=1,
                inode_mode_offset=2,inode_rdev_offset=3,hook_btf_id=9))
            mocked('FilterPinDirectory',return_value=Mock(fd=12))
            mocked('DiagnosticReceiveLink',return_value=owner)
            mocked('compile_device_receive',return_value=b'program')
            mocked('exchange',return_value=None);mocked('_received',return_value=True)
            mocked('exercise_pin_lifetime',side_effect=lambda *a,**k:events.append('absence') or {})
            mocked('release_proven',return_value=True)
            mocked('cleanup_fixture',side_effect=cleanup)
            report=runner.run_fixture(retention=retention)
        return report,events

    def test_prepare_before_load_and_release_before_removal(self):
        report,events=self.exercise()
        self.assertEqual(events,['prepare','load','absence','release',('cleanup',True)])
        self.assertEqual(report['state'],'fixture_passed')

    def test_release_failure_retains_cgroup_despite_program_absence(self):
        report,events=self.exercise(True)
        self.assertEqual(events[-1],('cleanup',False))
        self.assertEqual(report['state'],'fixture_failed')
        self.assertTrue(report['cgroup_retained'])


if __name__=='__main__':unittest.main()


