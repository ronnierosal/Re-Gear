"""Redacted player checkpoint for an interrupted canonical sleep request.

This is a projection of the existing owner-checked sleep journal result.  It
does not inspect a journal, start recovery, or authorize sleep.  In particular,
it intentionally makes no claim about why a game/session stopped.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .canonical_sleep import CanonicalSleepStatus


class SleepRecoveryCheckpointKind(StrEnum):
    NONE = "none"
    PORTABLE_VERIFIED = "portable_verified"
    ACTION_REQUIRED = "action_required"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class SleepRecoveryCheckpoint:
    kind: SleepRecoveryCheckpointKind
    code: str = ""
    acknowledgement_required: bool = False


_ACTION_REQUIRED_CODES = frozenset(
    {
        "sleep.restart_action_required",
        "sleep.restart_before_action",
        "sleep.foreign_journal",
    }
)
_UNAVAILABLE_CODES = frozenset(
    {
        "sleep.journal_unavailable",
        "sleep.recovery_observation_unavailable",
        "sleep.recovery_persist_failed",
    }
)


def project_sleep_recovery_checkpoint(
    status: CanonicalSleepStatus,
) -> SleepRecoveryCheckpoint:
    """Expose only an acknowledged terminal restart outcome.

    A stale/incomplete journal, unrelated completed sleep request, or a status
    without an acknowledgement remains invisible to this player notification
    surface.  That prevents a fresh UI instance from inventing a historical
    incident or treating ordinary sleep completion as recovery.
    """
    if not status.acknowledgement_required:
        return SleepRecoveryCheckpoint(SleepRecoveryCheckpointKind.NONE)
    if status.code == "sleep.restart_portable_verified":
        return SleepRecoveryCheckpoint(
            SleepRecoveryCheckpointKind.PORTABLE_VERIFIED,
            status.code,
            acknowledgement_required=True,
        )
    if status.code in _ACTION_REQUIRED_CODES:
        return SleepRecoveryCheckpoint(
            SleepRecoveryCheckpointKind.ACTION_REQUIRED,
            status.code,
            acknowledgement_required=True,
        )
    if status.code in _UNAVAILABLE_CODES:
        return SleepRecoveryCheckpoint(
            SleepRecoveryCheckpointKind.UNAVAILABLE,
            status.code,
            acknowledgement_required=True,
        )
    return SleepRecoveryCheckpoint(SleepRecoveryCheckpointKind.NONE)
