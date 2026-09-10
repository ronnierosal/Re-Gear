"""Audio recovery serialization contract for the supervised transition owner."""
from typing import ContextManager, Protocol


class AudioRecoveryBlocked(RuntimeError):
    """Audio journal or restoration cannot authorize a presentation operation."""


class AudioRecoveryPort(Protocol):
    def transition_guard(self, *, recover: bool = False) -> ContextManager[None]: ...
    def recovery_status(self) -> str: ...
