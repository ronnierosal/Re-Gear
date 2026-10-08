"""Software children exercise bounded transport without contacting any bus."""
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from regear.adapters.steamos import commands

Runner = commands.InputPlumberReadCommandRunner
BASE = Runner.PREFIX
ID = BASE + ('call', 'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetId')
OWNER = BASE + ('call', 'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetNameOwner', 's', Runner.SERVICE)
INTROSPECT = BASE + ('call', ':1.24', '/org/shadowblip/InputPlumber', 'org.freedesktop.DBus.Introspectable', 'Introspect')
PROP = BASE + ('call', ':1.24', '/org/shadowblip/InputPlumber/Manager', 'org.freedesktop.DBus.Properties', 'Get', 'ss', 'org.shadowblip.InputManager', 'Version')

class TransportRegression(unittest.TestCase):
    def child(self, code, runner=None, argv=ID):
        real = subprocess.Popen
        processes = []
        def spawn(actual, **kwargs):
            self.assertEqual(actual, argv)
            self.assertFalse(kwargs['shell'])
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
            self.assertEqual(kwargs['env'], {'LANG':'C','LC_ALL':'C','PATH':'/usr/bin:/bin'})
            self.assertTrue(kwargs['close_fds'])
            p = real((sys.executable, '-c', code), **kwargs)
            processes.append(p)
            return p
        with patch.object(commands.subprocess, 'Popen', side_effect=spawn):
            result = (runner or Runner()).run(argv)
        for p in processes:
            self.assertIsNotNone(p.poll())
            self.assertTrue(p.stdout.closed)
            self.assertTrue(p.stderr.closed)
        return result

    def test_success_and_exact_flags(self):
        for argv in (ID, OWNER, INTROSPECT, PROP):
            self.assertTrue(self.child("print('evidence')", argv=argv).ok)

    def test_mutation_arbitrary_method_and_ownership_rejected_before_spawn(self):
        bad = [('/usr/bin/busctl','set-property'), BASE+('tree',':1.24'),
               BASE+('call',':1.24','/org/shadowblip/InputPlumber','org.shadowblip.InputManager','CreateTargetDevice'),
               BASE+('get-property','org.shadowblip.InputPlumber',*PROP[-3:]),
               BASE+('get-property',':1.24','/org/freedesktop/systemd1','org.shadowblip.InputManager','Version'),
               BASE+('get-property',':1.24','/org/shadowblip/InputPlumber/Manager',PROP[-2],'ManageAllDevices'),
               PROP[:-1]+('ManageAllDevices',), PROP[:-2]+('org.freedesktop.systemd1.Manager','Version'),
               PROP[:len(BASE)+2]+('/org/freedesktop/systemd1',)+PROP[len(BASE)+3:],
               BASE+('get-property',':1.24','/org/shadowblip/InputPlumber/Manager','org.shadowblip.InputManager','Version'),
               BASE+('call',':1.24','/org/shadowblip/InputPlumberX','org.freedesktop.DBus.Introspectable','Introspect'),
               BASE+('get-property',':1.24','/org/shadowblip/InputPlumber/Manager','org.freedesktop.systemd1.Manager','Version'),
               ('/tmp/busctl',)+ID[1:], ID+('extra',), list(ID[:-1])+[object()], 'busctl']
        with patch.object(commands.subprocess,'Popen') as spawn:
            for argv in bad:
                with self.assertRaises(ValueError): Runner().run(argv)
            spawn.assert_not_called()

    def test_constructor_rejects_unbounded_limits(self):
        for kwargs in ({'timeout_seconds':float('nan')},{'timeout_seconds':4},
                       {'max_calls':513},{'max_output_bytes':1048577}, {'max_calls':True}):
            with self.assertRaises(ValueError): Runner(**kwargs)

    def test_aggregate_count_no_later_spawn(self):
        runner=Runner(max_calls=1)
        self.assertTrue(self.child("print('ok')",runner).ok)
        with patch.object(commands.subprocess,'Popen') as spawn:
            self.assertEqual(runner.run(ID).error,'inputplumber.budget_exhausted')
            spawn.assert_not_called()

    def test_aggregate_stdout_stderr_budget(self):
        runner=Runner(max_output_bytes=10)
        self.assertTrue(self.child("import os;os.write(1,b'1234');os.write(2,b'5678')",runner).ok)
        result=self.child("print('abc')",runner)
        self.assertEqual(result.error,'inputplumber.output_limit')
        self.assertEqual(result.stdout,'')

    def test_running_huge_stdout_and_stderr_are_reaped(self):
        for fd in (1,2):
            result=self.child(f"import os,time;os.write({fd},b'x'*1000000);time.sleep(20)",Runner(max_output_bytes=1024))
            self.assertEqual(result.error,'inputplumber.output_limit')

    def test_timeout_kills_reaps_ignoring_terminate(self):
        result=self.child("import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(20)",Runner(timeout_seconds=.15))
        self.assertEqual(result.error,'inputplumber.timeout')

    def test_closed_pipes_live_child_still_bounded(self):
        result=self.child("import os,time;os.close(1);os.close(2);time.sleep(20)",Runner(timeout_seconds=.15))
        self.assertEqual(result.error,'inputplumber.timeout')

    def test_deadline_is_instance_aggregate(self):
        runner=Runner(timeout_seconds=.01)
        time.sleep(.02)
        with patch.object(commands.subprocess,'Popen') as spawn:
            self.assertEqual(runner.run(ID).error,'inputplumber.budget_exhausted')
            spawn.assert_not_called()

    def test_failures_and_stderr_never_escape(self):
        result=self.child("import sys;print('private detail',file=sys.stderr);sys.exit(1)")
        self.assertEqual(result.error,'inputplumber.command_failed')
        self.assertEqual(result.stderr,'')
        runner=Runner()
        with patch.object(commands.subprocess,'Popen',side_effect=OSError('private path')):
            self.assertEqual(runner.run(ID).error,'inputplumber.command_unavailable')
        with patch.object(commands.subprocess,'Popen') as spawn:
            self.assertEqual(runner.run(ID).error,'inputplumber.budget_exhausted')
            spawn.assert_not_called()

    def test_invalid_utf8_is_not_silently_replaced(self):
        self.assertEqual(self.child("import os;os.write(1,b'\\xff')").error,'inputplumber.output_invalid')

    def test_cancelled_awaiter_does_not_escape_child_deadline(self):
        import asyncio
        async def exercise():
            task=asyncio.create_task(asyncio.to_thread(self.child,"import time;time.sleep(20)",Runner(timeout_seconds=.15)))
            await asyncio.sleep(.02)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        started=time.monotonic()
        asyncio.run(exercise())
        self.assertLess(time.monotonic()-started,1)

    def test_uncertain_cleanup_poison_prevents_later_spawn(self):
        runner=Runner()
        with patch.object(Runner,'_reap',return_value=False):
            result=self.child("print('ok')",runner)
        self.assertEqual(result.error,'inputplumber.cleanup_unconfirmed')
        self.assertEqual(result.stdout,'')
        with patch.object(commands.subprocess,'Popen') as spawn:
            self.assertEqual(runner.run(ID).error,'inputplumber.budget_exhausted')
            spawn.assert_not_called()

    def test_read_os_fault_reaps_before_categorical_denial(self):
        real_read=os.read
        def fail_read(fd, size):
            # Popen itself reads its exec-error pipe before catalog selection.
            if size == 50000: return real_read(fd,size)
            raise OSError('private read failure')
        with patch.object(commands.os,'read',side_effect=fail_read):
            result=self.child("print('ok')")
        self.assertEqual(result.error,'inputplumber.command_unavailable')
