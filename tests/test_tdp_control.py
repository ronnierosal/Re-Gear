import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.application.tdp_control import TdpControlService
from hdm.ports.tdp import TdpObservation, TdpReading, TdpRegister, TdpSessionRecord, TdpWriteOutcome


def reading(spl=15, slow=15, fast=15, binding="opaque-binding"):
    return TdpReading(binding, TdpRegister(spl, 7, 30), TdpRegister(slow, 15, 43), TdpRegister(fast, 15, 53))


class MemoryJournal:
    def __init__(self):
        self.record = None
        self.fail_save = False
        self.saved = []

    def load(self):
        return self.record

    def save(self, record):
        if self.fail_save:
            raise OSError("private error")
        self.record = record
        self.saved.append(record)


class Provider:
    def __init__(self, journal):
        self.current = reading()
        self.code = "tdp.ready"
        self.writes = []
        self.journal = journal
        self.behavior = "success"
        self.observations = []

    def observe(self):
        if self.observations:
            self.current = self.observations.pop(0)
        return TdpObservation(self.code, self.current)

    def set_limit(self, expected, watts):
        assert self.journal.record.phase == "pending", "must journal before writing"
        if self.behavior == "refused":
            return TdpWriteOutcome(False, False, "tdp.revalidation_failed")
        self.writes.append(watts)
        if self.behavior == "timeout":
            return TdpWriteOutcome(True, False, "tdp.command_timeout")
        if self.behavior == "success":
            self.current = reading(*expected.target_values(watts))
        elif self.behavior == "partial":
            self.current = replace(expected, sustained=replace(expected.sustained, current=watts))
        elif self.behavior == "lost_save":
            self.current = reading(*expected.target_values(watts))
            self.journal.fail_save = True
        return TdpWriteOutcome(True, True, "tdp.request_accepted")


class TdpControlTests(unittest.TestCase):
    def setUp(self):
        self.journal = MemoryJournal()
        self.provider = Provider(self.journal)
        self.waits = []
        self.service = TdpControlService(self.provider, self.journal, wait=self.waits.append, verification_attempts=3)

    def test_apply_and_restore_verify_all_registers(self):
        self.assertEqual(self.service.apply(20).state, "applied")
        self.assertEqual(self.provider.current.values, (20, 20, 20))
        self.assertEqual(self.service.restore().state, "restored")
        self.assertEqual(self.provider.current.values, (15, 15, 15))
        self.assertIsNone(self.journal.record)

    def test_repeated_adjustments_preserve_original_baseline(self):
        self.service.apply(20)
        self.service.apply(18)
        self.assertEqual(self.journal.record.baseline.values, (15, 15, 15))
        self.assertEqual(self.service.restore().state, "restored")
        self.assertEqual(self.provider.writes, [20, 18, 15])

    def test_lower_sustained_limit_respects_distinct_boost_minimums(self):
        self.assertEqual(self.service.apply(10).state, "applied")
        self.assertEqual(self.provider.current.values, (10, 15, 15))

    def test_invalid_request_or_unavailable_ownership_never_writes(self):
        for watts in (True, None, 7.5, -1, 0, 2**32, "20", 31):
            self.assertEqual(self.service.apply(watts).state, "blocked")
        self.provider.code = "tdp.ownership_unverified"
        self.assertEqual(self.service.apply(20).state, "blocked")
        self.assertEqual(self.provider.writes, [])

    def test_noop_does_not_create_journal_or_write(self):
        self.assertEqual(self.service.apply(15).state, "unchanged")
        self.assertIsNone(self.journal.record)
        self.assertEqual(self.provider.writes, [])

    def test_original_boost_settings_must_be_exactly_restorable(self):
        self.provider.current = reading(15, 25, 30)
        self.assertEqual(self.service.apply(20).code, "tdp.baseline_not_restorable")
        self.assertEqual(self.provider.writes, [])

    def test_pending_write_survives_service_recreation_and_blocks_retry(self):
        self.provider.behavior = "timeout"
        self.assertEqual(self.service.apply(20).state, "recovery_required")
        restarted = TdpControlService(self.provider, self.journal, wait=lambda _: None)
        self.assertEqual(restarted.apply(21).code, "tdp.previous_write_uncertain")
        self.assertEqual(restarted.restore().code, "tdp.previous_write_uncertain")
        self.assertEqual(self.provider.writes, [20])

    def test_partial_write_is_not_success_or_blind_rollback(self):
        self.provider.behavior = "partial"
        self.assertEqual(self.service.apply(20).code, "tdp.readback_unverified")
        self.assertEqual(self.journal.record.phase, "pending")
        self.assertEqual(self.waits, [0.1, 0.1])
        self.assertEqual(self.provider.writes, [20])

    def test_external_change_or_restart_prevents_restoration(self):
        for new in (reading(18, 18, 18), reading(20, 20, 20, "new-owner")):
            with self.subTest(new=new):
                self.setUp()
                self.service.apply(20)
                self.provider.current = new
                self.assertEqual(self.service.restore().code, "tdp.external_change")
                self.assertEqual(self.provider.writes, [20])

    def test_journal_failure_before_or_after_write_is_honest(self):
        self.journal.fail_save = True
        self.assertEqual(self.service.apply(20).code, "tdp.journal_unavailable")
        self.assertEqual(self.provider.writes, [])
        self.journal.fail_save = False
        self.provider.behavior = "lost_save"
        self.assertEqual(self.service.apply(20).state, "recovery_required")
        self.assertEqual(self.provider.writes, [20])

    def test_failed_revalidation_does_not_leave_spurious_pending_state(self):
        self.provider.behavior = "refused"
        self.assertEqual(self.service.apply(20).state, "blocked")
        self.assertIsNone(self.journal.record)
        self.assertEqual(self.provider.writes, [])

    def test_overlapping_request_is_rejected(self):
        self.service._lock.acquire()
        try:
            self.assertEqual(self.service.apply(20).code, "tdp.busy")
        finally:
            self.service._lock.release()

    def test_invalid_register_and_cross_register_target_are_rejected(self):
        for values in ((True, 1, 30), (15, 20, 30), (15, 1, 0), (15, 1, 2**32)):
            with self.assertRaises(ValueError):
                TdpRegister(*values)
        self.provider.current = replace(reading(), fast=TdpRegister(15, 15, 18))
        self.assertEqual(self.service.apply(20).code, "tdp.request_out_of_range")
        self.assertEqual(self.provider.writes, [])

    def test_verification_wait_failure_preserves_uncertain_record(self):
        self.provider.behavior = "partial"
        def failing_wait(_):
            raise OSError("private error")
        service = TdpControlService(self.provider, self.journal, wait=failing_wait)
        self.assertEqual(service.apply(20).code, "tdp.readback_unverified")
        self.assertEqual(self.journal.record.phase, "pending")
        self.assertEqual(service.restore().code, "tdp.previous_write_uncertain")
        self.assertEqual(self.provider.writes, [20])

    def test_foreign_baseline_cannot_enter_recovery_record(self):
        with self.assertRaises(ValueError):
            TdpSessionRecord(reading(10, 15, 15, "old-boot"), reading())


if __name__ == "__main__":
    unittest.main()
