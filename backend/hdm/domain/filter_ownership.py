"""Durable record of one parent-scope filter attempt, and its recovery verdict.

`docs/DEVICE_FILTER_RELEASE_2026-09-08.md` names the gap this fills: the link
`hdm.adapters.steamos.device_filter` attaches is **unpinned**, so it disappears
with its owner, "and there is no ownership journal, so nothing records that a
filter was ever in place." `docs/FILTER_PRIMITIVES_INTEGRATION.md` says the same
thing as a requirement on the production caller -- serialize and journal
ownership, preserve recovery on cancellation, timeout or owner failure -- and
adds that an unpinned link vanishing when its owner exits is not durable
recovery. This is the record that makes the vanishing visible.

Why this is a new record and not the existing one. `main` already carries
`hdm.delivery.device_filter_lifecycle` and `hdm.delivery.device_filter_journal`,
and #155 removed an earlier ownership record for duplicating them. Neither can
represent this model, for two structural reasons rather than stylistic ones:

- `LaunchBinding` raises `unapproved unit` for anything but
  `gamescope-session.service` or `steam-launcher.service`, and the journal's
  own key function refuses any other unit. A parent-scope attachment has no
  leaf unit at all: it attaches at `user@<uid>.service`.
- `FilterLifecycle` refuses any active phase whose `OwnedFilter` does not set
  `survives_owner_exit`, which is a pinned link. The parent-scope adapter
  deliberately does not pin, so that lifecycle cannot hold this attachment in
  an attached phase even if the binding were widened.

`docs/FILTER_PRIMITIVES_INTEGRATION.md` states the conclusion directly: the
legacy binding and journal model MUST NOT be treated as authorization for a
user-manager ancestor attachment, and parent-scope recovery needs a separately
reviewed contract. So this record keys on `ParentScopeAuthorization` instead,
and shares no type with the launch model.

What recovery can and cannot conclude. The link is unpinned, so an owner that
died took the filter with it: the scope is unfiltered now, whatever the record
says. That is the safe direction for the *device* and the unsafe direction for
any verdict computed while the filter was up. A `clients_clear` result, and any
removal readiness resting on it, described a moment that ended when the owner
died. Reconciliation therefore never reports a device as gated, clear, ready or
safe; it reports that an attempt was in flight and that the only defensible
next step is a fresh arm.

Nothing here is a claim that any device may be detached or unplugged. Safety
invariant 10 is untouched: releasing holders is not unplug clearance, and an
abandoned filter record is certainly not.

Pure. It attaches nothing, detaches nothing and stores nothing; storage lives
behind `hdm.ports.filter_ownership`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .filter_authorization import (
    CgroupIdentity,
    OwnerIdentity,
    ParentScopeAuthorization,
    is_finite_time,
)


FILTER_OWNERSHIP_SCHEMA_VERSION = 1


class OwnershipPhase(StrEnum):
    """How far one attempt had got when the record was last written.

    The phases exist for the audit trail, not for the recovery decision. A
    record in any of them means the same thing to recovery -- an attempt was in
    flight and may have attached -- and that is deliberate: `CLAIMED` is written
    before the attach precisely so that a crash in the gap is still visible, and
    an attach whose `ARMED` write never landed must not read as "nothing was
    attached". Recovery reads the phase to describe what happened, never to
    decide whether the scope might have been filtered.
    """

    #: Written before anything is attached, so an attach with no record is
    #: impossible and a crash in the gap leaves evidence rather than silence.
    CLAIMED = "claimed"
    #: The attach returned and its identity was recorded.
    ARMED = "armed"
    #: A deliberate release is under way. The record outlives the detach call so
    #: a crash during it is not mistaken for a completed release.
    RELEASING = "releasing"


class OwnershipRecoveryState(StrEnum):
    """What a stored record means now. None of these permits a removal."""

    #: The record is from an earlier boot, so its link cannot exist: BPF links
    #: do not survive a reboot. Nothing is attached; clear it and start over.
    DIFFERENT_BOOT = "different_boot"
    #: Same boot, and the recorded owner is gone. The unpinned link went with
    #: it, so the scope is unfiltered and anything that attempt concluded about
    #: a clear device stopped holding when the owner died.
    ABANDONED = "abandoned"
    #: Same boot, recorded owner still running, lease still live. Another
    #: instance owns this scope; a second claim is refused rather than taken.
    OWNER_LIVE = "owner_live"
    #: The recorded owner is still running but its lease has expired. A live
    #: process may still be holding the filter, so this neither clears the
    #: record nor permits a new claim: the holder must release it.
    EXPIRED_OWNER_LIVE = "expired_owner_live"
    #: The record, the clock or the observation cannot be reconciled. Fails
    #: closed: no claim, no clear, no inference about the scope.
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class AttachedFilter:
    """Kernel identity of the attachment a record names.

    The same three values `hdm.ports.device_filter.ArmedFilter` carries, held
    separately because that port imports the domain and the domain must not
    import back. Recorded for audit and for telling one attachment from
    another; it is not evidence that the link still exists, and after an owner
    dies it certainly does not.
    """

    program_id: int
    link_id: int
    cgroup_id: int

    def __post_init__(self) -> None:
        for value in (self.program_id, self.link_id, self.cgroup_id):
            if type(value) is not int or value <= 0:
                raise ValueError("attached filter identity is invalid")


@dataclass(frozen=True, slots=True)
class FilterOwnership:
    """One parent-scope filter attempt, durable across the process.

    Every field is copied from the grant that authorized the attempt rather
    than re-derived, so a record can be compared against a fresh reading
    without trusting the reader to rebuild the grant the same way.
    """

    schema_version: int
    phase: OwnershipPhase
    uid: int
    boot_hash: str
    cgroup: CgroupIdentity
    owner: OwnerIdentity
    attachment_binding: str
    generation: str
    sample_id: str
    deadline: float
    claimed_at_ns: int
    attached: AttachedFilter | None = None

    def __post_init__(self) -> None:
        if self.schema_version != FILTER_OWNERSHIP_SCHEMA_VERSION:
            raise ValueError("filter ownership schema version is unsupported")
        if type(self.phase) is not OwnershipPhase:
            raise ValueError("filter ownership phase is invalid")
        if type(self.cgroup) is not CgroupIdentity:
            raise ValueError("filter ownership cgroup is invalid")
        if type(self.owner) is not OwnerIdentity:
            raise ValueError("filter ownership owner is invalid")
        if type(self.uid) is not int or self.uid <= 0:
            raise ValueError("filter ownership uid is invalid")
        if not all(
            (self.boot_hash, self.attachment_binding, self.generation, self.sample_id)
        ):
            # Repeated from `authorize_parent_scope` because a record can be
            # rebuilt from a store without passing back through the factory,
            # and a record missing the observation it was bound to cannot say
            # which attachment the filter was armed for.
            raise ValueError("filter ownership is missing its binding evidence")
        if not is_finite_time(self.deadline) or self.deadline <= 0:
            raise ValueError("filter ownership needs a finite deadline")
        if type(self.claimed_at_ns) is not int or self.claimed_at_ns < 0:
            raise ValueError("filter ownership start time is invalid")
        if self.attached is not None and type(self.attached) is not AttachedFilter:
            raise ValueError("filter ownership attachment is invalid")
        if self.phase is OwnershipPhase.CLAIMED and self.attached is not None:
            raise ValueError("a claim does not yet name an attachment")
        if self.phase is OwnershipPhase.ARMED and self.attached is None:
            raise ValueError("an armed record names its attachment")


@dataclass(frozen=True, slots=True)
class OwnershipRecovery:
    """What to do about a stored record, and what may follow."""

    state: OwnershipRecoveryState
    code: str
    #: Whether a fresh arm may be claimed once `clear_record` is honoured. Never
    #: true while anything might still be holding the scope.
    may_rearm: bool = False
    #: Whether the caller must delete the record to finish recovering. Only set
    #: where the link provably cannot exist any more.
    clear_record: bool = False
    #: The phase the abandoned record had reached, for the audit trail.
    phase: OwnershipPhase | None = None
    #: The attachment the record named, when it had got that far.
    attached: AttachedFilter | None = None

    def __post_init__(self) -> None:
        if self.may_rearm and not self.clear_record:
            # Re-arming over a record that is still standing would leave two
            # owners recorded for one scope, and the second would overwrite the
            # evidence that the first ever existed.
            raise ValueError("a re-arm must clear the record it replaces")

    @property
    def grants_removal(self) -> bool:
        """Always false, and asserted by a test so it stays that way.

        Recovery settles a filter record. It says nothing about holders, render
        state, displays or whether a device may be detached, and a caller must
        not read any permission out of it.
        """
        return False


def claim(
    authorization: ParentScopeAuthorization, *, now_ns: int
) -> FilterOwnership:
    """Open a record for `authorization`, before anything is attached.

    Refuses an ungranted authorization: a record is the durable trace of a
    grant, and one that was never granted has nothing to trace.
    """
    if type(authorization) is not ParentScopeAuthorization:
        raise ValueError("a filter ownership claim needs an authorization")
    if (
        not authorization.granted
        or authorization.cgroup is None
        or authorization.owner is None
    ):
        raise ValueError("only an authorized grant may claim ownership")
    return FilterOwnership(
        FILTER_OWNERSHIP_SCHEMA_VERSION,
        OwnershipPhase.CLAIMED,
        authorization.uid,
        authorization.boot_hash,
        authorization.cgroup,
        authorization.owner,
        authorization.attachment_binding,
        authorization.generation,
        authorization.sample_id,
        authorization.deadline,
        now_ns,
    )


def record_attached(
    record: FilterOwnership, attached: AttachedFilter
) -> FilterOwnership:
    """Name the attachment a claim produced."""
    if type(record) is not FilterOwnership:
        raise ValueError("a filter ownership record is required")
    if record.phase is not OwnershipPhase.CLAIMED:
        raise ValueError("only a claim may record an attachment")
    if type(attached) is not AttachedFilter:
        raise ValueError("an attachment identity is required")
    return replace(record, phase=OwnershipPhase.ARMED, attached=attached)


def begin_release(record: FilterOwnership) -> FilterOwnership:
    """Mark a deliberate release as under way, before the detach is issued.

    Written from either live phase. A claim that never attached still goes
    through `RELEASING` rather than straight to deletion, because the reason a
    claim is written before the attach is that the caller cannot know whether
    the attach landed.
    """
    if type(record) is not FilterOwnership:
        raise ValueError("a filter ownership record is required")
    if record.phase is OwnershipPhase.RELEASING:
        return record
    return replace(record, phase=OwnershipPhase.RELEASING)


def reconcile(
    record: FilterOwnership,
    *,
    boot_hash: str,
    cgroup: CgroupIdentity | None,
    observed_owner_start_time: int | None,
    now: float,
) -> OwnershipRecovery:
    """Decide what a stored record means now.

    `observed_owner_start_time` is the start time read for the recorded pid
    now, or None when no such process exists. A reused pid reports a different
    start time and reads as dead, which is the safe direction: attributing a
    broad grant to a stranger's process would leave it unreleasable.

    `cgroup` is the user-manager cgroup observed now, or None when it could not
    be observed. None does not block recovering an abandoned record -- the link
    is gone either way -- but it is reported, because a scope that cannot be
    observed is not one a fresh arm should be attempted against blind.

    The order of the questions is the order of certainty. A different boot is
    decided first because it is the one case where the link provably cannot
    exist regardless of anything else on this system.
    """
    if type(record) is not FilterOwnership:
        return OwnershipRecovery(
            OwnershipRecoveryState.INVALID, "filter_ownership.record_invalid"
        )
    if not isinstance(boot_hash, str) or not boot_hash:
        # Without a current boot identity nothing below can be decided, and
        # guessing would either orphan a live filter or clear a live record.
        return OwnershipRecovery(
            OwnershipRecoveryState.INVALID,
            "filter_ownership.boot_unknown",
            phase=record.phase,
            attached=record.attached,
        )
    if not is_finite_time(now) or now < 0:
        return OwnershipRecovery(
            OwnershipRecoveryState.INVALID,
            "filter_ownership.clock_unusable",
            phase=record.phase,
            attached=record.attached,
        )
    if observed_owner_start_time is not None and (
        type(observed_owner_start_time) is not int or observed_owner_start_time <= 0
    ):
        return OwnershipRecovery(
            OwnershipRecoveryState.INVALID,
            "filter_ownership.owner_observation_invalid",
            phase=record.phase,
            attached=record.attached,
        )

    if record.boot_hash != boot_hash:
        # A BPF link does not survive a reboot, pinned or not, so this record
        # cannot describe anything currently attached.
        return OwnershipRecovery(
            OwnershipRecoveryState.DIFFERENT_BOOT,
            "filter_ownership.different_boot",
            may_rearm=True,
            clear_record=True,
            phase=record.phase,
            attached=record.attached,
        )

    if observed_owner_start_time == record.owner.start_time:
        if now >= record.deadline:
            # The lease is the guard against a stalled owner holding a broad
            # scope indefinitely, and it has done its job: no new claim. It is
            # not licence to clear the record, because the process that may
            # still be enforcing the filter is alive and this is not its
            # decision to take.
            return OwnershipRecovery(
                OwnershipRecoveryState.EXPIRED_OWNER_LIVE,
                "filter_ownership.lease_expired_owner_live",
                phase=record.phase,
                attached=record.attached,
            )
        return OwnershipRecovery(
            OwnershipRecoveryState.OWNER_LIVE,
            "filter_ownership.owner_live",
            phase=record.phase,
            attached=record.attached,
        )

    # The owner is gone. The link was never pinned, so it went with it: the
    # scope is unfiltered now whatever phase the record reached.
    if cgroup is None:
        return OwnershipRecovery(
            OwnershipRecoveryState.ABANDONED,
            "filter_ownership.abandoned_scope_unobserved",
            clear_record=True,
            phase=record.phase,
            attached=record.attached,
        )
    if type(cgroup) is not CgroupIdentity:
        return OwnershipRecovery(
            OwnershipRecoveryState.INVALID,
            "filter_ownership.cgroup_observation_invalid",
            phase=record.phase,
            attached=record.attached,
        )
    if (cgroup.path, cgroup.device, cgroup.inode) != (
        record.cgroup.path,
        record.cgroup.device,
        record.cgroup.inode,
    ):
        # The manager cgroup was recreated since the claim. Recovery is the
        # same -- the record is finished with -- but a fresh grant has to be
        # taken over the cgroup that exists now, which is what clearing forces.
        return OwnershipRecovery(
            OwnershipRecoveryState.ABANDONED,
            "filter_ownership.abandoned_scope_replaced",
            may_rearm=True,
            clear_record=True,
            phase=record.phase,
            attached=record.attached,
        )
    return OwnershipRecovery(
        OwnershipRecoveryState.ABANDONED,
        "filter_ownership.abandoned",
        may_rearm=True,
        clear_record=True,
        phase=record.phase,
        attached=record.attached,
    )
