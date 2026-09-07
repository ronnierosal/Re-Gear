import ctypes
import errno
import unittest
from unittest.mock import patch
from backend.hdm.delivery.cgroup_retention_map import CgroupRetentionMap, MapIdentity, MapInfo, UpdateAttr


class RetentionMapTests(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.closed=[];self.failure=None;self.error=errno.EPERM
        self.kind=8;self.identifier=11;self.entries=1
        def syscall(number,command,pointer,size):
            self.assertEqual(number,321)
            attr=pointer._obj;self.calls.append(command)
            if command==self.failure:
                ctypes.set_errno(self.error);return -1
            if command==0:
                self.assertEqual((attr.map_type,attr.key_size,attr.value_size,attr.max_entries,attr.map_flags),(8,4,4,1,0))
                return 20
            if command==15:
                info=MapInfo.from_address(attr.info)
                info.type=self.kind;info.id=self.identifier;info.key_size=info.value_size=4
                info.max_entries=self.entries;return 0
            if command in (2,3):
                self.assertEqual(attr.map_fd,20)
                self.assertEqual(ctypes.c_uint32.from_address(attr.key).value,0)
                self.assertEqual(attr.flags,0)
                if command==2:self.assertEqual(ctypes.c_uint32.from_address(attr.value).value,9)
                else:self.assertEqual(attr.value,0)
                return 0
            if command in (6,7):
                self.assertEqual(ctypes.string_at(attr.pathname),b'/proc/self/fd/12/'+b'a'*64)
                self.assertEqual(attr.file_flags,0)
                return 0 if command==6 else 20
            raise AssertionError('unexpected command')
        with patch('platform.system',return_value='Linux'),patch('platform.machine',return_value='x86_64'):
            self.owner=CgroupRetentionMap(syscall=syscall,close_fd=self.closed.append)

    def test_fixed_create_update_identity_and_close(self):
        self.assertEqual(UpdateAttr.key.offset,8)
        self.assertEqual(UpdateAttr.flags.offset,24)
        self.assertEqual(self.owner.create(9),MapIdentity(11))
        self.assertEqual(self.calls,[0,15,2,15])
        self.owner.close();self.owner.close()
        self.assertEqual(self.closed,[20]);self.assertNotIn(3,self.calls)

    def test_create_failures_close_acquired_only(self):
        for failure,closed in ((0,[]),(15,[20]),(2,[20])):
            self.failure=failure;self.closed.clear()
            with self.assertRaises(OSError):self.owner.create(9)
            self.assertEqual(self.closed,closed);self.assertIsNone(self.owner.map_fd)

    def test_metadata_and_preowned_refusal(self):
        self.kind=1
        with self.assertRaises(ValueError):self.owner.create(9)
        self.assertEqual(self.closed,[20])
        self.owner.map_fd=99;self.calls.clear()
        with self.assertRaises(RuntimeError):self.owner.create(9)
        with self.assertRaises(RuntimeError):self.owner.recover(12,'a'*64,MapIdentity(11))
        self.assertEqual(self.calls,[])

    def test_exclusive_pin_propagates_existing_name(self):
        self.owner.create(9);self.calls.clear()
        self.failure=6;self.error=errno.EEXIST
        with self.assertRaises(FileExistsError):self.owner.pin(12,'a'*64,MapIdentity(11))
        self.assertEqual(self.calls,[15,6]);self.assertEqual(self.closed,[])

    def test_recovered_wrong_identity_closes_no_mutation(self):
        with self.assertRaises(ValueError):self.owner.recover(12,'a'*64,MapIdentity(12))
        self.assertEqual(self.calls,[7,15]);self.assertEqual(self.closed,[20])

    def test_recover_exact_and_explicit_entry_release(self):
        self.assertEqual(self.owner.recover(12,'a'*64,MapIdentity(11)),20)
        self.assertTrue(self.owner.release_entry(MapIdentity(11)))
        self.failure=3;self.error=errno.ENOENT
        self.assertFalse(self.owner.release_entry(MapIdentity(11)))
        self.error=errno.EPERM
        with self.assertRaises(PermissionError):self.owner.release_entry(MapIdentity(11))
        self.calls.clear()
        with self.assertRaises(ValueError):self.owner.release_entry(MapIdentity(12))
        self.assertEqual(self.calls,[15])

    def test_input_bounds_no_syscall(self):
        for value in (True,-1,2**31):
            with self.assertRaises(ValueError):self.owner.create(value)
        for token in ('a'*63,'A'*64,'../x'):
            with self.assertRaises(ValueError):self.owner.recover(12,token,MapIdentity(11))
        for value in (True,0,2**32):
            with self.assertRaises(ValueError):MapIdentity(value)
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
