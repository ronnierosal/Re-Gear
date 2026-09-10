"""Pure experimental launch-filter contract; not a store or runtime integration.

Evidence is supplied by a future trusted adapter. Callers must persist and
serialize transitions: retaining an older immutable value does not provide
replay protection. No result grants resource release or disconnect clearance.
"""
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import math
import re


class PairedStage(Enum):
    RETENTION_INTENT = 'retention_intent'
    RETENTION_CONFIRMED = 'retention_confirmed'
    RECEIVE_INTENT = 'receive_intent'
    RECEIVE_CONFIRMED = 'receive_confirmed'
    RECEIVE_RELEASE_PENDING = 'receive_release_pending'
    RECEIVE_RELEASED = 'receive_released'
    RETENTION_RELEASE_PENDING = 'retention_release_pending'
    COMPLETE = 'complete'


class DirectCleanupStage(Enum):
    DETACHED_VERIFIED = 'detached_verified'
    COMPLETE = 'complete'


@dataclass(frozen=True)
class PairedReceiveIdentity:
    link_id: int
    program_id: int
    hook_btf_id: int
    target_obj_id: int

    def __post_init__(self):
        if any(type(value) is not int or not 0 < value < 2**32 for value in
               (self.link_id,self.program_id,self.hook_btf_id,self.target_obj_id)):
            raise ValueError('invalid paired receive identity')


@dataclass(frozen=True)
class PairedOwnership:
    map_id: int
    stage: PairedStage
    receive: PairedReceiveIdentity | None = None

    def __post_init__(self):
        if (type(self.map_id) is not int or not 0 < self.map_id < 2**32
                or type(self.stage) is not PairedStage
                or (self.receive is not None and type(self.receive) is not PairedReceiveIdentity)):
            raise ValueError('invalid paired ownership')
        if self.stage in (PairedStage.RETENTION_INTENT,PairedStage.RETENTION_CONFIRMED) and self.receive is not None:
            raise ValueError('premature receive identity')
        if self.stage not in (PairedStage.RETENTION_INTENT,PairedStage.RETENTION_CONFIRMED) and self.receive is None:
            raise ValueError('receive identity required')

    def advance(self, action, **evidence):
        transitions = {
            'retention_confirmed':({PairedStage.RETENTION_INTENT},PairedStage.RETENTION_CONFIRMED),
            'receive_intent':({PairedStage.RETENTION_CONFIRMED},PairedStage.RECEIVE_INTENT),
            'receive_confirmed':({PairedStage.RECEIVE_INTENT},PairedStage.RECEIVE_CONFIRMED),
            'receive_release_pending':({PairedStage.RECEIVE_INTENT,PairedStage.RECEIVE_CONFIRMED},PairedStage.RECEIVE_RELEASE_PENDING),
            'receive_released':({PairedStage.RECEIVE_RELEASE_PENDING},PairedStage.RECEIVE_RELEASED),
            'retention_release_pending':({PairedStage.RECEIVE_RELEASED},PairedStage.RETENTION_RELEASE_PENDING),
            'paired_complete':({PairedStage.RETENTION_RELEASE_PENDING},PairedStage.COMPLETE)}
        if action not in transitions or self.stage not in transitions[action][0]:
            raise ValueError('unordered paired transition')
        if set(evidence) != ({'receive'} if action=='receive_intent' else set()):
            raise ValueError('unexpected paired evidence')
        return replace(self,stage=transitions[action][1],receive=evidence.get('receive',self.receive))


def paired_token(binding, role):
    if type(binding) is not LaunchBinding or role not in ('retention','receive'):
        raise ValueError('exact paired token binding required')
    return hashlib.sha256('\0'.join((binding.boot_hash,binding.operation,binding.unit,
                                     binding.invocation,role)).encode('ascii')).hexdigest()


def _positive(value):
    return type(value) is int and value > 0


def _time(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


@dataclass(frozen=True)
class LaunchBinding:
    boot_hash: str
    operation: str
    unit: str
    invocation: str
    uid: int
    pid: int
    starttime: int
    cgroup_dev: int
    cgroup_inode: int
    topology_hash: str
    deadline: float

    def __post_init__(self):
        for value in (self.boot_hash, self.topology_hash):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("invalid binding hash")
        if not isinstance(self.operation, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", self.operation):
            raise ValueError("invalid operation")
        if self.unit not in ("gamescope-session.service", "steam-launcher.service"):
            raise ValueError("unapproved unit")
        if not isinstance(self.invocation, str) or not re.fullmatch(r"[0-9a-f]{32}", self.invocation):
            raise ValueError("invalid invocation")
        if not all(_positive(value) for value in (self.uid, self.pid, self.starttime, self.cgroup_inode)):
            raise ValueError("invalid process or cgroup identity")
        if type(self.cgroup_dev) is not int or self.cgroup_dev < 0:
            raise ValueError("invalid cgroup device")
        if not _time(self.deadline) or self.deadline <= 0:
            raise ValueError("invalid monotonic deadline")


@dataclass(frozen=True)
class OwnedFilter:
    program_id: int
    program_hash: str
    ownership_verified: bool
    survives_owner_exit: bool
    link_id: int
    kernel_cgroup_id: int

    def __post_init__(self):
        if not _positive(self.program_id) or self.program_id >= 2**32 or not isinstance(self.program_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", self.program_hash):
            raise ValueError("invalid owned program identity")
        if (not _positive(self.link_id) or self.link_id >= 2**32
                or not _positive(self.kernel_cgroup_id) or self.kernel_cgroup_id >= 2**64):
            raise ValueError("invalid owned link identity")
        if type(self.ownership_verified) is not bool or type(self.survives_owner_exit) is not bool:
            raise ValueError("invalid ownership evidence")


class Phase(Enum):
    REQUESTED = "requested"
    PIN_PENDING = "pin_pending"
    ATTACHED = "attached"
    GRANTED = "granted"
    CANCELLED = "cancelled"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True)
class FilterLifecycle:
    binding: LaunchBinding
    phase: Phase = Phase.REQUESTED
    owned: OwnedFilter | None = None

    def __post_init__(self):
        # Journal reconstruction must not bypass transition preconditions.
        if type(self.binding) is not LaunchBinding or type(self.phase) is not Phase:
            raise ValueError("invalid lifecycle identity or phase")
        if self.owned is not None and type(self.owned) is not OwnedFilter:
            raise ValueError("invalid lifecycle owner")
        if self.phase is Phase.REQUESTED and self.owned is not None:
            raise ValueError("request cannot already own an attachment")
        if self.phase is Phase.PIN_PENDING:
            if (self.owned is None or self.owned.ownership_verified is not True
                    or self.owned.survives_owner_exit is not False):
                raise ValueError("pending pin requires verified ephemeral ownership")
        if self.phase in (Phase.ATTACHED, Phase.GRANTED, Phase.RECOVERY_REQUIRED):
            if (self.owned is None or self.owned.ownership_verified is not True
                    or self.owned.survives_owner_exit is not True):
                raise ValueError("active lifecycle requires recoverable ownership")

    @property
    def owned_detach_allowed(self):
        return (self.phase is Phase.CANCELLED and self.owned is not None
                and self.owned.ownership_verified is True)

    def cancel(self):
        if self.phase in (Phase.GRANTED, Phase.RECOVERY_REQUIRED):
            return replace(self, phase=Phase.RECOVERY_REQUIRED)
        return replace(self, phase=Phase.CANCELLED)

    def revalidate(self, observed, *, now):
        if not _time(now) or now >= self.binding.deadline or observed != self.binding:
            return self.cancel()
        return self

    def prepare_pin(self, owned, *, observed, now):
        if self.phase is not Phase.REQUESTED:
            raise ValueError("pin preparation cannot replay")
        if type(owned) is not OwnedFilter:
            raise ValueError("owned filter evidence required")
        candidate = self.revalidate(observed, now=now)
        if (candidate.phase is Phase.CANCELLED or owned.ownership_verified is not True
                or owned.survives_owner_exit is not False):
            return replace(candidate, phase=Phase.CANCELLED, owned=owned)
        return replace(candidate, phase=Phase.PIN_PENDING, owned=owned)

    def confirm_pin(self, owned, *, observed, now):
        if self.phase is not Phase.PIN_PENDING:
            raise ValueError("pin confirmation requires pending ownership")
        if type(owned) is not OwnedFilter:
            raise ValueError("owned filter evidence required")
        candidate = self.revalidate(observed, now=now)
        if (candidate.phase is Phase.CANCELLED
                or owned != replace(self.owned, survives_owner_exit=True)):
            # Foreign confirmation must not replace the owner retained for cleanup.
            return candidate.cancel()
        return replace(candidate, phase=Phase.ATTACHED, owned=owned)

    def attach(self, owned, *, observed, now):
        """Compatibility name, with no bypass of the durable pin-pending phase."""
        return self.confirm_pin(owned, observed=observed, now=now)

    def grant(self, *, observed, now, no_game, inherited_scan_complete,
              inherited_descriptors_free):
        if self.phase is not Phase.ATTACHED:
            raise ValueError("grant requires an unconsumed attachment")
        candidate = self.revalidate(observed, now=now)
        if (candidate.phase is not Phase.ATTACHED or self.owned is None
                or self.owned.ownership_verified is not True
                or self.owned.survives_owner_exit is not True
                or any(value is not True for value in
                       (no_game, inherited_scan_complete, inherited_descriptors_free))):
            return candidate.cancel()
        return replace(candidate, phase=Phase.GRANTED)

    def after_crash(self):
        """Never resume a grant from recovered state without coordinated recovery."""
        return self.cancel()
