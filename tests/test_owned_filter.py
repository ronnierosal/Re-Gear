from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.application.filter_arm import FilterArmCoordinator, HolderObservation  # noqa: E402
from hdm.application.owned_filter import OwnedDeviceFilter  # noqa: E402
from hdm.delivery.filter_ownership_store import (  # noqa: E402
    RECORD_FILENAME,
    FileFilterOwnershipStore,
)
from hdm.domain.filter_authorization import (  # noqa: E402
    AuthorizationState,
    CgroupIdentity,
    OwnerIdentity,
    ParentScopeAuthorization,
    authorize_parent_scope,
)
from hdm.domain.filter_ownership import (  # noqa: E402
    OwnershipPhase,
    OwnershipRecoveryState,
)
from hdm.ports.device_filter import (  # noqa: E402
    ArmedFilter,
    ArmOutcome,
    ArmResult,
    DisarmOutcome,
    DisarmResult,
)


UID = 1000
MANAGER = f"/sys/fs/cgroup/user.slice/user-{UID}.slice/user@{UID}.service"
BOOT = "d" * 64
OTHER_BOOT = "e" * 64
CGROUP = CgroupIdentity(MANAGER, 27, 4242)
OWNER = OwnerIdentity(910, 55_500)
SECOND_OWNER = OwnerIdentity(1455, 61_200)
PROGRAM = b"\x00" * 16
ARMED = ArmedFilter(17, 31, 99_000)


def grant(owner: OwnerIdentity = OWNER, *, deadline: float = 900.0, **overrides):
    arguments = {
        "cgroup": CGROUP,
        "uid": UID,
        "session_uid": UID,
        "owner": owner,
        "boot_hash": BOOT,
        "attachment_binding": "egpu-attachment-1",
        "generation": "gen-4",
        "sample_id": "sample-9",
        "deadline": deadline,
    }
    arguments.update(overrides)
    authorization = authorize_parent_scope(**arguments)
    assert authorization.granted, authorization.code
    return authorization


class FakeFilter:
    """A `DeviceFilterPort` that records what it was asked to do."""

    def __init__(
        self,
        *,
        events: list[str] | None = None,
        arm_result: ArmResult | None = None,
        disarm_result: DisarmResult | None = None,
    ) -> None:
        self.events = events if events is not None else []
        self._arm_result = arm_result or ArmResult(ArmOutcome.ARMED, ARMED)
        self._disarm_result = disarm_result or DisarmResult(DisarmOutcome.DISARMED)
        self.attached = False
        self.enforced_calls = 0

    def arm(self, program: bytes, cgroup: CgroupIdentity) -> ArmResult:
        self.events.append("filter.arm")
        if self._arm_result.ok:
            self.attached = True
        return self._arm_result

    def enforced(self, cgroup: CgroupIdentity, program_id: int) -> bool:
        self.enforced_calls += 1
        return self.attached and program_id == ARMED.program_id

    def disarm(self) -> DisarmResult:
        self.events.append("filter.disarm")
        if self._disarm_result.ok:
            self.attached = False
        return self._disarm_result


class RecordingStore:
    """An in-memory store that logs its calls and can be made to fail."""

    def __init__(self, *, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.record = None
        self.fail_save = False
        self.fail_load = False
        self.fail_clear = False
        #: Runs after a successful load, to stage whatever a concurrent owner
        #: would have done in the gap before this one writes.
        self.on_load = None

    def load(self):
        self.events.append("store.load")
        if self.fail_load:
            raise ValueError("unreadable")
        value = self.record
        if self.on_load is not None:
            self.on_load()
        return value

    def create(self, record) -> None:
        self.events.append(f"store.create:{record.phase.value}")
        if self.fail_save:
            raise OSError("no space")
        if self.record is not None:
            raise FileExistsError("already claimed")
        self.record = record

    def save(self, record) -> None:
        self.events.append(f"store.save:{record.phase.value}")
        if self.fail_save:
            raise OSError("no space")
        self.record = record

    def clear(self) -> None:
        self.events.append("store.clear")
        if self.fail_clear:
            raise OSError("read-only")
        self.record = None


def owned(
    filter_: FakeFilter,
    store,
    *,
    live_owners: tuple[OwnerIdentity, ...] = (),
    boot: str = BOOT,
    cgroup: CgroupIdentity | None = CGROUP,
    now: float = 100.0,
) -> OwnedDeviceFilter:
    """An `OwnedDeviceFilter` whose observations are fixtures.

    `live_owners` is the set of processes that still exist. A recorded owner
    outside it reads as dead, which is how a crash is represented.
    """

    def observe_owner(pid: int):
        for owner in live_owners:
            if owner.pid == pid:
                return owner
        return None

    return OwnedDeviceFilter(
        device_filter=filter_,
        store=store,
        observe_owner=observe_owner,
        observe_cgroup=lambda: cgroup,
        boot_hash=lambda: boot,
        monotonic=lambda: now,
        now_ns=lambda: 1_700_000_000_000_000_000,
    )


class ClaimOrderingTests(unittest.TestCase):
    def test_the_record_is_durable_before_anything_is_attached(self) -> None:
        # The whole guarantee rests on this order. A filter attached before its
        # record exists is the silent failure the journal exists to prevent.
        events: list[str] = []
        filter_ = FakeFilter(events=events)
        store = RecordingStore(events=events)
        subject = owned(filter_, store)

        self.assertTrue(subject.claim(grant()).ok)
        subject.arm(PROGRAM, CGROUP)

        self.assertEqual(
            events,
            ["store.load", "store.create:claimed", "filter.arm", "store.save:armed"],
        )

    def test_arming_without_a_claim_is_refused(self) -> None:
        filter_ = FakeFilter()
        subject = owned(filter_, RecordingStore())
        result = subject.arm(PROGRAM, CGROUP)
        self.assertIs(result.outcome, ArmOutcome.REFUSED)
        self.assertEqual(result.code, "filter_ownership.unclaimed")
        self.assertFalse(filter_.attached)

    def test_a_claim_cannot_be_consumed_twice(self) -> None:
        filter_ = FakeFilter()
        subject = owned(filter_, RecordingStore())
        self.assertTrue(subject.claim(grant()).ok)
        self.assertTrue(subject.arm(PROGRAM, CGROUP).ok)
        again = subject.arm(PROGRAM, CGROUP)
        self.assertEqual(again.code, "filter_ownership.unclaimed")

    def test_an_ungranted_authorization_cannot_claim(self) -> None:
        subject = owned(FakeFilter(), RecordingStore())
        refused = ParentScopeAuthorization(
            AuthorizationState.REFUSED, "filter_authorization.uid_mismatch"
        )
        result = subject.claim(refused)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "filter_ownership.not_authorized")

    def test_a_claim_must_describe_the_scope_that_is_attached(self) -> None:
        filter_ = FakeFilter()
        subject = owned(filter_, RecordingStore())
        self.assertTrue(subject.claim(grant()).ok)
        result = subject.arm(PROGRAM, CgroupIdentity(MANAGER, 27, 4243))
        self.assertEqual(result.code, "filter_ownership.scope_mismatch")
        self.assertFalse(filter_.attached)

    def test_a_second_claim_while_armed_is_refused(self) -> None:
        subject = owned(FakeFilter(), RecordingStore())
        self.assertTrue(subject.claim(grant()).ok)
        self.assertTrue(subject.arm(PROGRAM, CGROUP).ok)
        result = subject.claim(grant())
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "filter_ownership.already_armed")

    def test_a_claim_the_sequence_refused_before_arming_is_reusable(self) -> None:
        # `FilterArmCoordinator` can refuse after the claim and before the
        # attach, on a stale authorization. That must not leave the instance
        # unable to claim again for the rest of its life.
        store = RecordingStore()
        subject = owned(FakeFilter(), store)
        self.assertTrue(subject.claim(grant()).ok)
        second = subject.claim(grant())
        self.assertTrue(second.ok, second.code)
        self.assertIs(store.record.phase, OwnershipPhase.CLAIMED)


class FailClosedTests(unittest.TestCase):
    def test_an_unreadable_stored_record_refuses_the_claim(self) -> None:
        store = RecordingStore()
        store.fail_load = True
        filter_ = FakeFilter()
        subject = owned(filter_, store)
        result = subject.claim(grant())
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "filter_ownership.record_unreadable")
        self.assertEqual(subject.arm(PROGRAM, CGROUP).code, "filter_ownership.unclaimed")
        self.assertFalse(filter_.attached)

    def test_a_record_that_cannot_be_written_refuses_the_claim(self) -> None:
        store = RecordingStore()
        store.fail_save = True
        filter_ = FakeFilter()
        subject = owned(filter_, store)
        result = subject.claim(grant())
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "filter_ownership.record_unwritable")
        self.assertFalse(filter_.attached)

    def test_a_stale_record_that_cannot_be_cleared_refuses_the_claim(self) -> None:
        store = RecordingStore()
        subject = owned(FakeFilter(), store)
        self.assertTrue(subject.claim(grant()).ok)
        store.fail_clear = True
        # A fresh instance finds the abandoned record and cannot settle it.
        successor = owned(FakeFilter(), store)
        result = successor.claim(grant(SECOND_OWNER))
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "filter_ownership.record_unclearable")

    def test_a_scope_claimed_underneath_this_one_refuses(self) -> None:
        # Two owners reconciled the same empty store. The exclusive create is
        # what stops both of them believing they hold the scope.
        store = RecordingStore()
        winner = owned(FakeFilter(), store)
        loser = owned(FakeFilter(), store)

        def winner_claims() -> None:
            store.on_load = None
            self.assertTrue(winner.claim(grant()).ok)

        # The loser looks and sees nothing; the winner lands its claim before
        # the loser gets to write.
        store.on_load = winner_claims

        result = loser.claim(grant(SECOND_OWNER))

        self.assertFalse(result.ok)
        self.assertEqual(result.code, "filter_ownership.claim_raced")
        self.assertEqual(store.record.owner, OWNER)
        self.assertEqual(
            loser.arm(PROGRAM, CGROUP).code, "filter_ownership.unclaimed"
        )

    def test_an_attachment_whose_identity_cannot_be_recorded_is_taken_down(self) -> None:
        events: list[str] = []
        filter_ = FakeFilter(events=events)
        store = RecordingStore(events=events)
        subject = owned(filter_, store)
        self.assertTrue(subject.claim(grant()).ok)
        store.fail_save = True

        result = subject.arm(PROGRAM, CGROUP)

        self.assertIs(result.outcome, ArmOutcome.REFUSED)
        self.assertEqual(result.code, "filter_ownership.record_unwritable")
        # Refused before any restart, so the player's session is undisturbed,
        # and the filter is not left up behind an unrecordable release.
        self.assertFalse(filter_.attached)
        self.assertIn("filter.disarm", events)


class ReleaseTests(unittest.TestCase):
    def test_the_release_is_recorded_before_the_detach_is_issued(self) -> None:
        events: list[str] = []
        filter_ = FakeFilter(events=events)
        store = RecordingStore(events=events)
        subject = owned(filter_, store)
        self.assertTrue(subject.claim(grant()).ok)
        self.assertTrue(subject.arm(PROGRAM, CGROUP).ok)
        events.clear()

        self.assertTrue(subject.disarm().ok)

        self.assertEqual(
            events, ["store.save:releasing", "filter.disarm", "store.clear"]
        )
        self.assertIsNone(store.record)

    def test_a_failed_detach_keeps_the_record(self) -> None:
        # The link may still be attached. Deleting the record here would produce
        # exactly the state this module exists to make impossible.
        filter_ = FakeFilter(
            disarm_result=DisarmResult(
                DisarmOutcome.FAILED, "device_filter.detach_failed"
            )
        )
        store = RecordingStore()
        subject = owned(filter_, store)
        self.assertTrue(subject.claim(grant()).ok)
        self.assertTrue(subject.arm(PROGRAM, CGROUP).ok)

        self.assertFalse(subject.disarm().ok)

        self.assertIsNotNone(store.record)
        self.assertIs(store.record.phase, OwnershipPhase.RELEASING)
        self.assertEqual(store.record.attached.link_id, ARMED.link_id)
        # And no new claim is taken over a scope that may still be filtered.
        self.assertEqual(subject.claim(grant()).code, "filter_ownership.already_armed")

    def test_a_failed_arm_leaves_no_record_behind(self) -> None:
        filter_ = FakeFilter(
            arm_result=ArmResult(
                ArmOutcome.ATTACH_FAILED, code="device_filter.attach_failed"
            )
        )
        store = RecordingStore()
        subject = owned(filter_, store)
        self.assertTrue(subject.claim(grant()).ok)

        result = subject.arm(PROGRAM, CGROUP)

        self.assertIs(result.outcome, ArmOutcome.ATTACH_FAILED)
        self.assertIsNone(store.record)

    def test_disarming_with_no_record_passes_straight_through(self) -> None:
        filter_ = FakeFilter(disarm_result=DisarmResult(DisarmOutcome.NOT_ARMED))
        store = RecordingStore()
        subject = owned(filter_, store)
        self.assertIs(subject.disarm().outcome, DisarmOutcome.NOT_ARMED)
        self.assertEqual(store.events, [])

    def test_enforcement_queries_write_nothing(self) -> None:
        # `FilterArmCoordinator` asks before every restart, so this must not
        # turn into a write per unit.
        filter_ = FakeFilter()
        store = RecordingStore()
        subject = owned(filter_, store)
        self.assertTrue(subject.claim(grant()).ok)
        self.assertTrue(subject.arm(PROGRAM, CGROUP).ok)
        store.events.clear()
        for _ in range(3):
            self.assertTrue(subject.enforced(CGROUP, ARMED.program_id))
        self.assertEqual(store.events, [])


class CrashRecoveryTests(unittest.TestCase):
    """The acceptance case: a crash between arm and disarm, settled next start."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = FileFilterOwnershipStore(self.root)

    def crash_while_armed(self) -> None:
        """Arm, then abandon the owner without ever disarming."""
        crashed = owned(FakeFilter(), self.store, live_owners=(OWNER,))
        self.assertTrue(crashed.claim(grant()).ok)
        self.assertTrue(crashed.arm(PROGRAM, CGROUP).ok)
        del crashed

    def test_the_record_survives_the_process_that_wrote_it(self) -> None:
        self.crash_while_armed()
        self.assertTrue((self.root / RECORD_FILENAME).exists())
        record = self.store.load()
        self.assertIsNotNone(record)
        self.assertIs(record.phase, OwnershipPhase.ARMED)
        self.assertEqual(record.attached.link_id, ARMED.link_id)
        self.assertEqual(record.owner, OWNER)
        self.assertEqual(record.boot_hash, BOOT)
        self.assertEqual(record.attachment_binding, "egpu-attachment-1")

    def test_the_next_start_reconciles_it_without_mutating_anything(self) -> None:
        self.crash_while_armed()
        # A new process: the recorded owner no longer exists.
        successor = owned(FakeFilter(), self.store)

        recovery = successor.recovery()

        self.assertIs(recovery.state, OwnershipRecoveryState.ABANDONED)
        self.assertIs(recovery.phase, OwnershipPhase.ARMED)
        self.assertEqual(recovery.attached.link_id, ARMED.link_id)
        self.assertTrue(recovery.clear_record)
        self.assertFalse(recovery.grants_removal)
        # Observation only: the record is still there for whoever acts on it.
        self.assertIsNotNone(self.store.load())

    def test_the_next_claim_settles_the_abandoned_record_and_proceeds(self) -> None:
        self.crash_while_armed()
        filter_ = FakeFilter()
        successor = owned(filter_, self.store)

        result = successor.claim(grant(SECOND_OWNER))

        self.assertTrue(result.ok, result.code)
        self.assertIs(result.recovery.state, OwnershipRecoveryState.ABANDONED)
        self.assertTrue(successor.arm(PROGRAM, CGROUP).ok)
        # The new owner's record replaced the abandoned one.
        record = self.store.load()
        self.assertEqual(record.owner, SECOND_OWNER)
        self.assertIs(record.phase, OwnershipPhase.ARMED)

    def test_a_crash_before_the_attach_is_still_visible(self) -> None:
        # The claim is written first precisely so this gap is not silent.
        crashed = owned(FakeFilter(), self.store, live_owners=(OWNER,))
        self.assertTrue(crashed.claim(grant()).ok)
        del crashed

        successor = owned(FakeFilter(), self.store)
        recovery = successor.recovery()
        self.assertIs(recovery.state, OwnershipRecoveryState.ABANDONED)
        self.assertIs(recovery.phase, OwnershipPhase.CLAIMED)
        self.assertTrue(recovery.clear_record)

    def test_a_live_owner_blocks_a_second_process_from_claiming(self) -> None:
        self.crash_while_armed()
        # Same record, but the recorded owner turns out to still be running.
        successor = owned(FakeFilter(), self.store, live_owners=(OWNER,))

        result = successor.claim(grant(SECOND_OWNER))

        self.assertFalse(result.ok)
        self.assertEqual(result.code, "filter_ownership.owner_live")
        # The live owner's record is untouched.
        self.assertIs(self.store.load().phase, OwnershipPhase.ARMED)

    def test_a_reboot_settles_the_record_without_consulting_the_pid(self) -> None:
        self.crash_while_armed()
        successor = owned(
            FakeFilter(), self.store, live_owners=(OWNER,), boot=OTHER_BOOT
        )
        recovery = successor.recovery()
        self.assertIs(recovery.state, OwnershipRecoveryState.DIFFERENT_BOOT)
        self.assertTrue(recovery.clear_record)
        self.assertTrue(recovery.may_rearm)

    def test_an_expired_lease_over_a_live_owner_refuses_and_keeps_the_record(
        self,
    ) -> None:
        self.crash_while_armed()
        successor = owned(
            FakeFilter(), self.store, live_owners=(OWNER,), now=1_000.0
        )
        result = successor.claim(grant(SECOND_OWNER))
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "filter_ownership.lease_expired_owner_live")
        self.assertIsNotNone(self.store.load())

    def test_an_unreadable_record_refuses_rather_than_arming_over_it(self) -> None:
        self.crash_while_armed()
        (self.root / RECORD_FILENAME).write_bytes(b"{truncated")
        filter_ = FakeFilter()
        successor = owned(filter_, self.store)
        result = successor.claim(grant(SECOND_OWNER))
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "filter_ownership.record_unreadable")
        self.assertFalse(filter_.attached)
        with self.assertRaises(ValueError):
            successor.recovery()


class CoordinatorIntegrationTests(unittest.TestCase):
    """The journal brackets the window the real sequence opens and closes."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = FileFilterOwnershipStore(self.root)
        self.filter = FakeFilter()
        self.subject = owned(self.filter, self.store, live_owners=(OWNER,))
        self.restarted: list[str] = []

    def restart(self, unit: str) -> bool:
        self.restarted.append(unit)
        return True

    def coordinator(self, after: HolderObservation) -> FilterArmCoordinator:
        """A sequence that sees one holder, restarts, then sees `after`."""
        observations = [HolderObservation(("wireplumber.service",), True), after]

        def observe_holders() -> HolderObservation:
            return observations.pop(0) if len(observations) > 1 else observations[0]

        return FilterArmCoordinator(
            device_filter=self.subject,
            restart=self.restart,
            observe_holders=observe_holders,
            observe_cgroup=lambda: CGROUP,
            monotonic=lambda: 100.0,
        )

    def test_a_cleared_device_leaves_the_record_standing_until_disarm(self) -> None:
        coordinator = self.coordinator(HolderObservation((), True))
        authorization = grant()
        # The claim is taken where the runtime takes it: alongside the grant,
        # before the sequence that arms is entered.
        self.assertTrue(self.subject.claim(authorization).ok)
        result = coordinator.arm(authorization, PROGRAM, boot_hash=BOOT)
        self.assertTrue(result.ok, result.code)
        # Still armed, so the record must still describe it: this is the window
        # a crash has to stay visible in.
        record = self.store.load()
        self.assertIs(record.phase, OwnershipPhase.ARMED)
        self.assertTrue(self.restarted)

        self.assertTrue(self.subject.disarm().ok)
        self.assertIsNone(self.store.load())

    def test_a_sequence_failure_after_arming_clears_through_its_own_disarm(
        self,
    ) -> None:
        # The coordinator disarms on every failure after arming, and it does so
        # through this port, so the record is settled without the coordinator
        # knowing a journal exists.
        coordinator = self.coordinator(HolderObservation(("wireplumber.service",), True))
        authorization = grant()
        self.assertTrue(self.subject.claim(authorization).ok)
        result = coordinator.arm(authorization, PROGRAM, boot_hash=BOOT)
        self.assertFalse(result.ok)
        self.assertTrue(result.disarmed)
        self.assertIsNone(self.store.load())

    def test_the_sequence_cannot_arm_without_a_claim_at_all(self) -> None:
        # Fail closed: the coordinator is given a grant but no claim was taken,
        # so nothing attaches and the session is never disturbed.
        coordinator = self.coordinator(HolderObservation((), True))
        result = coordinator.arm(grant(), PROGRAM, boot_hash=BOOT)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "filter_ownership.unclaimed")
        self.assertFalse(result.session_disturbed)
        self.assertFalse(self.filter.attached)
        self.assertIsNone(self.store.load())


class ProductionWiringTests(unittest.TestCase):
    """The journal is reachable from the composed runtime, not only from tests.

    #155 removed an earlier ownership record, and the reason the slice was still
    outstanding afterwards was that the surviving filter stack was "referenced by
    no non-test module at all". A record nothing wires in does not make any crash
    visible, so the composition is asserted here rather than assumed.
    """

    def builder(self) -> ast.FunctionDef:
        source = (
            ROOT / "backend" / "hdm" / "delivery" / "live_disconnect_runtime.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "build_live_disconnect_runtime"
            ):
                return node
        self.fail("build_live_disconnect_runtime is missing")

    def calls(self, node: ast.AST) -> set[str]:
        return {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }

    def test_the_runtime_composes_the_filter_behind_the_journal(self) -> None:
        builder = self.builder()
        self.assertIn("OwnedDeviceFilter", self.calls(builder))
        self.assertIn("FileFilterOwnershipStore", self.calls(builder))

    def test_the_runtime_claims_ownership_before_handing_out_a_grant(self) -> None:
        builder = self.builder()
        claims = {
            ast.unparse(node.func)
            for node in ast.walk(builder)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("device_filter.claim", claims)


if __name__ == "__main__":
    unittest.main()
