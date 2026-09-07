import unittest
import stat
import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from scripts.probe_receive_pin_fixture import exercise_pin_lifetime, release_proven, ReceiptJournal, _receipt_parent, run_fixture, Stage
from hdm.delivery.device_receive_kernel import ReceiveIdentity


class FakeKernel:
    def __init__(self):
        self.expected=ReceiveIdentity(3,7,9,5)
        self.pin=False
        self.holders=0
        self.events=[]
        self.force_present=False
        self.mismatch=False
    def link(self):return FakeLink(self)
    def denied(self):
        active=self.pin or self.holders>0
        self.events.append('deny' if active else 'receive')
        return dict(received=0 if active else 1,truncated=bool(active),device=None if active else 11)


class FakeLink:
    def __init__(self,kernel):self.kernel,self.held=kernel,False
    def link_identity(self):return self.kernel.expected
    def pin(self,directory,token,expected):
        if self.kernel.pin:raise ValueError('already pinned')
        self.kernel.events.append('pin')
        self.kernel.pin=True
    def recover(self,directory,token,expected):
        if self.kernel.mismatch or not self.kernel.pin or self.held:raise ValueError('recovery mismatch')
        self.held=True
        self.kernel.holders+=1
        self.kernel.events.append('recover')
    def close(self):
        self.kernel.events.append('close')
        if self.held:
            self.kernel.holders-=1
            self.held=False
    def probe_program_present(self,program):
        self.kernel.events.append('probe')
        return bool(self.kernel.force_present or self.kernel.pin or self.kernel.holders)


class ReceivePinFixtureTests(unittest.TestCase):
    def setUp(self):
        self.kernel=FakeKernel()
        self.owner=self.kernel.link()
        self.owner.held=True
        self.kernel.holders=1
        self.now=10
    def wait(self,seconds):self.now+=seconds
    def exercise(self,journal=None):
        def unlink(token,expected):
            self.assertEqual(expected,self.kernel.expected)
            self.assertEqual(self.kernel.holders,2)
            self.kernel.events.append('unlink')
            self.kernel.pin=False
        return exercise_pin_lifetime(self.owner,directory_fd=8,token='a'*64,expected=self.kernel.expected,
            journal=journal or (lambda expected:self.kernel.events.append('journal')),
            null_exchange=self.kernel.denied,zero_exchange=lambda:dict(received=1,truncated=False,device=12),
            zero_device=12,null_device=11,unlink_exact=unlink,link_factory=self.kernel.link,
            clock=lambda:self.now,wait=self.wait)

    def test_journal_pin_recover_extra_reference_order(self):
        result=self.exercise()
        events=self.kernel.events
        self.assertLess(events.index('journal'),events.index('pin'))
        self.assertEqual(events.count('recover'),2)
        unlink=events.index('unlink')
        self.assertEqual(events[unlink:unlink+4],['unlink','close','probe','deny'])
        self.assertTrue(result['program_absence_observed'])
        self.assertTrue(result['null_receipt_restored'])
        self.assertEqual(self.kernel.holders,0)
        self.assertFalse(self.kernel.pin)

    def test_journal_failure_never_pins(self):
        def fail(expected):raise OSError('fsync failed')
        with self.assertRaises(OSError):self.exercise(fail)
        self.assertNotIn('pin',self.kernel.events)
        self.assertEqual(self.kernel.holders,0)

    def test_recovery_mismatch_retains_pin_and_disallows_cgroup_removal(self):
        self.kernel.mismatch=True
        with self.assertRaises(ValueError):self.exercise()
        self.assertTrue(self.kernel.pin)
        self.assertNotIn('unlink',self.kernel.events)
        self.assertFalse(release_proven(self.owner,self.kernel.expected))

    def test_unresolved_extra_reference_disallows_cgroup_removal(self):
        self.kernel.force_present=True
        with self.assertRaises(ValueError):self.exercise()
        self.assertFalse(release_proven(self.owner,self.kernel.expected))
        self.assertGreaterEqual(self.now,12)

    def test_program_probe_error_is_not_absence(self):
        self.owner.probe_program_present=lambda program:(_ for _ in ()).throw(PermissionError())
        self.assertFalse(release_proven(self.owner,self.kernel.expected))

    def test_only_observed_absence_allows_cleanup(self):
        self.assertTrue(release_proven(self.owner,self.kernel.expected))
        self.assertFalse(release_proven(self.owner,None))

    def test_receipt_names_cannot_escape_private_directory(self):
        for token in ('../x','a'*63,'A'*64):
            with self.assertRaises(ValueError):ReceiptJournal(token,'regear-receive-pin-fixture-'+'b'*32,None)


class ReceiptAncestorTests(unittest.TestCase):
    def setup_syscalls(self,stack,stats,opens=(10,11,12)):
        for name,value in (('O_DIRECTORY',0x10000),('O_NOFOLLOW',0x20000),('O_CLOEXEC',0x40000)):
            stack.enter_context(patch('scripts.probe_receive_pin_fixture.os.'+name,value,create=True))
        opened=stack.enter_context(patch('scripts.probe_receive_pin_fixture.os.open',side_effect=opens))
        stack.enter_context(patch('scripts.probe_receive_pin_fixture.os.fstat',side_effect=stats))
        closed=stack.enter_context(patch('scripts.probe_receive_pin_fixture.os.close'))
        return opened,closed

    def test_each_ancestor_is_opened_relative_and_validated(self):
        safe=SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=0)
        with ExitStack() as stack:
            opened,closed=self.setup_syscalls(stack,[safe,safe,safe])
            self.assertEqual(_receipt_parent(),12)
            self.assertEqual([c.args[0] for c in opened.call_args_list],['/','var','lib'])
            self.assertEqual(opened.call_args_list[1].kwargs,{'dir_fd':10})
            self.assertEqual(opened.call_args_list[2].kwargs,{'dir_fd':11})
            for call in opened.call_args_list:
                self.assertTrue(call.args[1]&0x20000)
            self.assertEqual([c.args[0] for c in closed.call_args_list],[10,11])

    def test_unsafe_ancestor_stops_before_lib(self):
        safe=SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=0)
        unsafe=SimpleNamespace(st_mode=stat.S_IFDIR|0o777,st_uid=0)
        with ExitStack() as stack:
            opened,closed=self.setup_syscalls(stack,[safe,unsafe])
            with self.assertRaises(ValueError):_receipt_parent()
            self.assertEqual([c.args[0] for c in opened.call_args_list],['/','var'])
            self.assertEqual([c.args[0] for c in closed.call_args_list],[10,11])

    def test_symlink_ancestor_open_failure_closes_root(self):
        safe=SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=0)
        with ExitStack() as stack:
            opened,closed=self.setup_syscalls(stack,[safe],opens=(10,OSError('symlink rejected')))
            with self.assertRaises(OSError):_receipt_parent()
            self.assertEqual([c.args[0] for c in opened.call_args_list],['/','var'])
            closed.assert_called_once_with(10)


class FixtureDiagnosticsTests(unittest.TestCase):
    def test_failure_preserves_stage_and_retained_evidence_without_message(self):
        def fail(report):
            report.update(stage=Stage.LOAD_ATTACH.value,cgroup_retained=True,journal_retained=False)
            raise OSError(22,'private verifier pointer 0x1234')
        with patch('scripts.probe_receive_pin_fixture._run_fixture',side_effect=fail):
            report=run_fixture()
        self.assertEqual(report['stage'],'load_attach')
        self.assertEqual(report['error_type'],'OSError')
        self.assertEqual(report['errno'],22)
        self.assertTrue(report['cgroup_retained'])
        self.assertFalse(report['journal_retained'])
        self.assertNotIn('private',json.dumps(report))
        self.assertNotIn('0x1234',json.dumps(report))

    def test_original_failure_not_replaced_by_cleanup_exception(self):
        def fail(report):
            report.update(stage='pin',state='fixture_failed',error_type='ValueError',errno=None,
                          cleanup_error={'error_type':'PermissionError','errno':13})
            raise PermissionError(13,'private cleanup')
        with patch('scripts.probe_receive_pin_fixture._run_fixture',side_effect=fail):
            report=run_fixture()
        self.assertEqual(report['error_type'],'ValueError')
        self.assertEqual(report['cleanup_error']['errno'],13)

    def test_early_failure_has_platform_stage_and_no_retained_cgroup_claim(self):
        with patch('scripts.probe_receive_pin_fixture._run_fixture',side_effect=ValueError('unsafe platform')):
            report=run_fixture()
        self.assertEqual(report['stage'],'platform')
        self.assertFalse(report['cgroup_retained'])
        self.assertIsNone(report['errno'])


if __name__=='__main__':unittest.main()
