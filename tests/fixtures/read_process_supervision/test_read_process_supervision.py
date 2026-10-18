"""Standalone device-free Linux fixtures for the actual production module.
No route, endpoint, credentials, private receipt, or device commands are imported.
"""
import importlib.util,os,signal,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock
_source=Path(__file__).absolute().parent/'read_process_supervision.py'
_spec=importlib.util.spec_from_file_location('read_process_supervision',_source)
supervision=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(supervision)


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


if __name__=='__main__':unittest.main(verbosity=2)
