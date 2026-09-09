"""Pure composition of an approved restart plan for arming a device filter.

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

Observing that a service holds a device does NOT authorise restarting it.
Restarting an unrecognised service is the same class of action as force-closing
an unrecognised process, which safety invariant 17 forbids. So the approved set
here is an allowlist, not a hint: a holder outside it blocks the plan and is
reported, rather than being swept into a restart sequence. Membership requires
someone to have established both that restarting the unit is acceptable and
whether the session target already reaches it.

An earlier permission-based experiment cleared the same holders *without*
restarting the audio units, which made this requirement invisible. What was
observed is only that: denying by permission released `wireplumber` without a
restart, and denying by cgroup filter did not. The mechanism behind that
difference has not been established — a plausible explanation is that changing
the node's mode produces a udev event WirePlumber reacts to, while a cgroup
program is silent to userspace, but that has not been verified and should not
be relied on.

The conclusion does not depend on the explanation: permission experiments
released a holder the filter did not, so their results must not be read as
evidence about how holders behave under the filter.

Membership in the approved sets is evidence from one tested profile. A service
name alone does not establish identical restart behaviour across installations,
so an integrator must re-verify holders after executing a plan rather than
treating a composed plan as proof that the device was cleared. The hardware runs
behind this module re-probed after every restart for that reason.

Pure: no I/O, no service action, no removal claim. Composing a plan authorises
nothing on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


#: The target whose restart rebuilds the player-visible session.
SESSION_TARGET = "gamescope-session.target"

#: Approved holder units that a `SESSION_TARGET` restart already reaches, so
#: they need no separate restart. Membership is evidence, not inference: on the
#: tested profile every unit here recorded an identical `ActiveEnterTimestamp`
#: of 19:13:21 immediately after the target was restarted, while the audio units
#: showed 19:13:16 from their own separate restarts five seconds earlier.
#:
#: `galileo-mura-setup.service` is wanted by the target but was inactive
#: throughout, so no restart evidence exists for it and it is deliberately
#: absent.
APPROVED_SESSION_REACHED: frozenset[str] = frozenset(
    {
        "gamescope-session.service",
        "steam-launcher.service",
        "gamescope-mangoapp.service",
        "gamescope-xbindkeys.service",
        "ibus-gamescope.service",
        "steam-notif-daemon.service",
    }
)

#: Approved holder units the session target does NOT reach, in the order the
#: successful hardware run restarted them. The order is recorded rather than
#: derived: nothing here establishes a dependency ordering, so reproducing the
#: sequence that was measured is the only defensible choice.
APPROVED_EXPLICIT_RESTARTS: tuple[str, ...] = (
    "wireplumber.service",
    "pipewire.service",
)

#: Every unit an arm plan may act on.
APPROVED_HOLDER_UNITS: frozenset[str] = (
    APPROVED_SESSION_REACHED | frozenset(APPROVED_EXPLICIT_RESTARTS)
)


class ArmSequenceState(StrEnum):
    COMPOSED = "composed"
    BLOCKED_UNAPPROVED_HOLDER = "blocked_unapproved_holder"
    #: The scan finished and found no holder. There is nothing to restart, and
    #: that is a usable answer rather than a missing one.
    NOTHING_TO_RESTART = "nothing_to_restart"
    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ArmRestartPlan:
    """An approved, ordered restart plan, or the reason there is not one."""

    state: ArmSequenceState
    code: str
    units: tuple[str, ...] = ()
    unapproved: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.state is ArmSequenceState.COMPOSED:
            if not self.units:
                raise ValueError("a composed restart plan needs units")
            if self.unapproved:
                raise ValueError("a composed restart plan has no unapproved holders")
        elif self.state is ArmSequenceState.NOTHING_TO_RESTART:
            if self.units or self.unapproved:
                raise ValueError("nothing to restart names no units")
        elif self.units:
            raise ValueError("only a composed restart plan exposes units")
        if self.state is ArmSequenceState.BLOCKED_UNAPPROVED_HOLDER and not self.unapproved:
            raise ValueError("a blocked plan must name its unapproved holders")

    @property
    def usable(self) -> bool:
        """Whether the caller may proceed with this plan.

        Two states qualify. A plan with units is one thing to do; a device that
        nothing holds is another, and both leave the sequence able to continue.
        """
        return self.state in (
            ArmSequenceState.COMPOSED,
            ArmSequenceState.NOTHING_TO_RESTART,
        )


@dataclass(frozen=True, slots=True)
class RestartCoverage:
    """How a session-target restart alone would treat each observed holder."""

    reached: tuple[str, ...]
    requires_explicit_restart: tuple[str, ...]
    unapproved: tuple[str, ...]

    @property
    def complete(self) -> bool:
        """True only when every observed holder is approved and accounted for."""
        return not self.unapproved


def classify_holder_units(holder_units: tuple[str, ...]) -> RestartCoverage:
    """Partition observed holder units by how an arm plan must treat them.

    Unapproved units are reported separately and never folded into `reached`.
    An unfamiliar sibling service must not read as covered merely because its
    relationship to the session target is unknown.
    """
    observed = set(holder_units)
    return RestartCoverage(
        reached=tuple(sorted(observed & APPROVED_SESSION_REACHED)),
        requires_explicit_restart=tuple(
            unit for unit in APPROVED_EXPLICIT_RESTARTS if unit in observed
        ),
        unapproved=tuple(sorted(observed - APPROVED_HOLDER_UNITS)),
    )


def units_cleared_by(unit: str, holders: tuple[str, ...]) -> tuple[str, ...]:
    """Which observed holders a restart of `unit` is expected to release.

    A target is not a holder. Holders are reported by their leaf cgroup name
    and a systemd target has no cgroup, so nothing in a holder scan is ever
    named `gamescope-session.target`. Waiting for the target's own name to
    disappear therefore succeeded on the first scan, instantly and always,
    without the session having been restarted at all -- observed on hardware,
    where the sequence then re-observed and refused with the very holders the
    restart was supposed to clear.

    What a session-target restart actually clears is its member services, so
    that is what a caller watches. A plain service clears itself.

    Only approved members are ever named. An unapproved holder is refused by
    `compose_restart_plan` and must not become something a caller waits for.
    """
    observed = set(holders)
    if unit == SESSION_TARGET:
        return tuple(sorted(observed & APPROVED_SESSION_REACHED))
    return (unit,) if unit in observed else ()


def compose_restart_plan(
    holder_units: tuple[str, ...], *, scan_complete: bool
) -> ArmRestartPlan:
    """Return the approved restart plan for the observed holders.

    The plan restarts only approved units the session target does not reach,
    then the session target itself. Units the target already reaches are not
    restarted individually: doing so would disrupt the session more than the
    measured sequence did, without evidence that it helps.
    """
    if type(holder_units) is not tuple or any(
        type(unit) is not str or not unit for unit in holder_units
    ):
        return ArmRestartPlan(
            ArmSequenceState.INVALID, "arm_sequence.holder_units_invalid"
        )
    if type(scan_complete) is not bool:
        return ArmRestartPlan(
            ArmSequenceState.INVALID, "arm_sequence.holder_units_invalid"
        )
    if not holder_units:
        if not scan_complete:
            # A scan that could not finish looking found nothing because it
            # stopped looking. Arming on that basis would be unfounded.
            return ArmRestartPlan(
                ArmSequenceState.EVIDENCE_INCOMPLETE,
                "arm_sequence.no_holders_observed",
            )
        # The scan looked everywhere and the device is held by nothing. There
        # is nothing to restart, and the sequence may still arm: the filter is
        # what stops a holder reappearing during the window that follows.
        #
        # This used to be indistinguishable from the case above, because the
        # completeness the caller already had was dropped at this boundary --
        # the same weakening that made an empty holder tuple read as a clear
        # device. An idle eGPU that nothing holds is the ordinary state before
        # a disconnect, and it could not be armed at all.
        return ArmRestartPlan(
            ArmSequenceState.NOTHING_TO_RESTART, "arm_sequence.device_already_clear"
        )

    coverage = classify_holder_units(holder_units)
    if coverage.unapproved:
        return ArmRestartPlan(
            ArmSequenceState.BLOCKED_UNAPPROVED_HOLDER,
            "arm_sequence.unapproved_holder",
            unapproved=coverage.unapproved,
        )
    return ArmRestartPlan(
        ArmSequenceState.COMPOSED,
        "arm_sequence.composed",
        (*coverage.requires_explicit_restart, SESSION_TARGET),
    )
