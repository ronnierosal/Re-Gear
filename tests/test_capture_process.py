"""Device-free Linux containment in one dedicated, bounded worker process.

No private packets, artifact downloads, bridge operation, SSH or native reads.
Only synthetic Python children and fixture-owned temporary files are used.
"""
import ast
from contextlib import contextmanager, ExitStack
import ctypes
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from regear.adapters.steamos import capture_process as SUBJECT

OBSERVED={'fixture':'observed'}


def fixture_validator(raw,exit_code):
    if exit_code!=0 or json.loads(raw)!=OBSERVED:raise SUBJECT.Reject('fixture_output')
    return OBSERVED


def no_pid(pid):
    return not Path('/proc/'+str(pid)).exists()


def normalized(node):
    for child in ast.walk(node):
        if hasattr(child,'type_params'):delattr(child,'type_params')
    return ast.dump(node,include_attributes=False)


class CaptureIdentityOrderingTests(unittest.TestCase):
    @contextmanager
    def simulated(self, *, descendants=False, signal_failure=False):
        """Exercise the real supervisor with no process creation or OS signal."""
        state=SimpleNamespace(reaped=False,exited=not descendants,children=[456] if descendants else [],events=[])
        process=Mock(pid=123,returncode=None)
        def wait(**kwargs):
            state.reaped=True;process.returncode=0;state.events.append('reap');return 0
        process.wait.side_effect=wait
        process.poll.side_effect=lambda:wait() if state.exited else None
        def observe(*args):
            if state.reaped:raise ChildProcessError()
            return SimpleNamespace(si_pid=process.pid,si_code=1,si_status=0) if state.exited else None
        def signal_group(pid,sig):
            state.events.append(('signal',pid,sig,state.reaped))
            if signal_failure:raise PermissionError('synthetic refusal')
            state.exited=True
            if sig==9:state.children=[]
        def reap(exclude_pid=None):
            if state.exited and exclude_pid!=process.pid:wait()
        clock=[0.0]
        def tick():clock[0]+=.05;return clock[0]
        api=SimpleNamespace(Popen=Mock(return_value=process),DEVNULL=-3,PIPE=-1,TimeoutExpired=subprocess.TimeoutExpired)
        selector=Mock();selector.get_map.return_value={}
        with ExitStack() as stack:
            for target,name,kwargs in (
                (SUBJECT.ctypes,'CDLL',{'return_value':SimpleNamespace(prctl=lambda *args:0)}),
                (SUBJECT.selectors,'DefaultSelector',{'return_value':selector}),
                (SUBJECT.os,'waitid',{'create':True,'side_effect':observe}),
                (SUBJECT.os,'killpg',{'create':True,'side_effect':signal_group}),
                (SUBJECT.signal,'signal',{}),
                (SUBJECT.time,'monotonic',{'side_effect':tick}),
                (SUBJECT.time,'sleep',{}),
                (SUBJECT,'group_alive',{'side_effect':lambda pid:bool(state.children)}),
                (SUBJECT,'adopted_children',{'side_effect':lambda:([process.pid] if not state.reaped else [])+state.children}),
                (SUBJECT,'reap_adopted',{'side_effect':reap}),
                (SUBJECT,'kill_adopted',{'side_effect':lambda **kwargs:state.children.clear()}),
            ):stack.enter_context(patch.object(target,name,**kwargs))
            stack.enter_context(patch.multiple(SUBJECT.os,create=True,P_PID=1,WEXITED=4,WNOHANG=1,WNOWAIT=0x1000000,CLD_EXITED=1,CLD_KILLED=2,CLD_DUMPED=3))
            stack.enter_context(patch.multiple(SUBJECT.signal,create=True,SIGHUP=1,SIGTERM=15,SIGINT=2,SIGKILL=9))
            state.process=process;state.api=api
            yield state

    def test_success_keeps_launcher_identity_until_final_group_signal(self):
        with self.simulated() as state:
            result=SUBJECT.supervise(('synthetic',),cwd='.',environment={},validator=lambda raw,code:OBSERVED,process_api=state.api)
            self.assertEqual(result,('bridge.completed',OBSERVED,True))
            signals=[event for event in state.events if isinstance(event,tuple)]
            self.assertTrue(signals)
            self.assertTrue(all(not event[3] for event in signals),state.events)
            self.assertEqual(state.events[-1],'reap')

    def test_escalation_keeps_launcher_pinned_through_sigkill(self):
        with self.simulated(descendants=True) as state:
            self.assertTrue(SUBJECT.close_group(state.process))
            signals=[event for event in state.events if isinstance(event,tuple)]
            self.assertEqual([event[2] for event in signals],[15,9])
            self.assertTrue(all(not event[3] for event in signals),state.events)
            self.assertEqual(state.events[-1],'reap')

    def test_lost_launcher_identity_refuses_numeric_group_signal(self):
        with self.simulated() as state:
            state.reaped=True;state.process.returncode=0
            self.assertFalse(SUBJECT.close_group(state.process))
            self.assertEqual(state.events,[])

    def test_signal_refusal_withdraws_valid_capture(self):
        with self.simulated(signal_failure=True) as state:
            result=SUBJECT.supervise(('synthetic',),cwd='.',environment={},validator=lambda raw,code:OBSERVED,process_api=state.api)
            self.assertEqual(result,('bridge.cleanup_unconfirmed',None,False))
            self.assertFalse(state.reaped)

    def test_final_wait_uncertainty_withdraws_valid_capture(self):
        with self.simulated() as state:
            state.process.wait.side_effect=subprocess.TimeoutExpired('synthetic',.1)
            result=SUBJECT.supervise(('synthetic',),cwd='.',environment={},validator=lambda raw,code:OBSERVED,process_api=state.api)
            self.assertEqual(result,('bridge.cleanup_unconfirmed',None,False))

    def test_wrong_launcher_observation_never_signals_group(self):
        with self.simulated() as state, patch.object(SUBJECT.os,'waitid',return_value=SimpleNamespace(si_pid=999,si_code=1,si_status=0)):
            result=SUBJECT.supervise(('synthetic',),cwd='.',environment={},validator=lambda raw,code:OBSERVED,process_api=state.api)
            self.assertEqual(result,('bridge.cleanup_unconfirmed',None,False))
            self.assertEqual(state.events,[])


class CaptureProcessTests(unittest.TestCase):
    def test_unchanged_cleanup_helpers_and_limits(self):
        # The three reaping/signaling helpers intentionally diverge to retain
        # launcher identity; their old hashes remain historical, not acceptance.
        # Identity-order regressions above replace only those obsolete hashes.
        expected={'group_alive': '5a310c3057e7eca40919bdf843a3f3aa05d6cd3e90e4c5713c09a6421edd53ff', 'adopted_children': 'a67f0a303b278ce0f7360bbc151c8ff8d42fe49c991410f6e92d6f11d739c175'}
        for name,digest in expected.items():
            node=ast.parse(inspect.getsource(getattr(SUBJECT,name))).body[0]
            self.assertEqual(digest,hashlib.sha256(normalized(node).encode()).hexdigest(),name)
        self.assertEqual((6.0,4096,2048,6144,.2,1.0),(SUBJECT.LAUNCH_SECONDS,SUBJECT.STDOUT_CAP,SUBJECT.STDERR_CAP,SUBJECT.TOTAL_CAP,SUBJECT.TERM_SECONDS,SUBJECT.REAP_SECONDS))

    @unittest.skipUnless(sys.platform=='linux','Real Linux process APIs are exercised by the blocking Linux CI job')
    def test_device_free_linux_worker(self):
        argv=(sys.executable,'-I','-S','-B',str(Path(__file__).resolve()),'--fixture-worker')
        process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        try:
            out,err=process.communicate(timeout=45)
        except BaseException:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait(timeout=2)
            raise
        finally:
            process.stdout.close();process.stderr.close()
        self.assertEqual(0,process.returncode,(out+err).decode(errors='replace'))
        receipt=json.loads(out)
        self.assertEqual(13,receipt['tests_run']);self.assertEqual(0,receipt['skipped'])
        self.assertEqual('PASS',receipt['result'],receipt)
        print('Device-free Linux containment: '+json.dumps(receipt,sort_keys=True))


def worker_main():
    class LinuxFixtures(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            if sys.platform != 'linux': raise RuntimeError('Linux required; no installation or fallback permitted')
            required=(hasattr(os,'pidfd_open'),hasattr(signal,'pidfd_send_signal'),
                      hasattr(os,'O_NOFOLLOW'),hasattr(os,'O_DIRECTORY'),
                      shutil.rmtree.avoids_symlink_attacks,'dir_fd' in inspect.signature(shutil.rmtree).parameters,
                      Path(sys.executable).is_file(),Path('/proc/self/task').is_dir())
            if not all(required): raise RuntimeError('required_platform_API_missing')
            libc=ctypes.CDLL(None,use_errno=True)
            if libc.prctl(36,1,0,0,0)!=0:raise RuntimeError('subreaper_unavailable')

        def setUp(self):
            self.temp=tempfile.TemporaryDirectory(prefix='regear-device-free-')
            self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
            self.old_handlers={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP)}
            self.addCleanup(lambda:[signal.signal(s,h) for s,h in self.old_handlers.items()])
            self.addCleanup(self.emergency_fixture_reap)
            self.pids=self.root/'fixture-pids'

        def emergency_fixture_reap(self):
            # Dedicated test process owns no unrelated children. This is only a safety
            # fallback after assertions have already recorded a supervisor failure.
            deadline=time.monotonic()+2
            while time.monotonic()<deadline:
                children=SUBJECT.adopted_children()
                if not children:return
                for pid in children:
                    try:
                        fd=os.pidfd_open(pid)
                        try:
                            if b'PPid:\t'+str(os.getpid()).encode()+b'\n' not in Path('/proc/'+str(pid)+'/status').read_bytes():
                                raise RuntimeError('fixture_cleanup_parent_mismatch')
                            signal.pidfd_send_signal(fd,signal.SIGKILL)
                        finally:os.close(fd)
                    except (ProcessLookupError,FileNotFoundError):pass
                SUBJECT.reap_adopted();time.sleep(.01)
            raise RuntimeError('fixture_descendant_cleanup_unconfirmed')

        def synthetic(self, body):
            source=self.root/'synthetic-source';(source/'scripts').mkdir(parents=True)
            prologue='import os,sys,time,json,subprocess\nPIDS='+repr(str(self.pids))+'\n'
            prologue+="def record():\n with open(PIDS,'a') as f:f.write(str(os.getpid())+'\\n');f.flush()\nrecord()\n"
            (source/'scripts/fixture_child.py').write_text(prologue+body)
            return source

        def run_fixture(self, body):
            source=self.synthetic(body)
            real=subprocess.Popen;calls=[]
            def fixed_spawn(argv, **kwargs):
                self.assertEqual(tuple(argv),(sys.executable,'-I','-S','-B',str(source/'scripts/fixture_child.py')))
                self.assertFalse(kwargs['shell']);self.assertTrue(kwargs['start_new_session'])
                calls.append(argv);return real(argv,**kwargs)
            with patch.object(subprocess,'Popen',side_effect=fixed_spawn):
                result=SUBJECT.supervise((sys.executable,'-I','-S','-B',str(source/'scripts/fixture_child.py')),cwd=source,environment={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C'},validator=fixture_validator,process_api=subprocess)
            self.assertEqual(len(calls),1)
            pids=[int(x) for x in self.pids.read_text().split()] if self.pids.exists() else []
            for pid in pids:self.assertTrue(no_pid(pid),'fixture child still exists: '+str(pid))
            self.assertEqual(SUBJECT.adopted_children(),[])
            return result

        def test_successful_exit_cleanup(self):
            result=self.run_fixture('print('+repr(json.dumps(OBSERVED))+')\n')
            self.assertEqual(result,('bridge.completed',OBSERVED,True))

        def test_real_six_second_timeout(self):
            before=time.monotonic();result=self.run_fixture('time.sleep(60)\n')
            self.assertEqual(result,('bridge.rejected',None,True))
            self.assertGreaterEqual(time.monotonic()-before,6)
            self.assertLess(time.monotonic()-before,9)

        def test_stdout_overflow(self):
            self.assertEqual(self.run_fixture("os.write(1,b'x'*5000);time.sleep(60)\n"),('bridge.rejected',None,True))

        def test_stderr_overflow(self):
            self.assertEqual(self.run_fixture("os.write(2,b'x'*3000);time.sleep(60)\n"),('bridge.rejected',None,True))

        def test_descendant_holding_pipes(self):
            child="import os,time;f=open("+repr(str(self.pids))+",'a');f.write(str(os.getpid())+'\\n');f.close();time.sleep(60)"
            result=self.run_fixture('subprocess.Popen([sys.executable,"-I","-S","-B","-c",'+repr(child)+']);time.sleep(.1)\n')
            self.assertEqual(result,('bridge.rejected',None,True))

        def test_escaped_session_adopted_killed_and_reaped(self):
            body="pid=os.fork()\nif pid==0:\n os.setsid();record();os.close(1);os.close(2);time.sleep(60);os._exit(0)\n"
            body+="time.sleep(.15);print("+repr(json.dumps(OBSERVED))+")\n"
            self.assertEqual(self.run_fixture(body),('bridge.completed',OBSERVED,True))
            self.assertGreaterEqual(len(self.pids.read_text().split()),2)

        def test_real_interruption_cleanup(self):
            signal.signal(signal.SIGINT,signal.default_int_handler)
            timer=threading.Timer(.3,lambda:os.kill(os.getpid(),signal.SIGINT));timer.start()
            try:result=self.run_fixture('time.sleep(60)\n')
            finally:timer.cancel();timer.join()
            self.assertEqual(result,('bridge.rejected',None,True))

        def test_uncertain_cleanup_withdraws_result_after_real_reap(self):
            real=SUBJECT.close_group
            def uncertain(process):self.assertTrue(real(process));return False
            with patch.object(SUBJECT,'close_group',side_effect=uncertain):
                result=self.run_fixture('print('+repr(json.dumps(OBSERVED))+')\n')
            self.assertEqual(result,('bridge.cleanup_unconfirmed',None,False))

        def test_real_child_signal_refusal_withdraws_capture(self):
            source=self.synthetic('print('+repr(json.dumps(OBSERVED))+')\n')
            with patch.object(SUBJECT.os,'killpg',side_effect=PermissionError('synthetic signal refusal')):
                result=SUBJECT.supervise((sys.executable,'-I','-S','-B',str(source/'scripts/fixture_child.py')),cwd=source,environment={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C'},validator=fixture_validator,process_api=subprocess)
            self.assertEqual(result,('bridge.cleanup_unconfirmed',None,False))
            self.emergency_fixture_reap()
            self.assertEqual(SUBJECT.adopted_children(),[])

        def owned(self):
            home=self.root/'home';home.mkdir();root=home/'.capture-fixture.ABCD1234';root.mkdir(mode=0o700)
            return home,root

        def test_real_fd_relative_owned_source_removal(self):
            home,root=self.owned();(root/'source').mkdir();(root/'source/a.py').write_text('pass\n')
            before=SUBJECT.owned_root(root,parent=home,prefix='.capture-fixture.')
            self.assertTrue(SUBJECT.remove_owned_root(root,before,parent=home,prefix='.capture-fixture.'))
            self.assertFalse(root.exists())

        def test_inode_substitution_rejected(self):
            home,root=self.owned();original=root.lstat();root.rename(home/'old-owned');root.mkdir(mode=0o700)
            (root/'keep').write_text('fixture')
            self.assertFalse(SUBJECT.remove_owned_root(root,original,parent=home,prefix='.capture-fixture.'))
            self.assertTrue((root/'keep').exists())

        def test_symlink_root_rejected(self):
            home,root=self.owned();root.rmdir();target=self.root/'other-fixture';target.mkdir();root.symlink_to(target,target_is_directory=True)
            with self.assertRaises(SUBJECT.Reject):SUBJECT.owned_root(root,parent=home,prefix='.capture-fixture.')
            self.assertTrue(target.exists())

        def test_symlink_child_does_not_escape_cleanup(self):
            home,root=self.owned();outside=self.root/'other-fixture';outside.mkdir();(outside/'keep').write_text('fixture')
            (root/'symlink').symlink_to(outside,target_is_directory=True)
            self.assertTrue(SUBJECT.remove_owned_root(root,SUBJECT.owned_root(root,parent=home,prefix='.capture-fixture.'),parent=home,prefix='.capture-fixture.'))
            self.assertTrue((outside/'keep').exists())
    stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LinuxFixtures))
    receipt=dict(tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),result='PASS' if result.wasSuccessful() and result.testsRun==13 and not result.skipped else 'FAIL',python=platform.python_version(),kernel=platform.release(),device_contact=False)
    if not result.wasSuccessful():receipt['fixture_log']=stream.getvalue()
    print(json.dumps(receipt,sort_keys=True))
    return 0 if receipt['result']=='PASS' else 1


if __name__=='__main__':
    if sys.argv[1:]==['--fixture-worker']:raise SystemExit(worker_main())
    unittest.main()
