from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
import os
import signal
import sys
import time
import unittest
from unittest.mock import Mock, patch

from scripts import probe_killed_filter_controller as fixture
from hdm.delivery.device_filter_journal import JournalRecord
from hdm.delivery.device_filter_lifecycle import LaunchBinding, FilterLifecycle, OwnedFilter, Phase


class KilledControllerTests(unittest.TestCase):
    def setUp(self):
        self.binding = LaunchBinding('a'*64, 'fixture', 'gamescope-session.service',
            'b'*32, 1000, 123, 99, 1, 2, 'c'*64, 30)
        self.owner = OwnedFilter(3, 'd'*64, True, True, 4, 5)
        self.record = JournalRecord(3, FilterLifecycle(self.binding, Phase.ATTACHED, self.owner))
        self.events = []
        self.ids = (3,)
        test = self
        class Journal:
            @contextmanager
            def transaction(self):
                test.events.append('lock')
                yield SimpleNamespace(read=lambda *args:test.record)
                test.events.append('unlock')
        self.journal = Journal()

    def recover(self):
        self.events.append('recover')
        self.record = JournalRecord(4, FilterLifecycle(self.binding, Phase.CANCELLED, self.owner))
        self.ids = ()
        return SimpleNamespace(outcome='owned_pin_removed', launch_authorized=False, disconnect_clearance=False)

    def run_case(self, **updates):
        options = dict(ready=lambda:b'attached', probe=lambda result:self.events.append(tuple(result)),
            kill_controller=lambda:self.events.append('SIGKILL'), query=lambda:self.ids, recover=self.recover)
        options.update(updates)
        return fixture.verify_killed_owner(self.binding, self.journal, **options)

    def test_kill_survival_recovery_order_and_no_clearance(self):
        result = self.run_case()
        self.assertFalse(result['disconnect_clearance'])
        self.assertTrue(result['synthetic_binding'])
        self.assertTrue(result['journal_retained'])
        self.assertFalse(result['live_bpf_fd_crash_verified'])
        self.assertEqual(self.events, ['lock','unlock',(False,True),'SIGKILL','lock','unlock',
            (False,True),'recover','lock','unlock',(True,True)])

    def test_lost_readiness_never_kills_or_recovers_as_success(self):
        for ready in (b'', b'partial', b'pending'):
            with self.assertRaises(ValueError): self.run_case(ready=lambda:ready)
        self.assertEqual(self.events, [])

    def test_pending_and_changed_binding_rejected(self):
        for state in (FilterLifecycle(self.binding),
                      FilterLifecycle(replace(self.binding, operation='foreign'), Phase.ATTACHED, self.owner)):
            self.record = JournalRecord(1, state)
            with self.assertRaises(ValueError): self.run_case()
        self.assertNotIn('SIGKILL', self.events)

    def test_foreign_or_missing_program_set_rejected(self):
        for self.ids in ((), (3,4), (9,)):
            with self.assertRaises(ValueError): self.run_case()
        self.assertNotIn('SIGKILL', self.events)

    def test_survival_must_be_checked_after_kill(self):
        def kill(): self.ids = ()
        with self.assertRaises(ValueError): self.run_case(kill_controller=kill)
        self.assertNotIn('recover', self.events)

    def test_recovery_refusals_never_pass(self):
        for outcome in ('pin_missing_unverified','different_boot_unresolved','session_recovery_required'):
            with self.assertRaises(ValueError):
                self.run_case(recover=lambda:SimpleNamespace(outcome=outcome,launch_authorized=False,disconnect_clearance=False))

    def test_restore_probe_failure_never_passes(self):
        def probe(result):
            if result == [True,True]: raise ValueError('not restored')
        with self.assertRaises(ValueError): self.run_case(probe=probe)

    def test_exact_sigkill_status_required(self):
        kill = Mock()
        with patch.object(fixture.signal, 'SIGKILL', 9, create=True), \
             patch.object(fixture.os, 'WIFSIGNALED', lambda value:bool(value & 127), create=True), \
             patch.object(fixture.os, 'WTERMSIG', lambda value:value & 127, create=True):
            fixture._kill(123, kill=kill, wait=lambda pid:9)
            kill.assert_called_once_with(123, 9)
            for status in (0, 15, 2 << 8):
                with self.assertRaises(ValueError): fixture._kill(123, kill=Mock(), wait=lambda pid:status)

    def test_wait_is_bounded(self):
        with patch.object(fixture.os, 'WNOHANG', 1, create=True), self.assertRaises(TimeoutError):
            fixture._wait(123, waitpid=lambda *args:(0,0), clock=Mock(side_effect=[0,4]), sleep=Mock())

    def test_cleanup_accepts_already_exited_child_without_signal(self):
        kill = Mock()
        with patch.object(fixture.os, 'WNOHANG', 1, create=True):
            self.assertEqual(fixture.terminate_owned(123, waitpid=lambda *args:(123,512), kill=kill),512)
        kill.assert_not_called()

    def test_cleanup_accepts_natural_exit_race_and_pending_kill(self):
        with patch.object(fixture.os, 'WNOHANG', 1, create=True), patch.object(fixture.signal, 'SIGKILL', 9, create=True):
            for status in (0,512,9):
                kill, wait = Mock(), Mock(return_value=status)
                self.assertEqual(fixture.terminate_owned(123,waitpid=lambda *args:(0,0),kill=kill,wait=wait),status)
                kill.assert_called_once_with(123,9)
                wait.assert_called_once_with(123)

    def test_cleanup_esrch_still_requires_bounded_reap(self):
        with patch.object(fixture.os, 'WNOHANG', 1, create=True), patch.object(fixture.signal, 'SIGKILL', 9, create=True):
            kill = Mock(side_effect=ProcessLookupError())
            self.assertEqual(fixture.terminate_owned(123,waitpid=lambda *args:(0,0),kill=kill,wait=lambda pid:512),512)
            with self.assertRaises(TimeoutError):
                fixture.terminate_owned(123,waitpid=lambda *args:(0,0),kill=kill,wait=Mock(side_effect=TimeoutError()))

    @unittest.skipUnless(sys.platform == 'linux', 'Linux unprivileged fork fixture')
    def test_real_owned_child_cleanup_natural_exit_and_kill(self):
        for natural in (True,False):
            child = os.fork()
            if child == 0:
                if not natural: time.sleep(10)
                os._exit(2)
            try:
                status = fixture.terminate_owned(child)
                child = None
                self.assertTrue(os.WIFEXITED(status) or os.WIFSIGNALED(status))
            finally:
                if child is not None: fixture.terminate_owned(child)

    def test_root_and_explicit_invocation_guards(self):
        with patch.object(fixture.platform, 'system', return_value='Windows'), patch.object(fixture.os, 'open') as opened:
            with self.assertRaises(ValueError): fixture.run_fixture()
            opened.assert_not_called()
        with patch.object(fixture.sys, 'argv', ['probe']), patch.object(fixture, 'run_fixture') as run:
            with self.assertRaises(SystemExit): fixture.main()
            run.assert_not_called()

    def test_failure_report_sanitized_and_not_success(self):
        with patch.object(fixture.sys, 'argv', ['probe','--disposable-killed-controller']), \
             patch.object(fixture.platform, 'system', return_value='Windows'), \
             patch.object(fixture, 'run_fixture', side_effect=RuntimeError('PRIVATE')), patch('builtins.print') as output:
            self.assertEqual(fixture.main(), 1)
            self.assertNotIn('PRIVATE', output.call_args.args[0])
            self.assertIn('fixture_failed', output.call_args.args[0])


class PendingControllerTests(unittest.TestCase):
    setUp = KilledControllerTests.setUp
    recover = KilledControllerTests.recover
    def pending(self, **updates):
        self.owner = replace(self.owner, survives_owner_exit=False)
        self.record = JournalRecord(2, FilterLifecycle(self.binding, Phase.PIN_PENDING, self.owner))
        options = dict(ready=lambda:b'pin-pending', probe=lambda result:self.events.append(tuple(result)),
            kill_controller=lambda:self.events.append('SIGKILL'), query=lambda:self.ids, recover=self.recover)
        options.update(updates)
        return fixture.verify_pending_owner(self.binding,self.journal,**options)

    def test_pending_no_journal_read_until_kill_reaped(self):
        result = self.pending()
        self.assertTrue(result['live_bpf_fd_crash_verified'])
        self.assertTrue(result['pin_pending_recovery_verified'])
        self.assertEqual(self.events[:4], [(False,True),'SIGKILL','lock','unlock'])
        self.assertEqual(self.events[-1],(True,True))

    def test_pending_missing_query_prevents_kill_and_read(self):
        for ids in ((), (3,4), (True,), (0,)):
            self.events=[]
            with self.assertRaises(ValueError): self.pending(query=lambda:ids)
            self.assertEqual(self.events,[])

    def test_pending_attached_or_wrong_owner_after_kill_rejected(self):
        for wrong_phase in (True,False):
            self.events=[]
            def kill():
                self.events.append('SIGKILL')
                owner=replace(self.owner, survives_owner_exit=True) if wrong_phase else replace(self.owner,program_id=9)
                self.record=JournalRecord(3,FilterLifecycle(self.binding,
                    Phase.ATTACHED if wrong_phase else Phase.PIN_PENDING,owner))
            with self.assertRaises(ValueError): self.pending(kill_controller=kill)
            self.assertNotIn('recover',self.events)

    def test_pending_cleanup_refusal_cannot_pass(self):
        with self.assertRaises(ValueError):
            self.pending(recover=lambda:SimpleNamespace(outcome='pin_missing_unverified',launch_authorized=False,disconnect_clearance=False))

    def test_pending_cli_is_explicit(self):
        with patch.object(fixture.sys,'argv',['probe','--disposable-pin-pending-crash']), \
             patch.object(fixture.platform,'system',return_value='Windows'), \
             patch.object(fixture,'run_fixture',return_value={'state':'fixture_passed'}) as run, patch('builtins.print'):
            self.assertEqual(fixture.main(),0)
            run.assert_called_once_with(pin_pending=True)

    def test_pending_hook_signals_only_after_pin_and_live_identity_checks(self):
        expected=SimpleNamespace(program_id=3)
        sock=Mock()
        sock.recv.side_effect=TimeoutError()
        cls=fixture.pending_kernel_factory(sock)
        kernel=object.__new__(cls)
        kernel.program_fd=11
        kernel.link_fd=12
        with patch.object(fixture.CgroupDeviceLink,'pin') as pin, \
             patch.object(fixture.CgroupDeviceLink,'program_id',return_value=3), \
             patch.object(fixture.CgroupDeviceLink,'link_identity',return_value=expected), \
             patch.object(fixture,'_send') as send:
            with self.assertRaises(TimeoutError): kernel.pin(9,'token',expected)
            pin.assert_called_once_with(9,'token',expected)
            send.assert_called_once_with(sock,b'pin-pending')
            self.assertEqual((kernel.program_fd,kernel.link_fd),(11,12))
            send.reset_mock()
            kernel.program_fd=None
            with self.assertRaises(ValueError): kernel.pin(9,'token',expected)
            send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
