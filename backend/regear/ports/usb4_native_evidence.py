"""Private observation seam only. No installed API, grant or capability is defined.

A future reviewed reader must use non-activating native reads, honor the deadline
and account for all bytes/objects. Limits are cooperative: this seam cannot stop
an injected reader that blocks. Nothing here is a public RPC input or payload.
"""
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class Fact(StrEnum):
    UNKNOWN = "unknown"
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"
    DENIED = "denied"
    UNSUPPORTED = "unsupported"
    STALE = "stale"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class ReadLimits:
    seconds: float = 30.0
    max_age: float = 2.0
    max_bytes: int = 65536
    max_objects: int = 64


@dataclass(frozen=True)
class ReadBudget:
    deadline: float
    max_bytes: int
    max_objects: int


@dataclass(frozen=True, repr=False)
class AttachmentEvidence:
    binding: str
    generation: int
    fresh: bool = False
    authorization_requested: bool | None = None
    authorized: bool | None = None
    authorization_binding: str | None = None
    authorization_generation: int | None = None
    enrolled: bool | None = None
    enrollment_binding: str | None = None
    enrollment_generation: int | None = None
    gpu_present: bool | None = None


@dataclass(frozen=True)
class NativeSnapshot:
    captured_at: float
    api: Fact = Fact.UNKNOWN
    plugin_context: Fact = Fact.UNKNOWN
    static_permission: Fact = Fact.UNKNOWN
    enrollment_store: Fact = Fact.UNKNOWN
    attachment_state: Fact = Fact.UNKNOWN
    attachment: AttachmentEvidence | None = field(default=None, repr=False)
    bytes_read: int = 0
    objects_read: int = 0


class NativeEvidenceReader(Protocol):
    def service_owner(self, budget: ReadBudget) -> str | None:
        """Read existing native owner, without starting a service; None if absent."""
        ...

    def observe(self, owner: str, budget: ReadBudget) -> NativeSnapshot:
        """Read only from that exact owner; never request interactive permission."""
        ...
