"""Standalone device-free Linux fixtures for the actual production module.
No route, endpoint, credentials, private receipt, or device commands are imported.
"""
import importlib.util,os,signal,sys,tempfile,time,unittest
import json
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock
_source=Path(__file__).absolute().parent/'read_process_supervision.py'
_spec=importlib.util.spec_from_file_location('read_process_supervision',_source)
supervision=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(supervision)


def wire(body):return supervision.FRAME_MAGIC+len(body).to_bytes(4,'big')+body


class FramingProtocolFixtures(unittest.TestCase):
    def test_roundtrip_and_fragmented_header(self):
        value={'fixture':[1,True,None,'text']};packet=supervision.frame_result(value,1024)
        for end in range(8):self.assertIsNone(supervision.frame_length(packet[:end],1024))
        for end in range(8,len(packet)+1):self.assertEqual(supervision.frame_length(packet[:end],1024),len(packet))
        self.assertEqual(supervision.decode_result(packet,1024),value)

    def test_truncated_headers_and_bodies(self):
        packet=supervision.frame_result(True,1024)
        for end in range(len(packet)):
            with self.subTest(end=end),self.assertRaises(supervision.GuardFailure):supervision.decode_result(packet[:end],1024)

    def test_invalid_zero_and_oversized_length(self):
        for packet in (b'BAD!'+(5).to_bytes(4,'big')+b'hello',
                       supervision.FRAME_MAGIC+b'\0'*4,
                       supervision.FRAME_MAGIC+(1025).to_bytes(4,'big'),
                       supervision.FRAME_MAGIC+(2**32-1).to_bytes(4,'big')):
            with self.assertRaises(supervision.GuardFailure):supervision.frame_length(packet,1024)

    def test_trailing_bytes_second_frame_and_json_document(self):
        packet=supervision.frame_result(True,1024)
        for data in (packet+b'x',packet+packet,wire(b'{"ok":true,"value":1} '),
                     wire(b'{"ok":true,"value":1}{}')):
            with self.assertRaises(supervision.GuardFailure):supervision.decode_result(data,1024)

    def test_malformed_duplicate_nonfinite_and_envelope_fields(self):
        bodies=(b'\xff',b'no json',b' {"ok":true,"value":1}',
                b'{"ok":true,"ok":true,"value":1}',b'{"ok":true,"value":{"x":1,"x":2}}',
                b'{"ok":true,"value":NaN}',b'{"ok":true,"value":1e999}',
                b'{"ok":true,"value":{"nested":-1e999}}',b'{"ok":1,"value":1}',b'{"ok":true}',
                b'{"ok":true,"value":1,"extra":2}',b'{"ok":false,"error":"raw unknown"}',
                b'{"ok":false,"error":{}}',b'{"ok":true,"value":'+b'['*33+b'0'+b']'*33+b'}')
        for body in bodies:
            with self.subTest(body=body[:40]),self.assertRaises(supervision.GuardFailure):supervision.decode_result(wire(body),1024)

    def test_postcleanup_requires_eof_and_rejects_late_trailing(self):
        packet=supervision.frame_result(True,1024)
        with patch.object(supervision.os,'read',return_value=b''):
            self.assertIs(supervision.drain_result_after_cleanup(10,packet,1024),True)
        for effect in (b'x',BlockingIOError()):
            with patch.object(supervision.os,'read',side_effect=effect if isinstance(effect,BaseException) else None,return_value=effect):
                with self.assertRaises(supervision.GuardFailure):supervision.drain_result_after_cleanup(10,packet,1024)

    def test_nonserializable_and_oversized_worker_result_rejected(self):
        for value in (object(),float('nan'),'x'*8192):
            with self.assertRaises(supervision.GuardFailure):supervision.decode_result(supervision.frame_result(value,128),128)


class FramedParentCleanupFixtures(unittest.TestCase):
    def run_parent(self,packet,cleanup_error=None,trailing=b''):
        order=[];selector=Mock();selector.select.return_value=[(None,None)]
        reads=iter((packet,trailing))
        def read(*args):order.append('read');return next(reads)
        def cleanup(*args):
            order.append('cleanup')
            if cleanup_error:raise cleanup_error
        flags={name:getattr(signal,name,i+1) for i,name in enumerate(('SIGTERM','SIGINT','SIGHUP','SIG_BLOCK','SIG_SETMASK'))}
        with patch.object(supervision,'set_subreaper'),patch.object(supervision,'children',return_value=[]), \
             patch.object(supervision.selectors,'DefaultSelector',return_value=selector), \
             patch.object(supervision.os,'pipe2',return_value=(10,11),create=True), \
             patch.object(supervision.os,'O_CLOEXEC',0,create=True),patch.object(supervision.os,'O_NONBLOCK',0,create=True), \
             patch.object(supervision.os,'fork',return_value=123,create=True),patch.object(supervision.os,'close'), \
             patch.object(supervision.os,'read',side_effect=read), \
             patch.object(supervision.signal,'pthread_sigmask',return_value=set(),create=True), \
             patch.multiple(supervision.signal,create=True,**flags),patch.object(supervision.signal,'signal'), \
             patch.object(supervision,'cleanup',side_effect=cleanup):
            try:return supervision.guard_call(lambda:None),order
            except BaseException as exc:return exc,order

    def test_complete_frame_cleanup_then_drain_before_acceptance(self):
        value,order=self.run_parent(supervision.frame_result(True,1024))
        self.assertIs(value,True);self.assertEqual(order,['read','cleanup','read'])

    def test_complete_frame_never_bypasses_failed_cleanup(self):
        value,order=self.run_parent(supervision.frame_result(True,1024),supervision.GuardFailure())
        self.assertIsInstance(value,supervision.GuardFailure);self.assertEqual(order,['read','cleanup'])

    def test_bad_frame_still_cleans_and_late_bytes_still_reject(self):
        value,order=self.run_parent(b'BAD!'+b'\0'*4)
        self.assertIsInstance(value,supervision.GuardFailure);self.assertEqual(order,['read','cleanup'])
        value,order=self.run_parent(supervision.frame_result(True,1024),trailing=b'x')
        self.assertIsInstance(value,supervision.GuardFailure);self.assertEqual(order,['read','cleanup','read'])


class GenericCommandIdentityFixture(unittest.TestCase):
    def test_group_signal_precedes_leader_reap(self):
        order=[];process=Mock(pid=123)
        process.stdout.fileno.return_value=10;process.stderr.fileno.return_value=11
        process.wait.side_effect=lambda **kwargs:(order.append('wait') or 0)
        selector=Mock();selector.get_map.return_value={}
        flags={name:getattr(os,name,1) for name in ('P_PID','WEXITED','WNOHANG','WNOWAIT','CLD_EXITED')}
        with patch.object(supervision.subprocess,'Popen',return_value=process), \
             patch.object(supervision.selectors,'DefaultSelector',return_value=selector), \
             patch.object(supervision.os,'set_blocking'),patch.multiple(supervision.os,create=True,**flags), \
             patch.object(supervision.os,'waitid',create=True,return_value=Mock(si_status=0,si_code=flags['CLD_EXITED'])), \
             patch.object(supervision.os,'killpg',create=True,side_effect=lambda *args:order.append('kill')), \
             patch.object(supervision.signal,'SIGKILL',9,create=True):
            self.assertEqual(supervision.bounded_command(('fixture',),time.monotonic()+2,lambda count:None),b'')
        self.assertEqual(order,['kill','wait'])

@unittest.skipUnless(sys.platform=='linux','real Linux fork/pidfd fixtures require a Linux executor; no device needed')
class LinuxSupervisionFixtures(unittest.TestCase):
    def test_normal_result_and_no_children(self):
        self.assertEqual(supervision.guard_call(lambda:{'fixture':True}),{'fixture':True})
        self.assertEqual(supervision.children(),[])

    def test_blocked_worker_has_finite_timeout(self):
        start=time.monotonic()
        with self.assertRaises(supervision.GuardFailure):
            supervision.guard_call(lambda:time.sleep(10),.8,.3)
        self.assertLess(time.monotonic()-start,1.2);self.assertEqual(supervision.children(),[])

    def test_escaped_descendant_is_reaped(self):
        def action():
            ready_read,ready_write=os.pipe()
            child=os.fork()
            if child==0:
                os.close(ready_read);os.setsid();os.write(ready_write,b'1');os.close(ready_write)
                time.sleep(10);os._exit(0)
            os.close(ready_write)
            ready=os.read(ready_read,1);os.close(ready_read)
            if ready!=b'1':raise RuntimeError('fixture setup failed')
            return {'spawned':True}
        self.assertEqual(supervision.guard_call(action),{'spawned':True})
        self.assertEqual(supervision.children(),[])

    def test_output_ceiling_rejects(self):
        with self.assertRaises(supervision.GuardFailure):supervision.guard_call(lambda:'x'*65536,cap=1024)
        self.assertEqual(supervision.children(),[])

    def test_blocking_fifo_open_is_contained(self):
        with tempfile.TemporaryDirectory() as directory:
            fifo=Path(directory)/'fixture';os.mkfifo(fifo)
            def action():
                with fifo.open('rb') as f:f.read(1)
            with self.assertRaises(supervision.GuardFailure):supervision.guard_call(action,.8,.3)
        self.assertEqual(supervision.children(),[])

    def test_signal_masks_restored(self):
        before=signal.pthread_sigmask(signal.SIG_BLOCK,())
        supervision.guard_call(lambda:True)
        self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK,()),before)

    def test_native_command_combined_overflow(self):
        def action():
            counts=[]
            try:
                supervision.bounded_command((sys.executable,'-c','import sys;sys.stdout.write("x"*5000);sys.stderr.write("y"*5000)'),time.monotonic()+2,counts.append)
            except supervision.ReadFailure as exc:return {'code':exc.code,'bytes':sum(counts)}
        result=supervision.guard_call(action)
        self.assertEqual(result['code'],'output_bound');self.assertGreater(result['bytes'],8192)

    def test_postfork_actual_registration_failure_cleans(self):
        class BadRegister:
            def register(self,*args):raise OSError
            def close(self):pass
        with patch.object(supervision.selectors,'DefaultSelector',BadRegister):
            with self.assertRaises(OSError):supervision.guard_call(lambda:time.sleep(10))
        self.assertEqual(supervision.children(),[])

    def test_real_pipe_rejects_adversarial_frames_and_reaps(self):
        packets=(b'BAD!'+b'\0'*4,wire(b'{"ok":true,"value":1}')+b'extra',
                 wire(b'{"ok":true,"value":1}')[:-1],
                 supervision.FRAME_MAGIC+(1025).to_bytes(4,'big'),
                 wire(b'{"ok":true,"ok":true,"value":1}'),wire(b'{"ok":true,"value":NaN}'))
        for packet in packets:
            with self.subTest(packet=packet[:32]),patch.object(supervision,'frame_result',return_value=packet):
                with self.assertRaises(supervision.GuardFailure):supervision.guard_call(lambda:None,cap=1024)
            self.assertEqual(supervision.children(),[])

    def test_truncated_frame_with_escaped_writer_rejects_and_reaps(self):
        def action():
            read_fd,write_fd=os.pipe();child=os.fork()
            if child==0:
                os.close(read_fd);os.setsid();os.write(write_fd,b'1');os.close(write_fd)
                time.sleep(10);os._exit(0)
            os.close(write_fd);ready=os.read(read_fd,1);os.close(read_fd)
            if ready!=b'1':raise RuntimeError('fixture setup failed')
            return True
        packet=wire(b'{"ok":true,"value":1}')[:-1]
        with patch.object(supervision,'frame_result',return_value=packet):
            with self.assertRaises(supervision.GuardFailure):supervision.guard_call(action,.8,.3,1024)
        self.assertEqual(supervision.children(),[])


if __name__=='__main__':unittest.main(verbosity=2)
