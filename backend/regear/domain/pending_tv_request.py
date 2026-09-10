"""Hold a player's explicit "take me to the TV" while the TV is not there yet.

A player opens Re-Gear, the eGPU is up, and they ask for their TV -- but the TV
is switched off, or its HDMI side advertises nothing, so there is no output to
switch to. Today that request has nowhere to go: it either fails immediately,
which is wrong because the player's intent is perfectly clear, or it would have
to invent a display, which is the blind switch this project forbids outright.

So this records the request and answers one question per reading: is the exact
TV they asked for actually there now? That is all. It is the waiting half of a
request, in the same shape `deferred_dock` gives a Dock asked for while a game
is running -- a bounded, non-authorizing intent plus a handoff carrying fresh
observation evidence, which the transition path that already exists re-observes
and confirms for itself.

Distinct from `saved_tv`, and deliberately so. That module is the *passive*
resume: a TV a previous dock succeeded against comes back on, and the dock that
is already in progress continues. This is an *active* request made when no dock
is in progress, which is why it needs its own identity, its own budget and its
own cancel. The two share the remembered profile and nothing else.

Distinct from `tv_wake` as well. Nothing here turns a TV on, asks anything to
turn a TV on, or forces a mode onto a connector. A TV switched on by hand, or
by a remote, or by a person walking into the room, reaches the same place.

The rules, each of which declines on its own:

- **the request names one panel, not "a TV".** A request bound to a remembered
  EDID identity is a request for that panel. A request made with nothing
  remembered waits for exactly one verified, EDID-identified external display
  and reports *two* candidates as "cannot tell", never as a choice to make on
  the player's behalf;
- **a connector-derived identity is a socket, not a panel.** A remembered
  profile without EDID identity ends the search on the first reading rather
  than waiting: no number of further looks can change a property of the record,
  and a different TV in that socket would wear the same name;
- **an unfinished look is not an absent TV,** and must not spend the budget. A
  reader that keeps failing would otherwise exhaust the attempts and abandon a
  TV that was there the whole time;
- **waiting is bounded.** After the budget this settles into a neutral
  not-found and stays there. "Your TV was not found" is a worse-sounding and
  far more useful answer than a "connecting..." that never ends;
- **the dock underneath must be the same dock.** The request binds to the exact
  eGPU identity it was made against. A different attachment invalidates it
  rather than silently re-pointing a display switch at a new dock's TV;
- **nothing here authorizes anything.** `READY` yields a handoff -- a request
  identity, the attachment it was bound to, the observation generation that saw
  the TV, and the exact display identity. A handoff is evidence for the
  existing preview/approve/execute path, which re-observes and obtains the
  player's confirmation itself. There is no permit, no plan, no token and no
  mechanism in this module.

Two decisions this module makes on purpose, recorded here because both were
open questions and both are load-bearing:

- **a request does not survive a reboot.** It is a live intent, not a standing
  preference. The standing preference already exists and is already persisted:
  the saved TV profile. A request that outlived a reboot would move a player's
  display on the strength of something they asked for in a session that is
  over, possibly in another room. So nothing here is written anywhere, and the
  coordinator that holds it keeps it in memory only;
- **a ready arrival needs renewed approval.** The handoff is not an approval.
  Re-Gear grants display mutation to supervised execution or to the explicit
  profile-gated automatic path, and a request that sat waiting is neither: the
  approval that would have covered it is short-lived by design and the player
  may well have walked away. When the automatic-connection preference is on,
  the arrival is carried by the automatic coordinator that already exists,
  under the latches it already honours -- this module adds no authority to it.

Pure. No clock, no store, no discovery, no display change.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .control_plane import RequestSource
from .models import Confidence, DisplayKind, DisplayObservation
from .saved_tv import DEFAULT_MAX_ATTEMPTS, SavedTvProfile


#: Sources that may record an explicit request. An automatic source has its own
#: path -- the profile-gated automatic dock -- and letting it mint a player
#: intent here would launder an automatic decision into a manual one.
DIRECT_REQUEST_SOURCES = frozenset(
    {RequestSource.MANUAL, RequestSource.CONTROLLER, RequestSource.STEAM_MENU}
)


class PendingTvState(StrEnum):
    #: No request outstanding. Ordinary behaviour applies.
    NONE = "none"
    #: The request could not be recorded at all. Nothing is waiting.
    REJECTED = "rejected"
    #: Recorded, looked, finished the look, and did not find the TV.
    WAITING = "waiting"
    #: The reading did not finish, or could not say which TV was meant. Not
    #: evidence of an absent TV, and does not spend the budget.
    UNOBSERVABLE = "unobservable"
    #: The bounded search is over. Neutral, not an error.
    NOT_FOUND = "not_found"
    #: The exact requested TV is present and verified. The existing approval
    #: path may now be offered. This is not itself an approval.
    READY = "ready"
    #: The player withdrew the request.
    CANCELLED = "cancelled"
    #: The dock or the remembered TV changed underneath the request.
    INVALIDATED = "invalidated"


@dataclass(frozen=True, slots=True)
class PendingTvRequest:
    """One bounded player request for a TV. Not a plan and not a permit."""

    #: Opaque request identity, issued by the caller. Never a device identity.
    request_id: str
    source: RequestSource
    #: The exact eGPU identity this request was made against, so a different
    #: attachment cannot inherit it. An opaque adapter-issued token, never a
    #: bus address, card number or connector.
    attachment_binding: str
    #: The remembered panel this request is for, or "" when nothing was
    #: remembered and the request is for the one TV that appears.
    display_stable_id: str = ""
    #: Whether ``display_stable_id`` came from the panel's EDID rather than
    #: from the connector it happened to be plugged into.
    edid_identified: bool = False
    #: What to call it for a player. Presentation only, never matched on.
    label: str = ""

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("pending TV request requires an opaque request identity")
        if not self.attachment_binding:
            raise ValueError("pending TV request requires an exact attachment binding")
        if self.source not in DIRECT_REQUEST_SOURCES:
            raise ValueError("pending TV request requires direct player intent")
        if self.edid_identified and not self.display_stable_id:
            raise ValueError("pending TV request identity grade needs an identity")

    @property
    def bound(self) -> bool:
        """Whether this request names one remembered panel."""
        return bool(self.display_stable_id)


@dataclass(frozen=True, slots=True)
class PendingTvHandoff:
    """Fresh evidence for the existing approval path; never an execution permit.

    It carries the exact display the TV was seen on so the approval path acts
    on the panel that was actually detected, rather than on whatever the
    request set out to reach.
    """

    request_id: str
    attachment_binding: str
    observed_generation: str
    display_stable_id: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.request_id,
                self.attachment_binding,
                self.observed_generation,
                self.display_stable_id,
            )
        ):
            raise ValueError("pending TV handoff is incomplete")


@dataclass(frozen=True, slots=True)
class PendingTvResolution:
    state: PendingTvState
    code: str
    #: The request this resolution is about, while one is still outstanding.
    request: PendingTvRequest | None = None
    #: Present only in ``READY``.
    handoff: PendingTvHandoff | None = None
    #: For a player, when there is something worth naming.
    label: str = ""

    def __post_init__(self) -> None:
        if self.state is PendingTvState.READY:
            if self.handoff is None:
                raise ValueError("a ready pending TV request requires its handoff")
        elif self.handoff is not None:
            raise ValueError("only a ready pending TV request exposes a handoff")
        if self.state in _OUTSTANDING_STATES and self.request is None:
            raise ValueError("an outstanding pending TV request must be carried")
        if self.state in _TERMINAL_STATES and self.request is not None:
            raise ValueError("a terminated pending TV request is not outstanding")

    @property
    def outstanding(self) -> bool:
        """Whether the request is still waiting for its TV."""
        return self.state in _OUTSTANDING_STATES

    @property
    def ready(self) -> bool:
        return self.state is PendingTvState.READY


#: States in which the request is still alive and must be carried forward.
#: ``READY`` is deliberately not one of them: a ready arrival is handed off to
#: the approval path, and holding the request open as well would let one
#: arrival be offered twice.
_OUTSTANDING_STATES = frozenset(
    {PendingTvState.WAITING, PendingTvState.UNOBSERVABLE, PendingTvState.NOT_FOUND}
)
#: States that end the request. Nothing is outstanding afterwards.
_TERMINAL_STATES = frozenset(
    {
        PendingTvState.NONE,
        PendingTvState.REJECTED,
        PendingTvState.READY,
        PendingTvState.CANCELLED,
        PendingTvState.INVALIDATED,
    }
)


def create_pending_tv_request(
    *,
    request_id: str,
    source: RequestSource,
    attachment_binding: str,
    saved_profile: SavedTvProfile | None,
    saved_record_readable: bool,
) -> PendingTvResolution:
    """Record the request, bound to whatever is actually known right now.

    An unreadable record is refused rather than treated as "nothing
    remembered". The difference matters: "nothing remembered" binds the request
    to the one TV that appears, and doing that because a file could not be read
    would aim a display switch at a panel the player never chose.
    """

    if not saved_record_readable:
        return PendingTvResolution(
            PendingTvState.REJECTED, "pending_tv.record_unreadable"
        )
    if not attachment_binding:
        # No exact eGPU identity means nothing to bind the request to, and a
        # request that is not bound would be inherited by the next dock.
        return PendingTvResolution(
            PendingTvState.REJECTED, "pending_tv.attachment_unknown"
        )
    if source not in DIRECT_REQUEST_SOURCES:
        # An automatic source already has a path. Letting it mint an intent
        # here would launder an automatic decision into a player's own, and the
        # blockers the automatic path honours would be bypassed by the
        # resulting "manual" request.
        return PendingTvResolution(
            PendingTvState.REJECTED, "pending_tv.automatic_source_rejected"
        )
    try:
        request = PendingTvRequest(
            request_id=request_id,
            source=source,
            attachment_binding=attachment_binding,
            display_stable_id=(
                saved_profile.display_stable_id if saved_profile is not None else ""
            ),
            edid_identified=(
                saved_profile.edid_identified if saved_profile is not None else False
            ),
            label=saved_profile.label if saved_profile is not None else "",
        )
    except ValueError:
        return PendingTvResolution(PendingTvState.REJECTED, "pending_tv.request_invalid")
    return PendingTvResolution(
        PendingTvState.WAITING,
        "pending_tv.requested",
        request,
        label=request.label,
    )


def cancel_pending_tv_request(request: PendingTvRequest) -> PendingTvResolution:
    """Withdraw the request. Nothing is executed, rolled back or restored."""
    return PendingTvResolution(
        PendingTvState.CANCELLED, "pending_tv.cancelled", label=request.label
    )


def evaluate_pending_tv_request(
    request: PendingTvRequest,
    *,
    attachment_binding: str,
    displays: tuple[DisplayObservation, ...],
    scan_complete: bool,
    observed_generation: str,
    attempts: int = 0,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> PendingTvResolution:
    """Whether the requested TV is there, on this one reading.

    ``attempts`` counts finished looks that found nothing; the caller owns the
    count and must spend it only on ``WAITING``. Spending it on a reading that
    never happened is how a working TV gets abandoned by a flapping reader.
    """

    def settled(code: str) -> PendingTvResolution:
        state = (
            PendingTvState.NOT_FOUND if attempts >= max_attempts else PendingTvState.WAITING
        )
        # Settling replaces only "still looking" with "did not find it". Any
        # other reason -- a contradicted identity, an uncorroborated reading --
        # is why the search ended and must survive it.
        final = (
            "pending_tv.not_found"
            if state is PendingTvState.NOT_FOUND and code == "pending_tv.awaiting_display"
            else code
        )
        return PendingTvResolution(state, final, request, label=request.label)

    def cannot_tell(code: str) -> PendingTvResolution:
        return PendingTvResolution(
            PendingTvState.UNOBSERVABLE, code, request, label=request.label
        )

    if not attachment_binding:
        # The dock this request was made against is no longer identified. Not a
        # reason to keep looking for its TV, and not a reason to claim removal.
        return PendingTvResolution(
            PendingTvState.INVALIDATED,
            "pending_tv.attachment_absent",
            label=request.label,
        )
    if attachment_binding != request.attachment_binding:
        return PendingTvResolution(
            PendingTvState.INVALIDATED,
            "pending_tv.attachment_changed",
            label=request.label,
        )
    if request.bound and not request.edid_identified:
        # A property of the record, not of what is plugged in, so no number of
        # further looks can change it. Ending the search now rather than
        # waiting out the budget is the difference between telling the player
        # to switch by hand and implying their TV is still coming.
        return PendingTvResolution(
            PendingTvState.NOT_FOUND,
            "pending_tv.identity_not_verifiable",
            request,
            label=request.label,
        )
    if not scan_complete:
        return cannot_tell("pending_tv.display_scan_incomplete")

    if request.bound:
        match = next(
            (
                display
                for display in displays
                if display.stable_id == request.display_stable_id
            ),
            None,
        )
        if match is None:
            return settled("pending_tv.awaiting_display")
        if match.kind is not DisplayKind.EXTERNAL:
            # The requested identity now reports as something other than an
            # external display. A contradiction, not a TV to switch to.
            return settled("pending_tv.identity_contradicted")
        if match.connected is None or match.confidence is not Confidence.VERIFIED:
            return settled("pending_tv.connection_unverified")
        if not match.connected:
            return settled("pending_tv.awaiting_display")
        found = match
    else:
        candidates = tuple(
            display
            for display in displays
            if display.kind is DisplayKind.EXTERNAL
            and display.connected is True
            and display.confidence is Confidence.VERIFIED
            and display.edid_ready is True
            and display.stable_id
        )
        if not candidates:
            return settled("pending_tv.awaiting_display")
        if len(candidates) > 1:
            # Two panels and no remembered choice. "Cannot tell which one you
            # meant" is the honest answer; picking one would be Re-Gear
            # choosing a player's display for them.
            return cannot_tell("pending_tv.target_ambiguous")
        found = candidates[0]

    if not observed_generation:
        # The TV matched, but this reading cannot say which observation saw it.
        # Handing that to the approval path would give it evidence it cannot
        # re-check, so it is "cannot tell" and the budget is not spent.
        return cannot_tell("pending_tv.observation_unavailable")
    return PendingTvResolution(
        PendingTvState.READY,
        "pending_tv.ready",
        handoff=PendingTvHandoff(
            request_id=request.request_id,
            attachment_binding=request.attachment_binding,
            observed_generation=observed_generation,
            display_stable_id=found.stable_id,
        ),
        label=request.label,
    )
