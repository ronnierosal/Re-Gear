from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.filter_authorization import (  # noqa: E402
    AuthorizationState,
    CgroupIdentity,
    OwnerIdentity,
    ParentScopeAuthorization,
    authorize_parent_scope,
)
from hdm.domain.filter_ownership import (  # noqa: E402
    FILTER_OWNERSHIP_SCHEMA_VERSION,
    AttachedFilter,
    FilterOwnership,
    OwnershipPhase,
    OwnershipRecovery,
    OwnershipRecoveryState,
    begin_release,
    claim,
    reconcile,
    record_attached,
)


UID = 1000
MANAGER = (
    f"/sys/fs/cgroup/user.slice/user-{UID}.slice/user@{UID}.service"
)
BOOT = "a" * 64
OTHER_BOOT = "b" * 64
CGROUP = CgroupIdentity(MANAGER, 27, 4242)
OWNER = OwnerIdentity(910, 55_500)
ATTACHED = AttachedFilter(17, 31, 99_000)


def granted(**overrides) -> ParentScopeAuthorization:
    arguments = {
        "cgroup": CGROUP,
        "uid": UID,
        "session_uid": UID,
        "owner": OWNER,
        "boot_hash": BOOT,
        "attachment_binding": "egpu-attachment-1",
        "generation": "gen-4",
        "sample_id": "sample-9",
        "deadline": 900.0,
    }
    arguments.update(overrides)
    authorization = authorize_parent_scope(**arguments)
    assert authorization.granted, authorization.code
    return authorization


def claimed() -> FilterOwnership:
    return claim(granted(), now_ns=1_700_000_000_000_000_000)


def armed() -> FilterOwnership:
    return record_attached(claimed(), ATTACHED)


class ClaimTests(unittest.TestCase):
    def test_a_claim_copies_the_grant_it_was_taken_under(self) -> None:
        record = claimed()
        self.assertEqual(record.schema_version, FILTER_OWNERSHIP_SCHEMA_VERSION)
        self.assertIs(record.phase, OwnershipPhase.CLAIMED)
        self.assertEqual(record.cgroup, CGROUP)
        self.assertEqual(record.owner, OWNER)
        self.assertEqual(record.uid, UID)
        self.assertEqual(record.boot_hash, BOOT)
        self.assertEqual(record.attachment_binding, "egpu-attachment-1")
        self.assertEqual(record.generation, "gen-4")
        self.assertEqual(record.sample_id, "sample-9")
        self.assertEqual(record.deadline, 900.0)

    def test_a_claim_names_no_attachment_yet(self) -> None:
        # The claim is written before the attach, so an attachment at this point
        # would be a record describing something that has not happened.
        self.assertIsNone(claimed().attached)

    def test_an_ungranted_authorization_cannot_claim(self) -> None:
        refused = ParentScopeAuthorization(
            AuthorizationState.REFUSED, "filter_authorization.uid_mismatch"
        )
        with self.assertRaises(ValueError):
            claim(refused, now_ns=1)

    def test_only_an_authorization_may_claim(self) -> None:
        with self.assertRaises(ValueError):
            claim(object(), now_ns=1)  # type: ignore[arg-type]


class PhaseTests(unittest.TestCase):
    def test_recording_an_attachment_keeps_every_binding_field(self) -> None:
        record = armed()
        self.assertIs(record.phase, OwnershipPhase.ARMED)
        self.assertEqual(record.attached, ATTACHED)
        self.assertEqual(
            replace(record, phase=OwnershipPhase.CLAIMED, attached=None), claimed()
        )

    def test_an_attachment_cannot_be_recorded_twice(self) -> None:
        with self.assertRaises(ValueError):
            record_attached(armed(), ATTACHED)

    def test_release_is_reachable_from_a_claim_that_never_attached(self) -> None:
        # The reason a claim is written before the attach is that the caller
        # cannot know whether the attach landed, so winding one up has to be
        # possible without an attachment identity.
        record = begin_release(claimed())
        self.assertIs(record.phase, OwnershipPhase.RELEASING)
        self.assertIsNone(record.attached)

    def test_release_is_idempotent(self) -> None:
        once = begin_release(armed())
        self.assertEqual(begin_release(once), once)

    def test_an_armed_record_must_name_its_attachment(self) -> None:
        with self.assertRaises(ValueError):
            replace(claimed(), phase=OwnershipPhase.ARMED)

    def test_a_claim_must_not_name_an_attachment(self) -> None:
        with self.assertRaises(ValueError):
            replace(claimed(), attached=ATTACHED)


class RecordValidationTests(unittest.TestCase):
    """A record rebuilt from a store must not bypass the grant's invariants."""

    def test_binding_evidence_is_required(self) -> None:
        for field in ("boot_hash", "attachment_binding", "generation", "sample_id"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    replace(claimed(), **{field: ""})

    def test_a_nonfinite_deadline_is_refused(self) -> None:
        for value in (float("inf"), float("nan"), 0.0, -1.0):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    replace(claimed(), deadline=value)

    def test_an_unsupported_schema_version_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            replace(claimed(), schema_version=FILTER_OWNERSHIP_SCHEMA_VERSION + 1)

    def test_an_attachment_identity_must_be_positive(self) -> None:
        for values in ((0, 1, 1), (1, 0, 1), (1, 1, 0), (-1, 1, 1)):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    AttachedFilter(*values)


def settle(record: FilterOwnership, **overrides) -> OwnershipRecovery:
    arguments = {
        "boot_hash": BOOT,
        "cgroup": CGROUP,
        "observed_owner_start_time": None,
        "now": 100.0,
    }
    arguments.update(overrides)
    return reconcile(record, **arguments)


class ReconcileTests(unittest.TestCase):
    def test_a_dead_owner_is_abandoned_and_clears_for_a_fresh_arm(self) -> None:
        recovery = settle(armed())
        self.assertIs(recovery.state, OwnershipRecoveryState.ABANDONED)
        self.assertEqual(recovery.code, "filter_ownership.abandoned")
        self.assertTrue(recovery.clear_record)
        self.assertTrue(recovery.may_rearm)
        self.assertIs(recovery.phase, OwnershipPhase.ARMED)
        self.assertEqual(recovery.attached, ATTACHED)

    def test_a_claim_that_may_never_have_attached_recovers_the_same_way(self) -> None:
        # The phase is audit detail, not the verdict: a CLAIMED record can
        # precede an attach whose ARMED write never landed, so it must not read
        # as "nothing was attached".
        for record in (claimed(), armed(), begin_release(armed())):
            with self.subTest(phase=record.phase):
                recovery = settle(record)
                self.assertIs(recovery.state, OwnershipRecoveryState.ABANDONED)
                self.assertTrue(recovery.clear_record)
                self.assertTrue(recovery.may_rearm)

    def test_a_reused_pid_reads_as_dead(self) -> None:
        # A different start time for the same pid is a different process, and
        # attributing a broad grant to a stranger would leave it unreleasable.
        recovery = settle(armed(), observed_owner_start_time=OWNER.start_time + 1)
        self.assertIs(recovery.state, OwnershipRecoveryState.ABANDONED)

    def test_a_live_owner_refuses_a_second_claim(self) -> None:
        recovery = settle(armed(), observed_owner_start_time=OWNER.start_time)
        self.assertIs(recovery.state, OwnershipRecoveryState.OWNER_LIVE)
        self.assertFalse(recovery.clear_record)
        self.assertFalse(recovery.may_rearm)

    def test_an_expired_lease_with_a_live_owner_neither_clears_nor_rearms(self) -> None:
        # The lease stops a stalled owner holding the broad scope forever, which
        # means refusing a new claim. It does not mean deleting the record: the
        # process that may still be enforcing the filter is alive.
        recovery = settle(
            armed(), observed_owner_start_time=OWNER.start_time, now=900.0
        )
        self.assertIs(recovery.state, OwnershipRecoveryState.EXPIRED_OWNER_LIVE)
        self.assertEqual(recovery.code, "filter_ownership.lease_expired_owner_live")
        self.assertFalse(recovery.clear_record)
        self.assertFalse(recovery.may_rearm)

    def test_a_different_boot_is_decided_before_the_owner_is_consulted(self) -> None:
        # A BPF link does not survive a reboot, so a live pid with a matching
        # start time on a new boot is a coincidence, not the old owner.
        recovery = settle(
            armed(),
            boot_hash=OTHER_BOOT,
            observed_owner_start_time=OWNER.start_time,
        )
        self.assertIs(recovery.state, OwnershipRecoveryState.DIFFERENT_BOOT)
        self.assertTrue(recovery.clear_record)
        self.assertTrue(recovery.may_rearm)

    def test_a_replaced_manager_cgroup_is_still_abandoned(self) -> None:
        recovery = settle(armed(), cgroup=CgroupIdentity(MANAGER, 27, 4243))
        self.assertIs(recovery.state, OwnershipRecoveryState.ABANDONED)
        self.assertEqual(recovery.code, "filter_ownership.abandoned_scope_replaced")
        self.assertTrue(recovery.clear_record)
        self.assertTrue(recovery.may_rearm)

    def test_an_unobservable_scope_clears_the_record_but_refuses_a_rearm(self) -> None:
        # The link is gone either way, so the record is finished with. Arming
        # against a scope that cannot be observed is a separate question and the
        # answer is no.
        recovery = settle(armed(), cgroup=None)
        self.assertIs(recovery.state, OwnershipRecoveryState.ABANDONED)
        self.assertEqual(recovery.code, "filter_ownership.abandoned_scope_unobserved")
        self.assertTrue(recovery.clear_record)
        self.assertFalse(recovery.may_rearm)


class ReconcileFailsClosedTests(unittest.TestCase):
    def test_an_unknown_boot_decides_nothing(self) -> None:
        for value in ("", None, 7):
            with self.subTest(value=value):
                recovery = settle(armed(), boot_hash=value)
                self.assertIs(recovery.state, OwnershipRecoveryState.INVALID)
                self.assertFalse(recovery.clear_record)
                self.assertFalse(recovery.may_rearm)

    def test_an_unusable_clock_decides_nothing(self) -> None:
        for value in (float("nan"), float("inf"), -1.0, "100"):
            with self.subTest(value=value):
                recovery = settle(
                    armed(),
                    observed_owner_start_time=OWNER.start_time,
                    now=value,
                )
                self.assertIs(recovery.state, OwnershipRecoveryState.INVALID)
                self.assertFalse(recovery.clear_record)

    def test_an_invalid_owner_observation_decides_nothing(self) -> None:
        for value in (0, -3, True, 1.5):
            with self.subTest(value=value):
                recovery = settle(armed(), observed_owner_start_time=value)
                self.assertIs(recovery.state, OwnershipRecoveryState.INVALID)

    def test_an_invalid_cgroup_observation_decides_nothing(self) -> None:
        recovery = settle(armed(), cgroup=MANAGER)
        self.assertIs(recovery.state, OwnershipRecoveryState.INVALID)
        self.assertFalse(recovery.clear_record)

    def test_something_that_is_not_a_record_decides_nothing(self) -> None:
        recovery = settle(object())  # type: ignore[arg-type]
        self.assertIs(recovery.state, OwnershipRecoveryState.INVALID)
        self.assertEqual(recovery.code, "filter_ownership.record_invalid")


class RecoveryNeverPermitsRemovalTests(unittest.TestCase):
    def test_no_recovery_state_grants_a_removal(self) -> None:
        # Settling a filter record says nothing about holders, render state,
        # displays, or whether a device may be detached. Pinned so a later field
        # cannot quietly become a permission.
        for state in OwnershipRecoveryState:
            with self.subTest(state=state):
                self.assertFalse(OwnershipRecovery(state, "code").grants_removal)

    def test_a_rearm_must_clear_the_record_it_replaces(self) -> None:
        with self.assertRaises(ValueError):
            OwnershipRecovery(
                OwnershipRecoveryState.ABANDONED, "code", may_rearm=True
            )

    def test_every_reconcile_result_that_rearms_also_clears(self) -> None:
        cases = (
            settle(armed()),
            settle(armed(), boot_hash=OTHER_BOOT),
            settle(armed(), cgroup=CgroupIdentity(MANAGER, 27, 4243)),
            settle(armed(), cgroup=None),
            settle(armed(), observed_owner_start_time=OWNER.start_time),
        )
        for recovery in cases:
            with self.subTest(code=recovery.code):
                self.assertFalse(recovery.may_rearm and not recovery.clear_record)


if __name__ == "__main__":
    unittest.main()
