"""Pure, private fixture contracts. These are not installed setter identifiers."""

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
import re


class Manager(StrEnum):
    REGEAR = "regear"
    OS = "os"
    OTHER = "other"
    UNKNOWN = "unknown"


class Phase(StrEnum):
    STAGED = "staged"
    REQUESTED = "requested"
    EFFECTIVE = "effective"
    RESTORE_REQUESTED = "restore_requested"
    RESTORED = "restored"
    RECOVERY_REQUIRED = "recovery_required"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class Authority:
    manager: Manager
    evidence: str


@dataclass(frozen=True, slots=True)
class TargetType:
    identifier: str
    gamepad: bool

    def __post_init__(self):
        if (type(self.identifier) is not str
                or re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,63}", self.identifier) is None
                or type(self.gamepad) is not bool):
            raise ValueError("requires a verified categorical setter ID and kind")


@dataclass(frozen=True, slots=True)
class Frame:
    epoch: str
    composite: str
    generation: int
    authority: Authority
    targets: tuple[str, ...]
    supported: tuple[TargetType, ...]
    compatible: tuple[str, ...]
    complete: bool
    identity_verified: bool
    visible: bool
    idle: bool
    observed_at: float

    @property
    def binding(self):
        return self.epoch, self.composite, self.generation, self.authority


@dataclass(frozen=True, slots=True)
class Request:
    """Private immutable plan; only the minting session may dispatch this object."""

    frame: Frame
    original: tuple[str, ...]
    desired: tuple[str, ...]
    started: float
    deadline: float
    restoring: bool = False


def timestamp(value: object) -> float:
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError("invalid clock evidence")
    return float(value)


def catalogue(types: tuple[TargetType, ...]) -> dict[str, bool]:
    if type(types) is not tuple or not 1 <= len(types) <= 64:
        raise ValueError("incomplete or oversized type evidence")
    result = {}
    for target in types:
        if type(target) is not TargetType or target.identifier in result:
            raise ValueError("duplicate or conflicting type evidence")
        result[target.identifier] = target.gamepad
    return result


def admitted(frame: Frame, now: float, reviewed: tuple[TargetType, ...]) -> dict[str, bool]:
    """Require explicit authority; provider access and process absence prove none."""
    now = timestamp(now)
    if type(frame) is not Frame:
        raise ValueError("missing verified frame")
    if (frame.complete is not True or frame.identity_verified is not True
            or frame.visible is not True or frame.idle is not True
            or type(frame.epoch) is not str or not frame.epoch
            or type(frame.composite) is not str or not frame.composite
            or type(frame.generation) is not int or frame.generation < 0
            or type(frame.authority) is not Authority
            or frame.authority.manager is not Manager.REGEAR
            or type(frame.authority.evidence) is not str or not frame.authority.evidence
            or not 0 <= now - timestamp(frame.observed_at) < 10):
        raise ValueError("inadmissible identity, authority, visibility, idle or freshness")
    supported = catalogue(frame.supported)
    allowed = catalogue(reviewed)
    if (type(frame.targets) is not tuple or not 1 <= len(frame.targets) <= 64
            or any(type(t) is not str or t not in supported for t in frame.targets)
            or sum(supported[t] for t in frame.targets) != 1):
        raise ValueError("baseline must contain exactly one verified gamepad slot")
    if (type(frame.compatible) is not tuple or len(frame.compatible) > 64
            or any(type(t) is not str or t not in supported for t in frame.compatible)
            or len(set(frame.compatible)) != len(frame.compatible)
            or any(allowed[t] != supported[t] for t in allowed.keys() & supported.keys())):
        raise ValueError("conflicting compatibility or kind evidence")
    return {t: kind for t, kind in supported.items()
            if kind and allowed.get(t) is True and t in frame.compatible}


def replacement(frame: Frame, target: str) -> tuple[str, ...]:
    kinds = catalogue(frame.supported)
    return tuple(target if kinds[t] else t for t in frame.targets)
