"""Carry one explicit TV request while the TV is not there, and end it cleanly.

The domain decides one reading. This holds the request between readings, owns
the budget that makes waiting end, and turns a decision into something a player
can be shown: waiting, cannot tell, not found, or ready.

It also owns the one thing the domain deliberately refuses to know about. A
found TV and a running game are independent facts, so `evaluate_pending_tv_request`
is never told the game state -- mixing them is how "your TV is ready" became
"your TV is not connected" in the past. The policy that a blocked transition
must not be offered lives here instead, and it is expressed as a blocker beside
a `READY` state rather than by downgrading the state. A player whose TV just
came on is told exactly that, plus what is in the way.

Two properties worth stating, because both are easy to lose in an edit:

- **a ready arrival that cannot be offered does not end the request.** If the
  TV appears mid-game the intent must survive until the game closes, otherwise
  the player's request evaporates for a reason that has nothing to do with
  their TV. The request is retired only when the arrival is actually handed to
  the approval path, or when the player cancels, or when the dock changes;
- **nothing here is written anywhere.** The request lives in this object for as
  long as the plugin does and no longer. The standing preference -- the TV to
  resume to -- is already persisted elsewhere and is read through, never
  copied. See the decision recorded in the domain module: a request that
  outlived a reboot would move a display on the strength of a session that is
  over.

This composes, counts, and reports. It observes no hardware, switches no
display, and authorizes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.control_plane import RequestSource
from ..domain.models import DisplayObservation, GameState
from ..domain.pending_tv_request import (
    PendingTvHandoff,
    PendingTvRequest,
    PendingTvState,
    cancel_pending_tv_request,
    create_pending_tv_request,
    evaluate_pending_tv_request,
)
from ..domain.saved_tv import DEFAULT_MAX_ATTEMPTS


@dataclass(frozen=True, slots=True)
class PendingTvRequestStatus:
    """Categorical state for one waiting request.

    The requested display identity and the label EDID gave it stay behind this
    boundary, the way the saved-TV status already keeps them off the snapshot
    payload. A state, a code and the budget are everything a caller needs to
    tell "waiting for your TV" from "cannot tell" from "not found" from "ready".
    """

    state: PendingTvState
    code: str
    attempts: int = 0
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    #: The existing preview/approve/execute path may be offered now. Never an
    #: approval, a permit or a plan -- that path re-observes and asks the player
    #: for itself.
    approval_offered: bool = False
    #: The arrival is eligible for the already-approved, profile-gated automatic
    #: path. The automatic coordinator that exists still decides, under the
    #: latches it already honours; this adds no authority to it.
    automatic_continuation: bool = False
    #: Why a found TV is not offerable yet. Presentation only.
    blockers: tuple[str, ...] = field(default_factory=tuple)

    @property
    def waiting(self) -> bool:
        return self.state in {
            PendingTvState.WAITING,
            PendingTvState.UNOBSERVABLE,
        }


_NO_REQUEST = PendingTvRequestStatus(PendingTvState.NONE, "pending_tv.no_request")


class PendingTvRequestCoordinator:
    """At most one outstanding request, bounded, cancellable, and in memory."""

    def __init__(self, search, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> None:
        self._search = search
        self._max_attempts = max_attempts
        self._request: PendingTvRequest | None = None
        self._attempts = 0
        self._status = _NO_REQUEST
        self._handoff: PendingTvHandoff | None = None

    @property
    def attempts(self) -> int:
        """Finished looks that did not find it. For reporting and tests."""
        return self._attempts

    @property
    def outstanding(self) -> bool:
        return self._request is not None

    def status(self) -> PendingTvRequestStatus:
        return self._status

    def request(
        self,
        *,
        request_id: str,
        source: RequestSource,
        attachment_binding: str,
    ) -> PendingTvRequestStatus:
        """Record the request, bound to the TV this player actually has.

        A second request replaces the first and re-arms the budget: a player
        asking again is asking again, not continuing a search that already gave
        up on them.
        """
        target = self._search.target()
        resolution = create_pending_tv_request(
            request_id=request_id,
            source=source,
            attachment_binding=attachment_binding,
            saved_profile=target.profile,
            saved_record_readable=target.readable,
        )
        self._attempts = 0
        self._handoff = None
        self._request = resolution.request
        self._status = self._present(resolution.state, resolution.code)
        return self._status

    def cancel(self) -> PendingTvRequestStatus:
        """Withdraw the request. Explicit, immediate, and never implied."""
        request = self._request
        if request is None:
            self._status = _NO_REQUEST
            return self._status
        resolution = cancel_pending_tv_request(request)
        self._retire()
        self._status = self._present(resolution.state, resolution.code)
        return self._status

    def rearm(self) -> PendingTvRequestStatus:
        """Keep looking for the same TV, from zero.

        The budget bounds one attempt to find the TV, not the player's patience.
        Re-arming changes no authority: the same request, looked for again.
        """
        if self._request is None:
            self._status = _NO_REQUEST
            return self._status
        self._attempts = 0
        self._handoff = None
        self._status = self._present(PendingTvState.WAITING, "pending_tv.rearmed")
        return self._status

    def satisfied(self) -> PendingTvRequestStatus:
        """Retire the request because the player is on a TV now.

        Called when a transition to the TV actually succeeded. Leaving the
        request outstanding would have it offered again from the place it was
        trying to reach.
        """
        if self._request is None:
            self._status = _NO_REQUEST
            return self._status
        self._retire()
        self._status = self._present(PendingTvState.NONE, "pending_tv.satisfied")
        return self._status

    def take_handoff(self) -> PendingTvHandoff | None:
        """The one arrival's evidence, handed over once.

        Consumed on read so a single arrival cannot be offered twice. It is
        evidence for the existing approval path, not an approval.
        """
        handoff, self._handoff = self._handoff, None
        return handoff

    def observe(
        self,
        *,
        attachment_binding: str,
        displays: tuple[DisplayObservation, ...],
        scan_complete: bool,
        observed_generation: str,
        game_state: GameState = GameState.UNKNOWN,
        automatic_preference_enabled: bool = False,
        portable_return_suppressed: bool = False,
    ) -> PendingTvRequestStatus:
        """Resolve one reading, spending the budget only on a finished look."""
        request = self._request
        if request is None:
            self._status = _NO_REQUEST
            return self._status

        target = self._search.target()
        if not target.readable:
            # "Cannot tell whether the remembered TV is still the one asked
            # for" is not a reason to throw the request away. A reader that
            # fails for a moment must not cancel a player's intent, so the
            # request stands and the budget is not spent.
            self._status = self._present(
                PendingTvState.UNOBSERVABLE, "pending_tv.record_unreadable"
            )
            return self._status
        remembered = target.profile.display_stable_id if target.profile else ""
        if remembered != request.display_stable_id:
            # A display switch must not be silently re-pointed at a different
            # panel, so a changed record ends the request and the player asks
            # again for the TV they are actually at now.
            self._retire()
            self._status = self._present(
                PendingTvState.INVALIDATED, "pending_tv.target_changed"
            )
            return self._status

        resolution = evaluate_pending_tv_request(
            request,
            attachment_binding=attachment_binding,
            displays=displays,
            scan_complete=scan_complete,
            observed_generation=observed_generation,
            attempts=self._attempts,
            max_attempts=self._max_attempts,
        )

        if resolution.state is PendingTvState.WAITING:
            # The only state that means "looked, finished, did not find it".
            self._attempts += 1

        if resolution.ready:
            blockers = _transition_blockers(game_state)
            if blockers:
                # Keep the request: the TV is there and the player still wants
                # it. Only the transition is blocked, and that can clear.
                self._status = self._present(
                    resolution.state, resolution.code, blockers=blockers
                )
                return self._status
            self._handoff = resolution.handoff
            exact = request.bound and request.edid_identified
            self._retire()
            self._status = self._present(
                resolution.state,
                resolution.code,
                approval_offered=True,
                automatic_continuation=(
                    exact
                    and automatic_preference_enabled
                    and not portable_return_suppressed
                ),
            )
            return self._status

        if not resolution.outstanding:
            self._retire()
        self._status = self._present(resolution.state, resolution.code)
        return self._status

    def _retire(self) -> None:
        self._request = None
        self._attempts = 0

    def _present(
        self,
        state: PendingTvState,
        code: str,
        *,
        approval_offered: bool = False,
        automatic_continuation: bool = False,
        blockers: tuple[str, ...] = (),
    ) -> PendingTvRequestStatus:
        return PendingTvRequestStatus(
            state=state,
            code=code,
            attempts=self._attempts,
            max_attempts=self._max_attempts,
            approval_offered=approval_offered,
            automatic_continuation=automatic_continuation,
            blockers=blockers,
        )


def _transition_blockers(game_state: GameState) -> tuple[str, ...]:
    """What stands between a found TV and offering the switch.

    Unknown game evidence is a running-game blocker, not an absent one: a
    transition that may restart Gamescope cannot be offered on a reading that
    could not say whether a game is up.
    """
    if game_state is GameState.RUNNING:
        return ("pending_tv.game_running",)
    if game_state is not GameState.IDLE:
        return ("pending_tv.game_state_unknown",)
    return ()
