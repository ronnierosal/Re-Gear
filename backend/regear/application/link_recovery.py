"""Release the session, watch for the link, and always give the session back.

The measurement this implements: with the eGPU plugged in and PCI enumeration
never completing, stopping `gamescope-session.target` caused the kernel to log
`pciehp: Slot(0): Card present` and `Link Up` 6.7 seconds later (2.2 seconds on
an earlier occurrence). The card is reported as *newly present*, so while the
session runs the slot is not detecting it at all and no amount of waiting would
have worked.

Three things make this different from the restarts already in the codebase.

**The gap is the mechanism, so a restart will not do.** `systemctl restart`
brings the session straight back; the link needed seconds of nothing holding
the GPU. So this stops, watches, and starts as three separate steps, and the
stop is the blocking one.

**The link is watched, not assumed.** In the same spirit as
`await_units_released`, a stop returning success only means the unit was asked
to stop. What matters is whether the slot then saw the card, so this polls the
caller's own observation of PCI completion and reports the truth either way. A
recovery that did not recover says so.

**The session is always given back.** Every path out of here starts the
session again, including the failure paths and an unexpected exception. Losing
the eGPU is a disappointment; leaving somebody on a black screen because a
display fix raised is not acceptable, and `finally` is the only way to promise
that. If the restore itself fails, that is reported as its own outcome and is
the most serious code this module can produce.

It authorizes nothing. The decision to offer this at all lives in
`regear.domain.link_training_recovery`, and the confirmation belongs to whoever
is looking at the screen that is about to go away.
"""

from __future__ import annotations

from dataclasses import dataclass
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


#: How long to leave the session down while watching for the link. The two
#: measured recoveries took 2.2s and 6.7s; this is generous enough to cover a
#: slower one without stranding anybody on a black screen if it never comes.
DEFAULT_GAP_SECONDS = 20.0

#: How often to look. Cheap -- it is a sysfs path existing or not.
POLL_INTERVAL_SECONDS = 0.5


@dataclass(frozen=True, slots=True)
class LinkRecoveryOutcome:
    ok: bool
    code: str
    #: Seconds between the session stopping and the link appearing. Only
    #: meaningful when `ok`; it is the number worth recording as evidence.
    seconds: float | None = None
    #: True when the session was put back. False here is the serious case and
    #: means somebody is looking at a black screen.
    session_restored: bool = True


class LinkRecoveryService:
    """Perform one held session release per attachment, and report honestly."""

    def __init__(
        self,
        commands: UserServiceCommandPort,
        observe_pci_complete: Callable[[], bool],
        *,
        now: Callable[[], float],
        sleep: Callable[[float], None],
        gap_seconds: float = DEFAULT_GAP_SECONDS,
    ) -> None:
        self._commands = commands
        self._observe = observe_pci_complete
        self._now = now
        self._sleep = sleep
        self._gap_seconds = gap_seconds
        self._attempted = False

    # -- the latch -----------------------------------------------------------

    def observe_transport(self, present: bool) -> None:
        """Re-arm when the eGPU goes away, so a replug earns a fresh offer."""
        if not present:
            self._attempted = False

    @property
    def attempted(self) -> bool:
        return self._attempted

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

    def recover(self, user: GamescopeUserContext) -> LinkRecoveryOutcome:
        """Stop the session, watch for the link, start the session again.

        Spends the attachment's one attempt whatever happens, including a stop
        that failed: something is wrong enough that offering the same button
        again would not help.
        """
        self._attempted = True
        stopped = self._run(UserServiceOperation.STOP_GAMESCOPE_SESSION, user)
        if not stopped:
            # Nothing was taken down, so there is nothing to give back, but
            # start anyway rather than reason about a partial stop.
            restored = self._run(UserServiceOperation.START_GAMESCOPE_SESSION, user)
            return LinkRecoveryOutcome(
                False, "link_recovery.stop_failed", session_restored=restored
            )

        began = self._now()
        trained_at: float | None = None
        try:
            deadline = began + self._gap_seconds
            while True:
                if self._observe():
                    trained_at = self._now()
                    break
                if self._now() >= deadline:
                    break
                self._sleep(POLL_INTERVAL_SECONDS)
        finally:
            restored = self._run(
                UserServiceOperation.START_GAMESCOPE_SESSION, user
            )

        if not restored:
            return LinkRecoveryOutcome(
                False,
                "link_recovery.session_restore_failed",
                seconds=None if trained_at is None else trained_at - began,
                session_restored=False,
            )
        if trained_at is None:
            return LinkRecoveryOutcome(False, "link_recovery.link_absent")
        return LinkRecoveryOutcome(
            True, "link_recovery.trained", seconds=trained_at - began
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
