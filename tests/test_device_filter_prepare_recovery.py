from dataclasses import replace
import unittest
from unittest.mock import Mock, MagicMock
from backend.hdm.delivery.device_filter_journal import JournalRecord
from backend.hdm.delivery.device_filter_lifecycle import LaunchBinding, FilterLifecycle, Phase
from backend.hdm.delivery.device_filter_prepare_recovery import recover_prepared_operation
from backend.hdm.delivery.device_filter_recovery import RecoveryResult
from backend.hdm.delivery.device_filter_arm_recovery import ArmRecoveryResult
from tests.test_device_filter_arm import arm


class PreparedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.arm=arm();self.events=[]
        self.binding=LaunchBinding(self.arm.boot_hash,self.arm.operation,self.arm.unit,
            'e'*32,self.arm.uid,50,60,70,80,self.arm.topology_hash,99)
        self.record=JournalRecord(1,FilterLifecycle(self.binding,Phase.CANCELLED))
        self.journal=MagicMock()
        self.journal.transaction.return_value.__enter__.return_value.read.side_effect=lambda *a:self.record
        self.arms=Mock();self.arms.read.return_value=self.arm
        self.boot=Mock(return_value=self.arm.boot_hash)
        self.stopped=Mock(return_value=True)
        self.recovery=Mock()
        def recover(*args,**kwargs):
            self.events.append('recover')
            return RecoveryResult('owned_pin_removed',3)
        self.recovery.recover.side_effect=recover
        def clear(*args,**kwargs):
            self.events.append('clear');self.arms.read.return_value=None
            return ArmRecoveryResult('arm_removed')
        self.clear=Mock(side_effect=clear)

    def run_recovery(self):
        return recover_prepared_operation(self.journal,self.arms,self.arm,
            observe_boot=self.boot,publisher_stopped=self.stopped,
            recovery_factory=lambda journal:self.recovery,clear_arm=self.clear)

    def test_filter_recovery_precedes_arm_cleanup(self):
        result=self.run_recovery()
        self.assertEqual(self.events,['recover','clear'])
        self.assertTrue(result.configuration_restore_required)
        self.assertFalse(result.launch_authorized)
        self.assertFalse(result.disconnect_clearance)

    def test_running_publisher_or_changed_boot_prevents_recovery(self):
        for stopped,boot in ((False,self.arm.boot_hash),(True,'f'*64)):
            self.stopped.return_value=stopped;self.boot.return_value=boot
            with self.assertRaises(ValueError):self.run_recovery()
        self.recovery.recover.assert_not_called()

    def test_unresolved_or_postgrant_result_never_clears_arm(self):
        self.recovery.recover.side_effect=None
        for outcome in ('session_recovery_required','pin_missing_unverified','different_boot_unresolved'):
            self.recovery.recover.return_value=RecoveryResult(outcome,3)
            with self.assertRaises(ValueError):self.run_recovery()
        self.clear.assert_not_called()

    def test_missing_journal_never_clears_arm(self):
        self.recovery.recover.side_effect=FileNotFoundError()
        with self.assertRaises(FileNotFoundError):self.run_recovery()
        self.clear.assert_not_called()

    def test_publisher_restarts_during_recovery_blocks_clear(self):
        self.stopped.side_effect=[True,False]
        with self.assertRaises(ValueError):self.run_recovery()
        self.clear.assert_not_called()

    def test_replacement_arm_is_not_touched(self):
        self.arms.read.return_value=replace(self.arm,operation='foreign')
        with self.assertRaises(ValueError):self.run_recovery()
        self.recovery.recover.assert_not_called()
        self.clear.assert_not_called()

    def test_journal_mismatch_blocks_kernel_recovery(self):
        for change in (dict(uid=1001),dict(topology_hash='f'*64),
                       dict(invocation=self.arm.previous_invocation)):
            self.record=JournalRecord(1,FilterLifecycle(replace(self.binding,**change),Phase.CANCELLED))
            with self.assertRaises(ValueError):self.run_recovery()
        self.recovery.recover.assert_not_called()
        self.clear.assert_not_called()


class SessionRestoreTests(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        from backend.hdm.ports.presentation_activation import GamescopeUserContext
        from backend.hdm.delivery.device_filter_prepare_recovery import PreparedRecoveryResult
        self.arm=arm();self.events=[]
        self.user=GamescopeUserContext('deck',self.arm.uid,1000,Path('/home/deck'),Path('/run/user/1000'),Path('/run/user/1000/bus'))
        self.arms=Mock();self.arms.read.return_value=None
        self.recover=Mock(side_effect=lambda *a,**k:self.events.append('recover') or PreparedRecoveryResult('owned_pin_removed','arm_removed'))
        self.dropins=Mock();self.dropins.restore.side_effect=lambda *a,**k:self.events.append('restore')
        self.legacy=Mock();self.legacy.restore.side_effect=lambda *a,**k:self.events.append('legacy_restore')
        self.commands=Mock()
        self.commands.run.side_effect=lambda operation,**k:self.events.append(operation.value) or Mock(ok=True)
        self.idle=Mock(return_value=True)

    def restore(self):
        from backend.hdm.delivery.device_filter_prepare_recovery import restore_prepared_session
        return restore_prepared_session(Mock(),self.arms,self.arm,user=self.user,
            dropins=self.dropins,commands=self.commands,expected_candidate=b'candidate',legacy=self.legacy,expected_legacy_original=b'legacy',observe_boot=lambda:self.arm.boot_hash,
            publisher_stopped=lambda:True,observe_idle=self.idle,recover=self.recover)

    def test_recovery_restore_reload_then_restart(self):
        self.assertEqual(self.restore(),'normal_session_restart_requested_unverified')
        self.assertEqual(self.events,['recover','restore','legacy_restore','daemon_reload','restart_gamescope_session'])

    def test_failed_restore_does_not_reload_or_restart(self):
        self.dropins.restore.side_effect=ValueError('foreign file')
        with self.assertRaises(ValueError):self.restore()
        self.commands.run.assert_not_called()

    def test_failed_filter_recovery_does_not_restore_configuration(self):
        self.recover.side_effect=ValueError('unresolved filter')
        with self.assertRaises(ValueError):self.restore()
        self.dropins.restore.assert_not_called()
        self.commands.run.assert_not_called()

    def test_unknown_or_running_game_blocks_restart(self):
        for idle in (None,False):
            self.events.clear();self.idle.return_value=idle
            with self.assertRaises(ValueError):self.restore()
            self.assertEqual(self.events,['recover','restore','legacy_restore','daemon_reload'])

    def test_failed_reload_blocks_restart(self):
        self.commands.run.return_value=Mock(ok=False);self.commands.run.side_effect=None
        with self.assertRaises(ValueError):self.restore()
        self.commands.run.assert_called_once()

    def test_failed_legacy_restore_blocks_reload_and_restart(self):
        self.legacy.restore.side_effect=ValueError('legacy replacement')
        with self.assertRaises(ValueError):self.restore()
        self.commands.run.assert_not_called()

    def test_legacy_restore_bound_to_recovered_trial(self):
        self.restore()
        self.legacy.restore.assert_called_once_with(self.user,self.arm.unit,
            self.arm.operation,expected_original=b'legacy')
