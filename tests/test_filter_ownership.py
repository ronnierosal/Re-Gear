from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.filter_ownership import (  # noqa: E402
    OWNERSHIP_SCHEMA_VERSION,
    FilterOwnership,
    FilterOwnershipState,
    Reconciliation,
    ReconciliationState,
    arm,
    claim,
    reconcile,
    release,
)


OWNER = "hdm-egpu-release:1000"
CGROUP = "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service"
DEVICE_SET = "egpu:0000:08:00.0+0000:08:00.1"
SECOND = 1_000_000_000


def claimed(now_ns: int = 0, lease_ns: int = 60 * SECOND) -> FilterOwnership:
    return claim(
        owner_id=OWNER,
        cgroup_path=CGROUP,
        device_set=DEVICE_SET,
        now_ns=now_ns,
        lease_ns=lease_ns,
    )


def armed(program_id: int = 496, **kwargs) -> FilterOwnership:
    return arm(claimed(**kwargs), program_id=program_id)


class RecordInvariantTests(unittest.TestCase):
    def test_a_claim_records_the_intention_before_anything_is_attached(self) -> None:
        record = claimed()
        self.assertIs(record.state, FilterOwnershipState.CLAIMED)
        self.assertEqual(record.program_id, 0)
        self.assertEqual(record.schema_version, OWNERSHIP_SCHEMA_VERSION)

    def test_a_lease_must_expire_after_it_begins(self) -> None:
        with self.assertRaises(ValueError):
            FilterOwnership(
                OWNERSHIP_SCHEMA_VERSION,
                OWNER,
                CGROUP,
                DEVICE_SET,
                FilterOwnershipState.CLAIMED,
                10,
                10,
            )

    def test_an_armed_record_without_a_program_id_is_refused(self) -> None:
        """It could never be reconciled: there is nothing to match against."""
        with self.assertRaises(ValueError):
            FilterOwnership(
                OWNERSHIP_SCHEMA_VERSION,
                OWNER,
                CGROUP,
                DEVICE_SET,
                FilterOwnershipState.ARMED,
                0,
                SECOND,
            )

    def test_an_unknown_schema_version_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            FilterOwnership(
                OWNERSHIP_SCHEMA_VERSION + 1,
                OWNER,
                CGROUP,
                DEVICE_SET,
                FilterOwnershipState.CLAIMED,
                0,
                SECOND,
            )

    def test_identifiers_must_be_safe_tokens(self) -> None:
        with self.assertRaises(ValueError):
            FilterOwnership(
                OWNERSHIP_SCHEMA_VERSION,
                "owner with spaces and \n newline",
                CGROUP,
                DEVICE_SET,
                FilterOwnershipState.CLAIMED,
                0,
                SECOND,
            )

    def test_only_a_claim_can_be_armed(self) -> None:
        with self.assertRaises(ValueError):
            arm(release(armed()), program_id=496)

    def test_arming_needs_the_reported_program_id(self) -> None:
        with self.assertRaises(ValueError):
            arm(claimed(), program_id=0)


class ReconciliationTests(unittest.TestCase):
    def test_an_armed_record_whose_program_is_attached_is_enforced(self) -> None:
        result = reconcile(armed(), attached_program_ids=(496,), now_ns=SECOND)
        self.assertIs(result.state, ReconciliationState.ENFORCED)
        self.assertTrue(result.gated)
        self.assertFalse(result.lapsed)

    def test_an_armed_record_with_nothing_attached_is_orphaned(self) -> None:
        """The crash case, and the reason this module exists.

        The process died, the unpinned link went with it, and the record still
        says armed. The system is unfiltered while believing otherwise.
        """
        result = reconcile(armed(), attached_program_ids=(), now_ns=SECOND)
        self.assertIs(result.state, ReconciliationState.ORPHANED)
        self.assertFalse(result.gated)
        self.assertTrue(result.lapsed)
        self.assertEqual(result.code, "filter_ownership.armed_but_absent")

    def test_another_owners_filter_does_not_satisfy_this_record(self) -> None:
        # A program attached to the same cgroup by someone else is not this
        # record's guarantee, and treating it as one would report a device as
        # gated by a filter that permits a different device set.
        result = reconcile(armed(496), attached_program_ids=(501,), now_ns=SECOND)
        self.assertIs(result.state, ReconciliationState.ORPHANED)
        self.assertFalse(result.gated)

    def test_a_claim_within_its_lease_is_pending_not_gated(self) -> None:
        result = reconcile(claimed(), attached_program_ids=(), now_ns=SECOND)
        self.assertIs(result.state, ReconciliationState.PENDING)
        self.assertFalse(result.gated)
        # Pending never made the guarantee, so nothing lapsed.
        self.assertFalse(result.lapsed)

    def test_a_claim_past_its_lease_is_expired(self) -> None:
        result = reconcile(
            claimed(lease_ns=SECOND), attached_program_ids=(), now_ns=5 * SECOND
        )
        self.assertIs(result.state, ReconciliationState.EXPIRED)
        self.assertFalse(result.gated)

    def test_an_expired_armed_record_still_reports_enforced(self) -> None:
        """A still-attached filter is still enforcing, whatever the lease says.

        Reporting it as expired would tell a caller the device is reachable
        again while the filter is in fact still gating it, which is the
        dangerous direction. The caller renews or releases deliberately.
        """
        result = reconcile(
            armed(lease_ns=SECOND), attached_program_ids=(496,), now_ns=99 * SECOND
        )
        self.assertIs(result.state, ReconciliationState.ENFORCED)
        self.assertTrue(result.gated)

    def test_a_released_record_is_not_a_crash(self) -> None:
        result = reconcile(release(armed()), attached_program_ids=(), now_ns=SECOND)
        self.assertIs(result.state, ReconciliationState.RELEASED)
        self.assertFalse(result.gated)
        self.assertFalse(result.lapsed)

    def test_no_record_is_invalid_rather_than_clear(self) -> None:
        result = reconcile(None, attached_program_ids=(496,), now_ns=SECOND)
        self.assertIs(result.state, ReconciliationState.INVALID)
        self.assertFalse(result.gated)

    def test_a_non_tuple_observation_is_refused(self) -> None:
        result = reconcile(armed(), attached_program_ids=[496], now_ns=SECOND)
        self.assertIs(result.state, ReconciliationState.INVALID)
        self.assertFalse(result.gated)

    def test_non_integer_program_ids_are_refused(self) -> None:
        result = reconcile(armed(), attached_program_ids=("496",), now_ns=SECOND)
        self.assertIs(result.state, ReconciliationState.INVALID)

    def test_nothing_but_enforced_reports_gated(self) -> None:
        """The safety property, asserted over every state rather than by case.

        Built through `Reconciliation` so this tests the property itself. An
        earlier version of this test recomputed the expected value from the
        same expression it was checking, which asserted nothing at all.
        """
        for state in ReconciliationState:
            result = Reconciliation(state, "code")
            if state is ReconciliationState.ENFORCED:
                self.assertTrue(result.gated)
            else:
                self.assertFalse(result.gated, f"{state} must not read as gated")

    def test_only_orphaned_reports_a_lapsed_guarantee(self) -> None:
        for state in ReconciliationState:
            result = Reconciliation(state, "code")
            if state is ReconciliationState.ORPHANED:
                self.assertTrue(result.lapsed)
            else:
                self.assertFalse(result.lapsed, f"{state} must not read as lapsed")


class LifecycleTests(unittest.TestCase):
    def test_claim_then_arm_then_release_preserves_identity(self) -> None:
        first = claimed(now_ns=7)
        second = arm(first, program_id=496)
        third = release(second)
        for record in (second, third):
            self.assertEqual(record.owner_id, first.owner_id)
            self.assertEqual(record.cgroup_path, first.cgroup_path)
            self.assertEqual(record.device_set, first.device_set)
            self.assertEqual(record.claimed_at_ns, first.claimed_at_ns)
            self.assertEqual(record.expires_at_ns, first.expires_at_ns)

    def test_arming_keeps_the_program_id_for_reconciliation(self) -> None:
        self.assertEqual(arm(claimed(), program_id=496).program_id, 496)

    def test_release_keeps_the_program_id_for_the_audit_trail(self) -> None:
        self.assertEqual(release(armed(496)).program_id, 496)

    def test_a_zero_or_negative_lease_still_expires_after_it_begins(self) -> None:
        # A caller passing a nonsense lease must not produce an unexpirable
        # record; the floor keeps the invariant rather than raising.
        record = claim(
            owner_id=OWNER,
            cgroup_path=CGROUP,
            device_set=DEVICE_SET,
            now_ns=0,
            lease_ns=0,
        )
        self.assertGreater(record.expires_at_ns, record.claimed_at_ns)


if __name__ == "__main__":
    unittest.main()
