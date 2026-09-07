from dataclasses import replace
import unittest
from unittest.mock import Mock
from backend.hdm.delivery.device_filter_trial_owner import configure_prepared_trial
from tests.test_device_filter_trial_owner_store import record


class OwnerSetupTests(unittest.TestCase):
    def setUp(self):
        self.record=record();self.events=[];self.persisted=None
        self.store=Mock()
        def create(value):
            if self.persisted is not None:raise FileExistsError()
            self.persisted=value;self.events.append('created')
        def transition(op,unit,old,new,*,expected_record):
            self.assertEqual(self.persisted,expected_record)
            self.assertEqual(self.persisted.phase,old)
            self.persisted=replace(self.persisted,phase=new)
            self.events.append(new);return self.persisted
        self.store.create.side_effect=create;self.store.transition.side_effect=transition
        self.legacy=Mock();self.dropins=Mock();self.arms=Mock()
        self.legacy.suspend.side_effect=lambda *a,**k:self.events.append('suspend')
        self.dropins.apply.side_effect=lambda *a:self.events.append('apply')
        self.arms.arm.side_effect=lambda *a:self.events.append('arm')
        self.commands=Mock();self.commands.run.side_effect=lambda *a,**k:self.events.append('reload') or Mock(ok=True)

    def configure(self):
        return configure_prepared_trial(self.store,self.record,legacy=self.legacy,
            dropins=self.dropins,arms=self.arms,commands=self.commands)

    def test_durable_intent_precedes_each_mutation(self):
        result=self.configure()
        self.assertEqual(result.phase,'scheduling')
        self.assertEqual(self.events,['created','legacy_suspending','suspend',
            'dropin_applying','apply','arming','arm','reload','scheduling'])
        self.assertFalse(result.hardware_verified)

    def test_existing_operation_never_replays_setup(self):
        self.persisted=self.record
        with self.assertRaises(FileExistsError):self.configure()
        self.legacy.suspend.assert_not_called()
        self.dropins.apply.assert_not_called()
        self.arms.arm.assert_not_called()

    def test_suspend_failure_preserves_recovery_intent(self):
        self.legacy.suspend.side_effect=OSError('suspend failed')
        with self.assertRaises(OSError):self.configure()
        self.assertEqual(self.persisted.phase,'legacy_suspending')
        self.dropins.apply.assert_not_called();self.arms.arm.assert_not_called()

    def test_apply_failure_never_arms(self):
        self.dropins.apply.side_effect=OSError('apply failed')
        with self.assertRaises(OSError):self.configure()
        self.assertEqual(self.persisted.phase,'dropin_applying')
        self.arms.arm.assert_not_called()

    def test_arm_failure_never_records_scheduling(self):
        self.arms.arm.side_effect=OSError('publication uncertain')
        with self.assertRaises(OSError):self.configure()
        self.assertEqual(self.persisted.phase,'arming')

    def test_persisted_scheduling_is_not_new_setup_authority(self):
        self.record=replace(self.record,phase='scheduling')
        with self.assertRaises(ValueError):self.configure()
        self.store.create.assert_not_called()

    def test_reload_failure_does_not_allow_scheduling(self):
        self.commands.run.side_effect=None;self.commands.run.return_value=Mock(ok=False)
        with self.assertRaises(ValueError):self.configure()
        self.assertEqual(self.persisted.phase,'arming')
