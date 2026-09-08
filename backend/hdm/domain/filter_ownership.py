"""Durable ownership of an attached eGPU device filter, and its reconciliation.

The device filter is what makes `clients_clear` true. It gates `open()` on the
eGPU's nodes, and the moment its link goes, the session reopens them. The link
`hdm.delivery.device_filter_kernel` creates is unpinned: it exists only while
the process holding it lives.

For a supervised operator run that is the right shape -- a crash releases the
filter, which is the safe direction. It is not usable for anything a player
touches, because the release is *silent*. Nothing records that a filter was
ever attached, so a later reader cannot tell "no filter was armed" apart from
"a filter was armed and vanished mid-operation". A durable claim that the eGPU
is released, resting on a link that may have disappeared, is the same fail-open
shape that `hdm.egpu_release`'s holder scan used to have: an unanswered question
reported as a clear device.

This module is the record and its lifecycle, and nothing else. It performs no
I/O and attaches nothing; storage lives behind `hdm.ports.filter_ownership`,
following the separation `hdm.domain.transition_journal` uses, so writing or
replaying a record cannot touch the live system.

What it deliberately does not decide:

- Whether recovery should re-adopt a surviving filter or always require a fresh
  arm. The record makes either possible; choosing is a later decision.
- What happens to a removal that was already in progress. A process that died
  after detaching one PCI function left a half-attached device, which has a
  different lifetime and a different recovery action from a filter lease, and
  belongs in its own record.

Nothing here is a claim that any device is safe to unplug.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


#: Opaque, privacy-safe identifiers, matching the journal contracts' shape.
#: `+` is included because a device set names both PCI functions of one
#: multi-function eGPU, and `/` because a cgroup path is one.
SAFE_TOKEN = re.compile(r"^[a-zA-Z0-9_.:@/+-]{1,192}$")

OWNERSHIP_SCHEMA_VERSION = 1


class FilterOwnershipState(StrEnum):
    #: Recorded before attaching, so a crash between record and attach is
    #: visible rather than indistinguishable from never having started.
    CLAIMED = "claimed"
    #: The filter is attached and was verified as enforced.
    ARMED = "armed"
    #: Deliberately ended by its owner. Terminal.
    RELEASED = "released"


class ReconciliationState(StrEnum):
    #: The record and the observed attachment agree, within the lease.
    ENFORCED = "enforced"
    #: Recorded as armed, but no matching program is attached. The system is
    #: unfiltered while the record says otherwise.
    ORPHANED = "orphaned"
    #: Claimed but never armed, and the claim has aged out.
    EXPIRED = "expired"
    #: Recorded as claimed, within the lease, nothing attached yet.
    PENDING = "pending"
    #: The owner ended it deliberately.
    RELEASED = "released"
    #: The record cannot be trusted to describe anything.
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class FilterOwnership:
    """One owner's durable claim on an attached filter.

    `program_id` is the kernel's id for the loaded program, and is what makes
    reconciliation possible: a filter attached by some other owner is not this
    record's filter, and must not satisfy it.
    """

    schema_version: int
    owner_id: str
    cgroup_path: str
    device_set: str
    state: FilterOwnershipState
    claimed_at_ns: int
    expires_at_ns: int
    program_id: int = 0

    def __post_init__(self) -> None:
        if self.schema_version != OWNERSHIP_SCHEMA_VERSION:
            raise ValueError("filter ownership schema version is unsupported")
        for value in (self.owner_id, self.cgroup_path, self.device_set):
            if not SAFE_TOKEN.fullmatch(value):
                raise ValueError("filter ownership identifiers must be safe tokens")
        if self.claimed_at_ns < 0 or self.expires_at_ns <= self.claimed_at_ns:
            raise ValueError("a filter ownership lease must expire after it begins")
        if self.program_id < 0:
            raise ValueError("a program id cannot be negative")
        if self.state is FilterOwnershipState.ARMED and not self.program_id:
            # An armed record without a program id can never be reconciled:
            # there is nothing to match against what the kernel reports.
            raise ValueError("an armed filter ownership record needs a program id")

    @property
    def expired_at(self) -> int:
        return self.expires_at_ns


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """What a record and a fresh observation say when read together."""

    state: ReconciliationState
    code: str

    @property
    def gated(self) -> bool:
        """Whether the eGPU is demonstrably gated by this owner's filter now.

        Only one state says yes. Everything else -- orphaned, expired, pending,
        released, invalid -- means the guarantee does not currently hold, and a
        caller must treat the device as reachable by its holders again.
        """
        return self.state is ReconciliationState.ENFORCED

    @property
    def lapsed(self) -> bool:
        """Whether a guarantee this record once made has since been lost.

        Distinct from simply not being gated. A pending claim never made the
        guarantee, and a released one ended it on purpose; an orphaned record
        means the filter went away without its owner ending it, which is the
        crash case and the reason this module exists.
        """
        return self.state is ReconciliationState.ORPHANED


def reconcile(
    record: FilterOwnership | None,
    *,
    attached_program_ids: tuple[int, ...],
    now_ns: int,
) -> Reconciliation:
    """Read a durable record against what the kernel currently reports.

    `attached_program_ids` are the programs attached to the cgroup the record
    names, read fresh. The record alone proves nothing: it describes an
    intention that may no longer hold, which is the whole point of reconciling.

    Expiry is checked before attachment for a claim, and after it for an armed
    record. A filter that is still attached and enforcing is still enforcing
    whatever the lease says, and reporting an enforced filter as expired would
    tell a caller the device is reachable when it is not -- the dangerous
    direction. An expired armed record is instead reported as enforced, so the
    caller renews or releases deliberately rather than being told a comforting
    falsehood.
    """
    if record is None:
        return Reconciliation(
            ReconciliationState.INVALID, "filter_ownership.no_record"
        )
    if type(record) is not FilterOwnership or type(attached_program_ids) is not tuple:
        return Reconciliation(
            ReconciliationState.INVALID, "filter_ownership.input_invalid"
        )
    if any(type(item) is not int for item in attached_program_ids):
        return Reconciliation(
            ReconciliationState.INVALID, "filter_ownership.input_invalid"
        )

    if record.state is FilterOwnershipState.RELEASED:
        return Reconciliation(
            ReconciliationState.RELEASED, "filter_ownership.released"
        )

    if record.state is FilterOwnershipState.CLAIMED:
        if now_ns >= record.expires_at_ns:
            return Reconciliation(
                ReconciliationState.EXPIRED, "filter_ownership.claim_expired"
            )
        return Reconciliation(
            ReconciliationState.PENDING, "filter_ownership.claim_pending"
        )

    # Armed. The only question that matters is whether this owner's program is
    # still attached; someone else's filter on the same cgroup is not this
    # record's guarantee and must not satisfy it.
    if record.program_id in attached_program_ids:
        return Reconciliation(
            ReconciliationState.ENFORCED, "filter_ownership.enforced"
        )
    return Reconciliation(
        ReconciliationState.ORPHANED, "filter_ownership.armed_but_absent"
    )


def claim(
    *,
    owner_id: str,
    cgroup_path: str,
    device_set: str,
    now_ns: int,
    lease_ns: int,
) -> FilterOwnership:
    """Record the intention to arm, before anything is attached.

    Written first on purpose. A crash between recording and attaching leaves a
    claim that reconciles as pending or expired, which is recoverable; the
    reverse order would attach a filter no record mentions.
    """
    return FilterOwnership(
        OWNERSHIP_SCHEMA_VERSION,
        owner_id,
        cgroup_path,
        device_set,
        FilterOwnershipState.CLAIMED,
        now_ns,
        now_ns + max(1, lease_ns),
    )


def arm(record: FilterOwnership, *, program_id: int) -> FilterOwnership:
    """Record that the filter is attached and was verified as enforced.

    Only a claim may be armed. Arming a released record would resurrect a
    guarantee its owner deliberately ended.
    """
    if record.state is not FilterOwnershipState.CLAIMED:
        raise ValueError("only a claimed filter ownership record can be armed")
    if not program_id:
        raise ValueError("arming needs the program id the kernel reported")
    return FilterOwnership(
        record.schema_version,
        record.owner_id,
        record.cgroup_path,
        record.device_set,
        FilterOwnershipState.ARMED,
        record.claimed_at_ns,
        record.expires_at_ns,
        program_id,
    )


def release(record: FilterOwnership) -> FilterOwnership:
    """Record a deliberate end, so a later reader does not read a crash."""
    return FilterOwnership(
        record.schema_version,
        record.owner_id,
        record.cgroup_path,
        record.device_set,
        FilterOwnershipState.RELEASED,
        record.claimed_at_ns,
        record.expires_at_ns,
        record.program_id,
    )
