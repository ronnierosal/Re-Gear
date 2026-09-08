from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.removal_transaction import (  # noqa: E402
    REMOVAL_TRANSACTION_SCHEMA_VERSION,
    FunctionProgress,
    Recovery,
    RecoveryState,
    RemovalFunctionRecord,
    RemovalTransaction,
    RemovalTransactionState,
    plan,
    reconcile,
    record_progress,
    record_restored,
)


OWNER = "hdm-egpu-remove:1000"
DEVICE_SET = "egpu:0000:08:00.0+0000:08:00.1"
AUDIO = "0000:08:00.1"
GPU = "0000:08:00.0"
BOTH = (AUDIO, GPU)


def planned(addresses: tuple[str, ...] = BOTH) -> RemovalTransaction:
    return plan(
        owner_id=OWNER, device_set=DEVICE_SET, addresses=addresses, now_ns=1_000
    )


class RecordInvariantTests(unittest.TestCase):
    def test_a_plan_records_the_intended_set_as_pending(self) -> None:
        record = planned()
        self.assertIs(record.state, RemovalTransactionState.PLANNED)
        self.assertEqual(record.addresses, BOTH)
        self.assertEqual(record.intended_removed, ())

    def test_an_invalid_address_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            planned(("not-a-pci-address",))

    def test_a_repeated_function_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            planned((AUDIO, AUDIO))

    def test_an_empty_transaction_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            planned(())

    def test_an_unknown_schema_version_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            RemovalTransaction(
                REMOVAL_TRANSACTION_SCHEMA_VERSION + 1,
                OWNER,
                DEVICE_SET,
                RemovalTransactionState.PLANNED,
                (RemovalFunctionRecord(AUDIO, FunctionProgress.PENDING),),
                0,
            )

    def test_progress_for_a_function_outside_the_transaction_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            record_progress(planned((AUDIO,)), GPU, FunctionProgress.REMOVED)


class ProgressTests(unittest.TestCase):
    def test_one_function_removed_leaves_the_transaction_in_progress(self) -> None:
        record = record_progress(planned(), AUDIO, FunctionProgress.REMOVED)
        self.assertIs(record.state, RemovalTransactionState.IN_PROGRESS)
        self.assertEqual(record.intended_removed, (AUDIO,))

    def test_every_function_removed_completes_the_transaction(self) -> None:
        record = record_progress(planned(), AUDIO, FunctionProgress.REMOVED)
        record = record_progress(record, GPU, FunctionProgress.REMOVED)
        self.assertIs(record.state, RemovalTransactionState.COMPLETE)

    def test_a_failed_function_does_not_complete_the_transaction(self) -> None:
        record = record_progress(planned(), AUDIO, FunctionProgress.REMOVED)
        record = record_progress(record, GPU, FunctionProgress.FAILED)
        self.assertIs(record.state, RemovalTransactionState.IN_PROGRESS)


class ReconciliationTests(unittest.TestCase):
    """The device is the authority; the record only says what was intended."""

    def test_a_whole_device_reads_as_not_started(self) -> None:
        result = reconcile(planned(), present_addresses=BOTH)
        self.assertIs(result.state, RecoveryState.NOT_STARTED)
        self.assertTrue(result.safe_to_continue)
        self.assertFalse(result.device_disturbed)

    def test_both_functions_absent_reads_as_complete(self) -> None:
        record = record_progress(planned(), AUDIO, FunctionProgress.REMOVED)
        record = record_progress(record, GPU, FunctionProgress.REMOVED)
        result = reconcile(record, present_addresses=())
        self.assertIs(result.state, RecoveryState.COMPLETE)
        self.assertFalse(result.safe_to_continue)

    def test_a_half_detached_device_needs_recovery(self) -> None:
        """The crash case: audio gone, GPU still bound, process dead."""
        record = record_progress(planned(), AUDIO, FunctionProgress.REMOVED)
        result = reconcile(record, present_addresses=(GPU,))
        self.assertIs(result.state, RecoveryState.NEEDS_RECOVERY)
        self.assertTrue(result.device_disturbed)
        self.assertFalse(result.safe_to_continue)

    def test_recovery_restores_everything_intended_not_only_what_was_removed(
        self,
    ) -> None:
        # The record's belief about what it removed was written before an
        # interruption of unknown length; the safe restore covers the whole
        # intended set rather than trusting that belief.
        record = record_progress(planned(), AUDIO, FunctionProgress.REMOVED)
        result = reconcile(record, present_addresses=(GPU,))
        self.assertEqual(result.restore, BOTH)

    def test_a_partial_removal_is_never_safe_to_continue(self) -> None:
        """Continuing would act on readiness gathered before an unknown gap."""
        record = record_progress(planned(), AUDIO, FunctionProgress.REMOVED)
        for present in ((GPU,), (AUDIO,)):
            result = reconcile(record, present_addresses=present)
            self.assertFalse(result.safe_to_continue)

    def test_a_plan_whose_device_vanished_entirely_reads_as_complete(self) -> None:
        # Recorded as planned, nothing written yet, but neither function is
        # present. The device is the authority, so this is not "not started".
        result = reconcile(planned(), present_addresses=())
        self.assertIs(result.state, RecoveryState.COMPLETE)
        self.assertFalse(result.safe_to_continue)

    def test_a_record_believing_it_removed_a_present_function_is_not_complete(
        self,
    ) -> None:
        # The record claims both removed; the bus still shows the GPU. The
        # device wins, and this is a recovery case rather than a completion.
        record = record_progress(planned(), AUDIO, FunctionProgress.REMOVED)
        record = record_progress(record, GPU, FunctionProgress.REMOVED)
        self.assertIs(record.state, RemovalTransactionState.COMPLETE)
        result = reconcile(record, present_addresses=(GPU,))
        self.assertIs(result.state, RecoveryState.NEEDS_RECOVERY)

    def test_a_restored_record_reads_as_restored(self) -> None:
        record = record_restored(
            record_progress(planned(), AUDIO, FunctionProgress.REMOVED)
        )
        result = reconcile(record, present_addresses=BOTH)
        self.assertIs(result.state, RecoveryState.RESTORED)
        self.assertFalse(result.safe_to_continue)

    def test_address_comparison_ignores_case(self) -> None:
        record = record_progress(planned(), AUDIO, FunctionProgress.REMOVED)
        result = reconcile(record, present_addresses=(GPU.upper(),))
        self.assertIs(result.state, RecoveryState.NEEDS_RECOVERY)

    def test_no_record_is_inconsistent_rather_than_not_started(self) -> None:
        result = reconcile(None, present_addresses=BOTH)
        self.assertIs(result.state, RecoveryState.INCONSISTENT)
        self.assertFalse(result.safe_to_continue)

    def test_a_non_tuple_observation_is_refused(self) -> None:
        result = reconcile(planned(), present_addresses=[AUDIO])
        self.assertIs(result.state, RecoveryState.INCONSISTENT)

    def test_non_string_addresses_are_refused(self) -> None:
        result = reconcile(planned(), present_addresses=(1,))
        self.assertIs(result.state, RecoveryState.INCONSISTENT)


class SafetyPropertyTests(unittest.TestCase):
    def test_only_not_started_is_safe_to_continue(self) -> None:
        for state in RecoveryState:
            result = Recovery(state, "code")
            if state is RecoveryState.NOT_STARTED:
                self.assertTrue(result.safe_to_continue)
            else:
                self.assertFalse(
                    result.safe_to_continue, f"{state} must not permit continuing"
                )

    def test_only_needs_recovery_reports_a_disturbed_device(self) -> None:
        for state in RecoveryState:
            result = Recovery(state, "code")
            self.assertEqual(
                result.device_disturbed, state is RecoveryState.NEEDS_RECOVERY
            )


if __name__ == "__main__":
    unittest.main()
