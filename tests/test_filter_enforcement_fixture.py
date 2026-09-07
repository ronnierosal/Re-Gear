import array
from contextlib import ExitStack
import errno
import json
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from scripts import probe_filter_enforcement_fixture as fixture


class EnforcementFixtureTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name,value in (('O_NOFOLLOW',0x100),('O_CLOEXEC',0x200)):
            self.stack.enter_context(patch.object(fixture.os,name,value,create=True))
        self.stack.enter_context(patch.object(fixture.os,'makedev',lambda major,minor:major*256+minor,create=True))
        for name,value in (('SCM_RIGHTS',1),('MSG_CTRUNC',8)):
            self.stack.enter_context(patch.object(fixture.socket,name,value,create=True))
        self.stack.enter_context(patch.object(fixture.socket,'CMSG_SPACE',lambda size:24,create=True))

    def test_direct_probe_opens_only_fixed_paths_and_closes_each(self):
        opener=Mock(side_effect=[10,11]);closer=Mock()
        stats=Mock(side_effect=[SimpleNamespace(st_mode=stat.S_IFCHR,st_rdev=259),SimpleNamespace(st_mode=stat.S_IFCHR,st_rdev=261)])
        self.assertEqual(fixture.open_controls(open_fd=opener,fstat=stats,close_fd=closer),dict(null_opened=True,zero_opened=True))
        self.assertEqual([call.args[0] for call in opener.call_args_list],['/dev/null','/dev/zero'])
        self.assertEqual([call.args[0] for call in closer.call_args_list],[10,11])

    def test_only_eperm_counts_as_direct_denial(self):
        opener=Mock(side_effect=[PermissionError(errno.EPERM,'denied'),11])
        result=fixture.open_controls(open_fd=opener,fstat=lambda fd:SimpleNamespace(st_mode=stat.S_IFCHR,st_rdev=261),close_fd=Mock())
        self.assertEqual(result,dict(null_opened=False,zero_opened=True))
        with self.assertRaises(PermissionError):fixture.open_controls(open_fd=Mock(side_effect=PermissionError(errno.EACCES,'unreadable')))

    def packet(self,data,descriptors=(),flags=0,other=()):
        ancillary=[(fixture.socket.SOL_SOCKET,fixture.socket.SCM_RIGHTS,array.array('i',descriptors).tobytes())] if descriptors else []
        sock=Mock();sock.recvmsg.return_value=(data,ancillary+list(other),flags,None)
        return sock

    def test_receipt_closes_descriptor_and_reports_separately(self):
        closer=Mock()
        result=fixture.receive_command(self.packet(b'fd',(42,)),close_fd=closer,
            fstat=lambda fd:SimpleNamespace(st_rdev=259),open_probe=Mock(side_effect=AssertionError()))
        self.assertEqual(result,dict(received=1,truncated=False,device=259));closer.assert_called_once_with(42)
        self.assertEqual(fixture.receive_command(self.packet(b'fd',flags=8)),dict(received=0,truncated=True,device=None))

    def test_control_descriptor_and_unknown_command_rejected_and_closed(self):
        for packet in (self.packet(b'open-controls',(42,)),self.packet(b'/dev/dri/card0',(42,)),self.packet(b'fd',(42,43))):
            closer=Mock();probe=Mock()
            with self.assertRaises(ValueError):fixture.receive_command(packet,close_fd=closer,open_probe=probe)
            self.assertGreaterEqual(closer.call_count,1);probe.assert_not_called()

    def test_unknown_ancillary_still_closes_rights(self):
        closer=Mock()
        with self.assertRaises(ValueError):fixture.receive_command(self.packet(b'fd',(42,),other=[(999,999,b'')]),close_fd=closer)
        closer.assert_called_once_with(42)

    def test_direct_protocol_has_strict_shape_and_boolean_values(self):
        sock=Mock();sock.send.return_value=13
        sock.recvmsg.return_value=(b'{"null_opened":false,"zero_opened":true}',[],0,None)
        self.assertTrue(fixture.probe_open_controls(sock,denied=True))
        sock.send.assert_called_with(b'open-controls')
        for raw in (b'{"null_opened":0,"zero_opened":true}',b'{"null_opened":false,"null_opened":true,"zero_opened":true}',b'x'*257):
            sock.recvmsg.return_value=(raw,[],0,None)
            with self.assertRaises(ValueError):fixture.probe_open_controls(sock,denied=True)

    def test_independent_flags_require_all_four_actual_direct_checks(self):
        def runner(**kwargs):
            self.assertIs(kwargs['receiver_factory'],fixture.enforcement_receiver)
            for denied in (False,True,True,False):
                self.assertTrue(kwargs['extra_probe'](Mock(),denied=denied))
            return dict(state='fixture_passed',direct_open_denial_verified=False)
        with patch.object(fixture,'probe_open_controls',return_value=True):report=fixture.run_fixture(runner=runner)
        self.assertTrue(report['direct_open_denial_verified']);self.assertTrue(report['scm_rights_denial_verified'])
        self.assertFalse(report['launch_authorized']);self.assertFalse(report['disconnect_clearance'])
        report=fixture.run_fixture(runner=lambda **kwargs:dict(state='fixture_passed'))
        self.assertEqual(report['state'],'fixture_failed');self.assertFalse(report['direct_open_denial_verified'])


if __name__=='__main__':unittest.main()
