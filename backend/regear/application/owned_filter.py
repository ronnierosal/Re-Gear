"""Journal parent-scope filter ownership around the arm and disarm window.

`regear.application.filter_arm` is explicit that an unpinned link vanishing with
its owner is not durable recovery, and says the caller is told what state it was
left in. That only works while the caller is alive. This is the part that works
when it is not: a `DeviceFilterPort` that writes a durable record before the
attach and clears it only after a verified detach, so the window between them --
the one a crash makes invisible -- always leaves evidence behind.

It is a port wrapper rather than a change to the coordinator because the window
is exactly the port's two mutating calls. `FilterArmCoordinator` arms through the
port and disarms through it on every failure path, and `LiveDisconnectService`
disarms through the same port when the removal has finished either way. Wrapping
the port therefore brackets the whole window, including the coordinator's own
recovery disarms, without the sequencing logic having to know a journal exists.

The ordering is the one `regear.ports.filter_ownership` requires, and the reason for
it is worth being concrete about:

1. `claim` reconciles any stored record, then writes this attempt's record and
   waits for it to be durable. Nothing is attached yet.
2. `arm` refuses unless a durable claim exists. An attach with no record is the
   silent failure this exists to prevent, so it is made unreachable rather than
   merely avoided.
3. `disarm` records the release *before* issuing the detach, and clears the
   record only when the detach is verified. A crash during the detach leaves a
   record, not a clean slate.

What a claim is not. It records that an attempt was made; it grants nothing. It
is not an authorization -- `regear.domain.filter_authorization` is -- and it is not
evidence that a device is clear, ready or detachable. Safety invariant 10 is
untouched by anything in this module.

Not thread-safe, and does not need to be: `LiveDisconnectRuntime` already
serializes attempts, and `CgroupDeviceFilter` holds one attachment at a time for
the same reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..domain.filter_authorization import (
    CgroupIdentity,
    OwnerIdentity,
    ParentScopeAuthorization,
)
from ..domain.filter_ownership import (
    AttachedFilter,
    FilterOwnership,
    OwnershipPhase,
    OwnershipRecovery,
    begin_release,
    claim as claim_ownership,
    reconcile,
    record_attached,
)
from ..ports.device_filter import (
    ArmOutcome,
    ArmResult,
    DeviceFilterPort,
    DisarmOutcome,
    DisarmResult,
)
from ..ports.filter_ownership import FilterOwnershipStore


@dataclass(frozen=True, slots=True)
class ClaimResult:
    """Whether this attempt may proceed to arm, and why not when it may not."""

    claimed: bool
    code: str
    #: What reconciling the stored record concluded, when one was stored. Kept
    #: so a caller can report that a previous attempt was abandoned rather than
    #: silently absorbing it.
    recovery: OwnershipRecovery | None = None

    @property
    def ok(self) -> bool:
        return self.claimed


class OwnedDeviceFilter:
    """A `DeviceFilterPort` that records ownership across a crash."""

    def __init__(
        self,
        *,
        device_filter: DeviceFilterPort,
        store: FilterOwnershipStore,
        observe_owner: Callable[[int], OwnerIdentity | None],
        observe_cgroup: Callable[[], CgroupIdentity | None],
        boot_hash: Callable[[], str],
        monotonic: Callable[[], float],
        now_ns: Callable[[], int],
    ) -> None:
        self._filter = device_filter
        self._store = store
        self._observe_owner = observe_owner
        self._observe_cgroup = observe_cgroup
        self._boot_hash = boot_hash
        self._monotonic = monotonic
        self._now_ns = now_ns
        self._record: FilterOwnership | None = None
        self._attached = False

    # -- observation ------------------------------------------------------

    def recovery(self) -> OwnershipRecovery | None:
        """Reconcile the stored record without changing anything.

        None means no record is stored. Raises when one is stored and cannot be
        read, because an unreadable record and an absent one need opposite
        answers. Safe to call from a status path: it observes and never clears,
        arms or detaches.
        """
        record = self._store.load()
        if record is None:
            return None
        return self._reconcile(record)

    # -- the claim --------------------------------------------------------

    def claim(self, authorization: ParentScopeAuthorization) -> ClaimResult:
        """Reconcile any stored record, then record this attempt durably.

        Refuses rather than proceeding whenever the scope might still be held,
        whenever the stored record cannot be read, and whenever this attempt's
        own record cannot be written. All three are the same judgement: an
        attach whose record is uncertain is worse than no attach.
        """
        if type(authorization) is not ParentScopeAuthorization:
            return ClaimResult(False, "filter_ownership.authorization_invalid")
        if not authorization.granted:
            return ClaimResult(False, "filter_ownership.not_authorized")
        if self._attached:
            # This instance is still holding a filter. A second claim would
            # overwrite the record describing the live one.
            return ClaimResult(False, "filter_ownership.already_armed")

        if self._record is not None:
            # A claim this instance made and never armed: an earlier attempt
            # that the coordinator refused before attaching anything. Release it
            # rather than refusing every later attempt for the process lifetime.
            self._release_unarmed_claim()

        try:
            stored = self._store.load()
        except Exception:
            return ClaimResult(False, "filter_ownership.record_unreadable")

        recovery: OwnershipRecovery | None = None
        if stored is not None:
            recovery = self._reconcile(stored)
            if recovery.clear_record:
                try:
                    self._store.clear()
                except Exception:
                    return ClaimResult(
                        False, "filter_ownership.record_unclearable", recovery
                    )
            if not recovery.may_rearm:
                # Either something may still hold the scope, or the record was
                # settled but the conditions for a fresh grant are not
                # established. Both refuse this attempt.
                return ClaimResult(False, recovery.code, recovery)

        record = claim_ownership(authorization, now_ns=self._now_ns())
        try:
            # Exclusive, not a replace. Another process that reconciled the same
            # abandoned record may have claimed the scope between the load above
            # and here, and two owners recorded for one scope is the state the
            # journal exists to make impossible.
            self._store.create(record)
        except FileExistsError:
            return ClaimResult(False, "filter_ownership.claim_raced", recovery)
        except Exception:
            return ClaimResult(False, "filter_ownership.record_unwritable", recovery)
        self._record = record
        return ClaimResult(True, "filter_ownership.claimed", recovery)

    # -- the port ---------------------------------------------------------

    def arm(self, program: bytes, cgroup: CgroupIdentity) -> ArmResult:
        """Attach only behind a durable claim describing this exact scope."""
        if self._record is None or self._record.phase is not OwnershipPhase.CLAIMED:
            # Fail closed. The whole point of the record is that no attachment
            # exists without one, so an unclaimed arm is refused rather than
            # journalled after the fact.
            return ArmResult(ArmOutcome.REFUSED, code="filter_ownership.unclaimed")
        if type(cgroup) is not CgroupIdentity:
            return ArmResult(ArmOutcome.REFUSED, code="filter_ownership.scope_invalid")
        recorded = self._record.cgroup
        if (cgroup.path, cgroup.device, cgroup.inode) != (
            recorded.path,
            recorded.device,
            recorded.inode,
        ):
            # A record naming one cgroup while the attach targets another would
            # be worse than no record: recovery would look in the wrong place.
            return ArmResult(ArmOutcome.REFUSED, code="filter_ownership.scope_mismatch")

        result = self._filter.arm(program, cgroup)
        if not result.ok or result.filter is None:
            # Nothing is attached. The claim is released through `RELEASING`
            # rather than deleted outright, so a crash in this gap still reads
            # as an attempt that was being wound up.
            self._release_unarmed_claim()
            return result

        self._attached = True
        attached = AttachedFilter(
            result.filter.program_id, result.filter.link_id, result.filter.cgroup_id
        )
        try:
            self._record = record_attached(self._record, attached)
            self._store.save(self._record)
        except Exception:
            # A live filter whose identity could not be recorded. The claim on
            # disk already makes the attempt visible, so this is not a silent
            # attach -- but continuing with a record that cannot be updated
            # means the release could not be recorded either. Take the filter
            # back down and refuse, which leaves the session undisturbed.
            self.disarm()
            return ArmResult(
                ArmOutcome.REFUSED, code="filter_ownership.record_unwritable"
            )
        return result

    def enforced(self, cgroup: CgroupIdentity, program_id: int) -> bool:
        """Pass through. Asking whether a filter is enforced writes nothing."""
        return self._filter.enforced(cgroup, program_id)

    def disarm(self) -> DisarmResult:
        """Record the release, detach, and clear the record only once verified.

        A failed detach keeps the record. The link may still be attached, and
        deleting the record would leave the one case this module exists for: a
        filter in place with nothing saying so.
        """
        if self._record is None:
            return self._filter.disarm()

        self._mark_releasing()
        result = self._filter.disarm()
        if result.ok:
            self._forget()
        elif result.outcome is DisarmOutcome.NOT_ARMED:
            # The wrapped port never had an attachment, so there is nothing that
            # could still be holding the scope and nothing to recover.
            self._forget()
        return result

    # -- record maintenance -----------------------------------------------

    def _reconcile(self, record: FilterOwnership) -> OwnershipRecovery:
        observed = self._observe_owner(record.owner.pid)
        return reconcile(
            record,
            boot_hash=self._boot_hash(),
            cgroup=self._observe_cgroup(),
            observed_owner_start_time=None if observed is None else observed.start_time,
            now=self._monotonic(),
        )

    def _release_unarmed_claim(self) -> None:
        """Wind up a claim that provably never produced an attachment."""
        self._mark_releasing()
        self._forget()

    def _mark_releasing(self) -> None:
        """Record that a release is under way, before the detach is issued.

        A failure to write is deliberately not fatal: the record already on disk
        reconciles safely either way, and refusing to detach because the journal
        could not be updated would leave the filter attached instead.
        """
        if self._record is None:
            return
        releasing = begin_release(self._record)
        try:
            self._store.save(releasing)
        except Exception:
            return
        self._record = releasing

    def _forget(self) -> None:
        """Drop the record once nothing it describes can still be attached."""
        try:
            self._store.clear()
        except Exception:
            # The stale record reconciles as abandoned on the next claim, which
            # clears it then. Refusing to forget it here would make this
            # instance unusable for the rest of its life.
            pass
        self._record = None
        self._attached = False
