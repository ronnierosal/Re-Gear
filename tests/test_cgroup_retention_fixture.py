import json
import unittest
from unittest.mock import patch

from scripts.probe_cgroup_retention_fixture import exercise_retention,run_fixture,write_receipt
from hdm.delivery.cgroup_retention_map import MapIdentity


class FakeMap:
    def __init__(self):
        self.events=[]
        self.held=False
        self.pinned=False
        self.entry=False
        self.child_held=True
        self.removed=False
        self.fail_recover=False
        self.expected=MapIdentity(7)
    def create(self,fd):
        self.events.append('create')
        self.held=self.entry=True
        return self.expected
    def identity(self):return self.expected
    def pin(self,directory,token,expected):
        self.events.append('pin')
        self.pinned=True
    def close(self):
        self.events.append('close_map')
        self.held=False
    def recover(self,directory,token,expected):
        self.events.append('recover')
        if self.fail_recover:raise ValueError('wrong map')
        if not self.pinned:raise ValueError('pin missing')
        self.held=True
    def release_entry(self,expected):
        self.events.append('release')
        previous,self.entry=self.entry,False
        return previous


class RetentionFixtureTests(unittest.TestCase):
    def setUp(self):self.owner=FakeMap()
    def exercise(self,journal=None):
        def close_child():
            self.owner.events.append('close_child')
            self.owner.child_held=False
        def remove():
            self.assertFalse(self.owner.held)
            self.assertFalse(self.owner.child_held)
            self.owner.events.append('remove')
            self.owner.removed=True
        def unlink(token,expected):
            self.assertEqual(expected,self.owner.expected)
            self.assertFalse(self.owner.entry)
            self.owner.events.append('unlink')
            self.owner.pinned=False
        return exercise_retention(self.owner,cgroup_fd=4,pin_directory_fd=8,token='a'*64,
            journal=journal or (lambda expected:self.owner.events.append('journal')),
            close_cgroup=close_child,remove_exact_cgroup=remove,unlink_exact_pin=unlink)

    def test_receipt_pin_close_all_remove_recover_release_order(self):
        result=self.exercise()
        self.assertEqual(self.owner.events,['create','journal','pin','close_map','close_child',
            'remove','recover','release','release','unlink','close_map'])
        self.assertTrue(result['entry_survived_cgroup_directory_removal'])
        self.assertFalse(result['id_nonreuse_certified'])
        self.assertFalse(self.owner.pinned)

    def test_journal_failure_prevents_pin_and_child_removal(self):
        def fail(expected):raise OSError('fsync failed')
        with self.assertRaises(OSError):self.exercise(fail)
        self.assertNotIn('pin',self.owner.events)
        self.assertNotIn('remove',self.owner.events)
        self.assertFalse(self.owner.held)

    def test_recovery_mismatch_keeps_pin(self):
        self.owner.fail_recover=True
        with self.assertRaises(ValueError):self.exercise()
        self.assertTrue(self.owner.pinned)
        self.assertNotIn('release',self.owner.events)
        self.assertNotIn('unlink',self.owner.events)

    def test_missing_slot_cannot_report_retention(self):
        self.owner.release_entry=lambda expected:False
        with self.assertRaises(ValueError):self.exercise()
        self.assertTrue(self.owner.pinned)
        self.assertNotIn('unlink',self.owner.events)

    def test_second_delete_must_be_absent(self):
        self.owner.release_entry=lambda expected:True
        with self.assertRaises(ValueError):self.exercise()
        self.assertTrue(self.owner.pinned)

    def test_failure_reports_stage_and_errno_without_message(self):
        def fail(report):
            report.update(stage='recover',receipt_retained=True,cgroup_retained=False)
            raise OSError(22,'private kernel data')
        with patch('scripts.probe_cgroup_retention_fixture._run',side_effect=fail):report=run_fixture()
        self.assertEqual(report['stage'],'recover')
        self.assertEqual(report['errno'],22)
        self.assertTrue(report['receipt_retained'])
        self.assertFalse(report['filters_loaded'])
        self.assertNotIn('private',json.dumps(report))

    def test_receipt_path_validation_before_any_filesystem_access(self):
        with patch('scripts.probe_cgroup_retention_fixture._receipt_parent') as parent:
            with self.assertRaises(ValueError):write_receipt(MapIdentity(7),'../x','bad',None)
        parent.assert_not_called()


if __name__=='__main__':unittest.main()
