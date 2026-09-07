import array
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
import stat
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from scripts import probe_device_receive_fixture as fixture


class ReceiveFixtureGuards(unittest.TestCase):
    def test_explicit_flag_required_before_any_mutation(self):
        with patch.object(sys,'argv',['probe']), patch.object(fixture,'run_fixture') as run:
            with self.assertRaises(SystemExit):fixture.main()
            run.assert_not_called()

    def test_nonroot_rejected_before_open(self):
        with patch.object(os,'geteuid',return_value=1000,create=True), patch('builtins.open') as opened:
            with self.assertRaises(ValueError):fixture.run_fixture()
            opened.assert_not_called()

    def test_cleanup_attempts_all_resources_after_owner_failure(self):
        owner=Mock();owner.close.side_effect=OSError('fixture')
        first,second=Mock(),Mock()
        identity=SimpleNamespace(st_dev=1,st_ino=2,st_mode=stat.S_IFDIR)
        with patch.object(os,'close') as close, patch.object(os,'waitpid',return_value=(123,0),create=True) as wait, \
                patch.object(os,'stat',return_value=identity), patch.object(os,'rmdir') as remove, \
                patch.object(os,'WNOHANG',1,create=True):
            with self.assertRaises(RuntimeError):
                fixture.cleanup_fixture(owner,(10,11),first,second,123,20,30,'owned',identity,True)
            self.assertEqual([c.args[0] for c in close.call_args_list],[10,11,20,30])
            first.close.assert_called_once();second.close.assert_called_once()
            wait.assert_called_once();remove.assert_called_once_with('owned',dir_fd=30)

    def test_cleanup_retains_replaced_directory_and_closes_parent(self):
        identity=SimpleNamespace(st_dev=1,st_ino=2,st_mode=stat.S_IFDIR)
        replacement=SimpleNamespace(st_dev=1,st_ino=3,st_mode=stat.S_IFDIR)
        with patch.object(os,'close') as close,patch.object(os,'stat',return_value=replacement), \
                patch.object(os,'rmdir') as remove:
            with self.assertRaises(RuntimeError):
                fixture.cleanup_fixture(None,(),None,None,None,20,30,'owned',identity,True)
            remove.assert_not_called()
            self.assertEqual([c.args[0] for c in close.call_args_list],[20,30])


@unittest.skipUnless(sys.platform=='linux','Linux descriptor passing required')
class ReceiveFixtureSockets(unittest.TestCase):
    def test_received_descriptor_is_classified_and_closed(self):
        left,right=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        descriptor=os.open('/dev/null',os.O_RDONLY)
        closed=[]
        realclose=os.close
        try:
            left.sendmsg([b'fd'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[descriptor]))])
            def close(fd):closed.append(fd);realclose(fd)
            with patch.object(fixture.os,'close',side_effect=close):result=fixture.receive_one(right)
            self.assertEqual(result,dict(received=1,truncated=False,device=os.fstat(descriptor).st_rdev))
            self.assertEqual(len(closed),1)
            with self.assertRaises(OSError):os.fstat(closed[0])
        finally:left.close();right.close();realclose(descriptor)

    def test_packet_without_rights_does_not_claim_denial(self):
        left,right=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        try:
            left.send(b'fd')
            self.assertEqual(fixture.receive_one(right),dict(received=0,truncated=False,device=None))
            left.send(b'stop')
            self.assertIsNone(fixture.receive_one(right))
        finally:left.close();right.close()

    def test_stop_packet_also_closes_received_rights(self):
        left,right=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        descriptor=os.open('/dev/null',os.O_RDONLY)
        closed=[];realclose=os.close
        try:
            left.sendmsg([b'stop'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[descriptor]))])
            def close(fd):closed.append(fd);realclose(fd)
            with patch.object(fixture.os,'close',side_effect=close):
                self.assertIsNone(fixture.receive_one(right))
            self.assertEqual(len(closed),1)
        finally:left.close();right.close();realclose(descriptor)
