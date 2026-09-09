"""Port for arming and disarming a cgroup device filter.

`hdm.delivery.device_filter_kernel` supplies the syscall primitives. This port
is the shape an application service depends on, so the sequencing can be tested
without loading a BPF program or holding a real cgroup descriptor.

Enforcement is a separate question from attachment. `attach` returning without
error means the kernel accepted a link, not that the program is the one now
deciding opens on that cgroup, so a caller must be able to ask.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ..domain.filter_authorization import CgroupIdentity


class ArmOutcome(StrEnum):
    ARMED = "armed"
    LOAD_FAILED = "load_failed"
    ATTACH_FAILED = "attach_failed"
    REFUSED = "refused"


class DisarmOutcome(StrEnum):
    DISARMED = "disarmed"
    NOT_ARMED = "not_armed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ArmedFilter:
    """Identity of a live attachment, sufficient to confirm it is still ours."""

    program_id: int
    link_id: int
    cgroup_id: int

    def __post_init__(self) -> None:
        for value in (self.program_id, self.link_id, self.cgroup_id):
            if type(value) is not int or value <= 0:
                raise ValueError("armed filter identity is invalid")


@dataclass(frozen=True, slots=True)
class ArmResult:
    outcome: ArmOutcome
    filter: ArmedFilter | None = None
    code: str = ""

    def __post_init__(self) -> None:
        if self.outcome is ArmOutcome.ARMED and self.filter is None:
            raise ValueError("an armed result needs a filter identity")
        if self.outcome is not ArmOutcome.ARMED and self.filter is not None:
            raise ValueError("only an armed result exposes a filter identity")

    @property
    def ok(self) -> bool:
        return self.outcome is ArmOutcome.ARMED


@dataclass(frozen=True, slots=True)
class DisarmResult:
    outcome: DisarmOutcome
    code: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is DisarmOutcome.DISARMED


class DeviceFilterPort(Protocol):
    """Arm an exact program on an authorized cgroup, and take it away again."""

    def arm(self, program: bytes, cgroup: CgroupIdentity) -> ArmResult:
        """Load `program` and attach it to `cgroup`."""

    def enforced(self, cgroup: CgroupIdentity, program_id: int) -> bool:
        """Report whether `program_id` is attached to `cgroup` right now."""

    def disarm(self) -> DisarmResult:
        """Detach whatever this port armed, if anything."""
