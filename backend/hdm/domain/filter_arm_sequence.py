"""Pure composition of the units a device filter must restart to take effect.

A cgroup device program decides `open()`. It never touches a descriptor that is
already open — `hdm.delivery.device_filter_program` says so in its own
docstring. So attaching a policy changes nothing for a process that never
reopens the device, however correct the policy and attach point are.

Supervised measurement on an Ally X with a GPD G1 attached, filter compiled from
the exact device set and attached at `user@1000.service`:

- Restarting `gamescope-session.target` alone took three holders down to one.
  `wireplumber` kept `audio_control`. It had started at boot and never
  restarted, so it still held the descriptor it opened before the filter
  existed. `wireplumber.service` is not a dependency of that target; only the
  pipewire sockets are.
- Restarting the audio units as well released every holder, and the readiness
  probe reached `ready_for_supervised_removal`.

An earlier permission-based experiment cleared the same holders *without*
restarting the audio units, which made this requirement invisible. `chmod`
emits a udev change event and WirePlumber, which watches udev for ALSA devices,
re-evaluated on its own. A cgroup filter is silent to userspace, so it gets no
such help. Evidence from permission experiments must not be used to conclude
that holders will release on their own.

This module composes the restart set from observed holders rather than assuming
a fixed list, so a holder appearing in a unit nobody anticipated is still
covered. Pure: no I/O, no service action, no removal claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


#: Units observed to hold eGPU devices on the tested profile. Present as a
#: cross-check against an observation that finds fewer, not as the source of
#: truth: `compose_restart_sequence` works from what was actually observed.
KNOWN_HOLDER_UNITS: frozenset[str] = frozenset(
    {
        "gamescope-session.service",
        "steam-launcher.service",
        "wireplumber.service",
        "pipewire.service",
        "gamescope-mangoapp.service",
    }
)

#: Units that hold eGPU devices but are not reached by restarting
#: `gamescope-session.target`. Restarting the session alone leaves these
#: running with descriptors opened before the filter was attached.
UNREACHED_BY_SESSION_RESTART: frozenset[str] = frozenset(
    {"wireplumber.service", "pipewire.service"}
)

#: Restarting a target does not restart units that merely socket-activate from
#: it, which is how the audio units escaped the first measured attempt.
SESSION_TARGET = "gamescope-session.target"


class ArmSequenceState(StrEnum):
    COMPOSED = "composed"
    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ArmRestartSequence:
    """The units to restart, ordered, so an attached policy actually applies."""

    state: ArmSequenceState
    code: str
    units: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.state is ArmSequenceState.COMPOSED:
            if not self.units:
                raise ValueError("a composed restart sequence needs units")
        elif self.units:
            raise ValueError("only a composed restart sequence exposes units")

    @property
    def usable(self) -> bool:
        return self.state is ArmSequenceState.COMPOSED


def compose_restart_sequence(holder_units: tuple[str, ...]) -> ArmRestartSequence:
    """Return the units to restart so every holder reopens under the filter.

    Every unit owning a holder must restart, because the filter cannot revoke a
    descriptor that unit's processes already hold. The session target is placed
    last so the player-visible restart happens once, after the background
    services have already reopened.
    """
    if type(holder_units) is not tuple:
        return ArmRestartSequence(
            ArmSequenceState.INVALID, "arm_sequence.holder_units_invalid"
        )
    if any(type(unit) is not str or not unit for unit in holder_units):
        return ArmRestartSequence(
            ArmSequenceState.INVALID, "arm_sequence.holder_units_invalid"
        )
    if not holder_units:
        # No observed holders is not the same as nothing to restart: it means
        # the scan found nothing, and arming on that basis would be unfounded.
        return ArmRestartSequence(
            ArmSequenceState.EVIDENCE_INCOMPLETE, "arm_sequence.no_holders_observed"
        )

    services = sorted({unit for unit in holder_units if unit != SESSION_TARGET})
    ordered = (*services, SESSION_TARGET)
    return ArmRestartSequence(ArmSequenceState.COMPOSED, "arm_sequence.composed", ordered)


def units_missed_by_session_restart(
    holder_units: tuple[str, ...],
) -> tuple[str, ...]:
    """Return observed holder units a session-target restart would not reach.

    Naming these explicitly is the difference between the measured failure and
    the measured success, so it is worth reporting rather than inferring.
    """
    return tuple(
        sorted(set(holder_units) & UNREACHED_BY_SESSION_RESTART)
    )
