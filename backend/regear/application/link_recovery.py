"""Disturb the session, watch for the link, and always leave the session running.

**A retraction first.** An earlier version of this module asserted that the
mechanism was the *gap*: that stopping `gamescope-session.target` and holding
it down let the hotplug slot finally see the card, and that a plain restart
therefore could not work. That claim is withdrawn. It was inferred from two
recoveries timed from the moment the stop was issued, without reading what
happened in between.

What the device journals actually show is that the link appears about a second
after a **new session starts**, not during any quiet gap:

- a desktop-mode switch: `gamescope-session.target` Stopped at 22:30:48.110,
  `plasma` Started at 22:30:49.416, `pciehp` Link Up at 22:30:50.691 -- 1.3s
  after the new session, 2.6s after the old one went away;
- a target stop: "Started Gamescope Session" at 23:04:32.314, Link Up at
  23:04:33.102 -- 0.8s later. The gamescope service never reported inactive at
  all, so in this case there was no gap to be the mechanism.

**What is NOT established is why.** A session start is correlated with the link
appearing; that is all. It could be the start itself, something the startup
path does that happens to touch the bus, the desktop round trip as a whole, or
a coincidence of two observations. Nobody has isolated it, and this module must
not pretend otherwise. The owner's hypothesis that a full Desktop-mode round
trip is what actually matters remains open and is deliberately kept reachable
below rather than designed out.

So the mechanism is not baked in. It is a **strategy chosen by the caller**,
and there are three rungs to try on hardware:

1. `SESSION_RESTART` -- one plain restart of the session target. The default,
   because a restart is exactly "a new session starts" and that is the
   best-supported description of what preceded the link. It needs no operation
   the codebase did not already have;
2. `SESSION_STOP_START` -- stop, watch, start. What this branch did when it
   believed the gap theory. Kept as an explicitly selectable rung so the
   comparison can still be run, not because the gap is believed;
3. `DESKTOP_ROUND_TRIP` -- the SteamOS desktop switch and back. Named, refused
   with an explicit code, and deliberately not implemented: it is not a
   `systemctl --user` operation and would need authority this change does not
   ask for. See the note on `DESKTOP_ROUND_TRIP` itself.

Two things survive the retraction unchanged, because they never depended on
which rung is right.

**The link is watched, not assumed.** In the same spirit as
`await_units_released`, a command returning success only means the unit was
asked. What matters is whether the slot then saw the card, so this polls the
caller's own observation of PCI completion and reports the truth either way. A
recovery that did not recover says so.

**The session is always given back.** Every path out of here leaves a command
that starts the session as the last thing issued -- including the failure paths
and an unexpected exception. Losing the eGPU is a disappointment; leaving
somebody on a black screen because a display fix raised is not acceptable.
Each strategy declares how it keeps that promise: a stop is always paired with
a start in a `finally`, while a restart carries its own restore and is only
re-issued when it did not take.

It authorizes nothing. The decision to offer this at all lives in
`regear.domain.link_training_recovery`, and the confirmation belongs to whoever
is looking at the screen that is about to go away.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from ..domain.link_training_recovery import (
    LinkRecoveryAssessment,
    assess_link_recovery,
)
from ..domain.models import GameState
from ..ports.presentation_activation import (
    GamescopeUserContext,
    UserServiceCommandPort,
    UserServiceOperation,
)


class LinkRecoveryStrategy(StrEnum):
    """Which disturbance to try. Chosen per call, never inferred."""

    #: One plain restart of the session target. Default: it is the closest
    #: thing the allow-list already has to the only event the journals put
    #: immediately before the link, and it adds no operation.
    SESSION_RESTART = "session_restart"
    #: Stop, watch with the session down, start. The shape this branch shipped
    #: while it believed the gap was the mechanism. Retained as a rung to
    #: compare against, so that belief can be tested rather than assumed.
    SESSION_STOP_START = "session_stop_start"
    #: The SteamOS desktop switch and back, which on the device is
    #: `steamosctl switch-to-desktop-mode plasma.desktop` followed by
    #: `steamosctl switch-to-game-mode`. Deliberately NOT implemented here.
    #:
    #: Those are not `systemctl --user` operations, so they do not fit
    #: `UserServiceCommandRunner`, whose entire safety property is that every
    #: argv is a fixed suffix looked up by operation behind `systemctl --user`.
    #: Running them would mean a new executor with a new binary on the
    #: allow-list, and that is authority to widen the display/GPU mutation
    #: surface -- which `AGENTS.md` reserves for a milestone decision with
    #: rollback coverage and safety tests. The member exists so the hypothesis
    #: stays visible and addressable; selecting it refuses cleanly.
    DESKTOP_ROUND_TRIP = "desktop_round_trip"


#: Rung 1. The best-supported mechanism and the one that needs nothing new.
DEFAULT_STRATEGY = LinkRecoveryStrategy.SESSION_RESTART

#: How long to keep watching for the link after the disturbance. The two
#: recoveries that were timed from a stop took 2.2s and 6.7s, and the two read
#: from journals arrived 0.8s and 1.3s after a session start; this is generous
#: enough to cover a slower one. It matters most for SESSION_STOP_START, where
#: it is also how long somebody may be looking at nothing.
DEFAULT_WATCH_SECONDS = 20.0

#: How often to look. Cheap -- it is a sysfs path existing or not.
POLL_INTERVAL_SECONDS = 0.5


@dataclass(frozen=True, slots=True)
class _Mechanism:
    """How one strategy disturbs the session, and how it gives it back."""

    #: Run in order. The first failure abandons the disturbance.
    disturb: tuple[UserServiceOperation, ...]
    #: The operation that leaves the session running. Issued on every path out
    #: unless the disturbance already carried it (see `self_restoring`).
    restore: UserServiceOperation
    #: True when a completed disturbance already brings the session back on its
    #: own, so `restore` is a retry for the case where it did not take rather
    #: than a second, gratuitous bounce of a session that is already coming up.
    self_restoring: bool
    #: Reported when the disturbance itself failed.
    failure_code: str


_MECHANISMS: dict[LinkRecoveryStrategy, _Mechanism] = {
    LinkRecoveryStrategy.SESSION_RESTART: _Mechanism(
        disturb=(UserServiceOperation.RESTART_GAMESCOPE_SESSION,),
        restore=UserServiceOperation.RESTART_GAMESCOPE_SESSION,
        self_restoring=True,
        failure_code="link_recovery.restart_failed",
    ),
    LinkRecoveryStrategy.SESSION_STOP_START: _Mechanism(
        disturb=(UserServiceOperation.STOP_GAMESCOPE_SESSION,),
        restore=UserServiceOperation.START_GAMESCOPE_SESSION,
        self_restoring=False,
        failure_code="link_recovery.stop_failed",
    ),
}


def strategy_is_implemented(strategy: LinkRecoveryStrategy) -> bool:
    """Whether selecting `strategy` would do anything but refuse."""
    return strategy in _MECHANISMS


@dataclass(frozen=True, slots=True)
class LinkRecoveryOutcome:
    ok: bool
    code: str
    #: Seconds between the disturbance being accepted and the link appearing.
    #: Only meaningful when `ok`. Which disturbance depends on the strategy, so
    #: it is not comparable across rungs and is not the same instant as the
    #: journal's session-start line; record `strategy` with it or the number
    #: means nothing.
    seconds: float | None = None
    #: True when a command that leaves the session running was issued and
    #: accepted. False here is the serious case and means somebody is looking
    #: at a black screen.
    session_restored: bool = True
    #: The rung this outcome came from. Evidence is worthless without it.
    strategy: str = ""


class LinkRecoveryService:
    """Perform one recovery attempt per attachment, and report honestly."""

    def __init__(
        self,
        commands: UserServiceCommandPort,
        observe_pci_complete: Callable[[], bool],
        *,
        now: Callable[[], float],
        sleep: Callable[[float], None],
        watch_seconds: float = DEFAULT_WATCH_SECONDS,
        default_strategy: LinkRecoveryStrategy = DEFAULT_STRATEGY,
    ) -> None:
        self._commands = commands
        self._observe = observe_pci_complete
        self._now = now
        self._sleep = sleep
        self._watch_seconds = watch_seconds
        self._default_strategy = default_strategy
        self._attempted = False

    # -- the latch -----------------------------------------------------------

    def observe_transport(self, present: bool) -> None:
        """Re-arm when the eGPU goes away, so a replug earns a fresh offer."""
        if not present:
            self._attempted = False

    @property
    def attempted(self) -> bool:
        return self._attempted

    @property
    def default_strategy(self) -> LinkRecoveryStrategy:
        return self._default_strategy

    def assess(
        self,
        *,
        readiness_exhausted: bool,
        transport_present: bool,
        pci_complete: bool,
        game_state: GameState,
    ) -> LinkRecoveryAssessment:
        return assess_link_recovery(
            readiness_exhausted=readiness_exhausted,
            transport_present=transport_present,
            pci_complete=pci_complete,
            game_state=game_state,
            attempted=self._attempted,
        )

    # -- the act -------------------------------------------------------------

    def recover(
        self,
        user: GamescopeUserContext,
        *,
        strategy: LinkRecoveryStrategy | str | None = None,
    ) -> LinkRecoveryOutcome:
        """Disturb the session by the chosen strategy and watch for the link.

        Spends the attachment's one attempt whenever a disturbance was actually
        issued, including one that failed: something is wrong enough that
        offering the same button again would not help. A strategy that is
        refused before anything runs costs nothing, because nothing happened.
        """
        selected = self._default_strategy if strategy is None else strategy
        try:
            chosen = LinkRecoveryStrategy(selected)
        except ValueError:
            return LinkRecoveryOutcome(
                False, "link_recovery.strategy_unknown", strategy=str(selected)
            )
        mechanism = _MECHANISMS.get(chosen)
        if mechanism is None:
            # Rung 3 lands here. Named so the hypothesis stays visible, refused
            # because implementing it needs authority nobody has granted.
            return LinkRecoveryOutcome(
                False,
                "link_recovery.strategy_not_implemented",
                strategy=chosen.value,
            )

        self._attempted = True
        disturbed = True
        for operation in mechanism.disturb:
            if not self._run(operation, user):
                disturbed = False
                break

        # A completed self-restoring disturbance has already promised the
        # session back; anything else has to be given back explicitly.
        restore_needed = not (disturbed and mechanism.self_restoring)
        began: float | None = None
        trained_at: float | None = None
        restored = True
        try:
            if disturbed:
                # Inside the `try` on purpose: even the clock reading must not
                # be able to escape without the restore running.
                began = self._now()
                deadline = began + self._watch_seconds
                while True:
                    if self._observe():
                        trained_at = self._now()
                        break
                    if self._now() >= deadline:
                        break
                    self._sleep(POLL_INTERVAL_SECONDS)
        finally:
            # The promise. Nothing above may return or raise past this without
            # the session having been asked to come back.
            if restore_needed:
                restored = self._run(mechanism.restore, user)

        if not disturbed:
            return LinkRecoveryOutcome(
                False,
                mechanism.failure_code,
                session_restored=restored,
                strategy=chosen.value,
            )
        elapsed = None if began is None or trained_at is None else trained_at - began
        if not restored:
            return LinkRecoveryOutcome(
                False,
                "link_recovery.session_restore_failed",
                seconds=elapsed,
                session_restored=False,
                strategy=chosen.value,
            )
        if trained_at is None:
            return LinkRecoveryOutcome(
                False, "link_recovery.link_absent", strategy=chosen.value
            )
        return LinkRecoveryOutcome(
            True, "link_recovery.trained", seconds=elapsed, strategy=chosen.value
        )

    def _run(
        self, operation: UserServiceOperation, user: GamescopeUserContext
    ) -> bool:
        try:
            outcome = self._commands.run(
                operation, uid=user.uid, username=user.username
            )
        except Exception:
            return False
        return bool(getattr(outcome, "ok", False))
