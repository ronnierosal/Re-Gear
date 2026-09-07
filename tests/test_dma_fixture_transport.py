import array
import json
import socket
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

from scripts import dma_fixture_transport as transport


class TransportTests(unittest.TestCase):
    def setUp(self):
        for name,value in (('MSG_CMSG_CLOEXEC',0x40000000),('SCM_RIGHTS',1),('MSG_CTRUNC',8)):
            p=patch.object(socket,name,getattr(socket,name,value),create=True)
            p.start(); self.addCleanup(p.stop)
        if not hasattr(socket,'CMSG_SPACE'):
            p=patch.object(socket,'CMSG_SPACE',lambda n:n+32,create=True)
            p.start();self.addCleanup(p.stop)
        self.sock=Mock()
        for module,name,value in ((transport.signal,'SIGKILL',9),(transport.os,'O_NOFOLLOW',0x20000)):
            p=patch.object(module,name,getattr(module,name,value),create=True)
            p.start();self.addCleanup(p.stop)
        self.closed=[]
        p=patch.object(transport.os,'close',side_effect=self.closed.append)
        p.start();self.addCleanup(p.stop)

    def packet(self,raw=b'{"sequence":1}',fds=(41,),flags=0):
        ancillary=[] if not fds else [(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',fds).tobytes())]
        self.sock.recvmsg.return_value=(raw,ancillary,flags,None)

    def test_identity_and_every_fd_closed(self):
        self.packet()
        with patch.object(transport.os,'fstat',return_value=SimpleNamespace(st_dev=12,st_ino=34)):
            self.assertEqual(transport.receive_one(self.sock),dict(sequence=1,received=1,truncated=False,identity=[12,34]))
        self.assertEqual(self.closed,[41])

    def test_malformed_and_multiple_packets_close_all(self):
        for raw in (b'bad',b'{"sequence":true}',b'{"sequence":1,"sequence":1}',
                    b'{"sequence":2}',b'{"sequence":1,"other":1}',b'stop'):
            self.packet(raw=raw,fds=(41,42))
            with self.assertRaises(ValueError):transport.receive_one(self.sock,1)
        self.assertEqual(self.closed,[41,42]*6)

    def test_rejected_and_stop_are_distinct(self):
        self.packet(fds=(),flags=socket.MSG_CTRUNC)
        self.assertEqual(transport.receive_one(self.sock),dict(sequence=1,received=0,truncated=True,identity=None))
        self.packet(raw=b'stop',fds=())
        self.assertIsNone(transport.receive_one(self.sock))

    def test_partial_or_payload_truncation_rejected(self):
        for flags in (socket.MSG_CTRUNC,0x20):
            self.packet(flags=flags)
            with self.assertRaises(ValueError):transport.receive_one(self.sock)
        self.assertEqual(self.closed,[41,41])

    def test_fstat_failure_still_closes(self):
        self.packet()
        with patch.object(transport.os,'fstat',side_effect=OSError('fixture')):
            with self.assertRaises(OSError):transport.receive_one(self.sock)
        self.assertEqual(self.closed,[41])

    def response(self,value):
        self.sock.sendmsg.side_effect=lambda data,anc:len(data[0])
        self.sock.recvmsg.return_value=(json.dumps(value).encode(),[],0,None)

    def test_exchange_strict_schema_and_sequence(self):
        good=dict(sequence=1,received=1,truncated=False,identity=[12,34])
        self.response(good)
        self.assertEqual(transport.exchange(self.sock,8,1),good)
        for changes in (dict(sequence=True),dict(sequence=2),dict(received=True),
                        dict(identity=[True,34]),dict(identity=[12]),dict(truncated=1),
                        dict(extra=1),dict(received=0,identity=None)):
            self.response({**good,**changes})
            with self.assertRaises(ValueError):transport.exchange(self.sock,8,1)

    def test_unexpected_response_fds_closed(self):
        self.sock.sendmsg.side_effect=lambda data,anc:len(data[0])
        self.packet(fds=(41,42))
        with self.assertRaises(ValueError):transport.exchange(self.sock,8,1)
        self.assertEqual(self.closed,[41,42])

    def test_send_bounded_and_short_send(self):
        for seq in (0,17,True):
            with self.assertRaises(ValueError):transport.send_descriptor(self.sock,8,seq)
        self.sock.sendmsg.return_value=0
        with self.assertRaises(ValueError):transport.send_descriptor(self.sock,8,1)

    def test_receiver_closes_unrelated_before_enter_and_inventory_after(self):
        class Exit(BaseException):pass
        library=Mock();library.prctl.return_value=0
        self.sock.fileno.return_value=20;self.sock.send.return_value=5
        self.packet(raw=b'stop',fds=())
        with patch.object(transport.ctypes,'CDLL',return_value=library), \
             patch.object(transport.os,'getppid',return_value=99), \
             patch.object(transport.os,'getpid',return_value=123), \
             patch.object(transport,'_inventory',side_effect=({0,1,2,20,21,55},{20})), \
             patch.object(transport.os,'open',return_value=56), \
             patch.object(transport.os,'write',return_value=3), \
             patch.object(transport.os,'_exit',side_effect=Exit) as leave:
            with self.assertRaises(Exit):transport.receiver(self.sock,21,99,idle_timeout=60)
        self.assertEqual(set(self.closed),{0,1,2,55,56,21})
        leave.assert_called_once_with(0)
        self.sock.recv.assert_called_once_with(1,socket.MSG_PEEK)
        self.assertIn(((60,),{}),self.sock.settimeout.call_args_list)

    def test_receiver_invalid_idle_timeout_exits_before_setup(self):
        class Exit(BaseException):pass
        for value in (True,0,-1,61,float('nan'),float('inf')):
            with patch.object(transport.os,'_exit',side_effect=Exit) as leave, \
                 patch.object(transport.ctypes,'CDLL') as library:
                with self.assertRaises(Exit):transport.receiver(self.sock,21,99,idle_timeout=value)
                leave.assert_called_once_with(2)
                library.assert_not_called()


@unittest.skipUnless(sys.platform=='linux','Linux SCM_RIGHTS fixture')
class NativeTransportTests(unittest.TestCase):
    def test_native_socket_receipt_and_extra_descriptor_cleanup(self):
        left,right=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        fd=os.open('/dev/null',os.O_RDONLY)
        try:
            expected=os.fstat(fd)
            transport.send_descriptor(left,fd,1)
            before_peek=set(os.listdir('/proc/self/fd'))
            self.assertTrue(right.recv(1,socket.MSG_PEEK))
            self.assertEqual(set(os.listdir('/proc/self/fd')),before_peek)
            result=transport.receive_one(right)
            self.assertEqual(result,dict(sequence=1,received=1,truncated=False,
                identity=[expected.st_dev,expected.st_ino]))
            before=set(os.listdir('/proc/self/fd'))
            left.sendmsg([b'{"sequence":2}'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[fd,fd]))])
            with self.assertRaises(ValueError):transport.receive_one(right,2)
            self.assertEqual(set(os.listdir('/proc/self/fd')),before)
        finally:
            os.close(fd);left.close();right.close()


if __name__=='__main__':unittest.main()
