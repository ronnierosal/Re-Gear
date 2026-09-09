"""Resume the TV a player already docked to, once it is actually observed.

A player docks with the TV switched off. The dock and the eGPU come up fine,
but the TV advertises no connection until someone picks up a remote, so there
is nothing to switch to. Today that reads as a failed dock. What the player
actually wants is for the setup they had last time to resume by itself when
the TV comes on.

So this remembers a TV as *intent* and answers one question on each reading:
may the normal TV transition continue now? It is the waiting half only. The
eGPU side is already ready by the time this matters, and saying so separately
is the point -- "eGPU ready, waiting for your TV" is a true and useful thing
to show, where "not connected" is neither.

Distinct from `tv_wake`, which is about using HDMI-CEC to *turn a TV on*.
This module never asks for that and does not depend on it; a TV switched on by
hand reaches the same place.

The rules, each of which declines on its own:

- **identity, not a port.** A saved TV is a panel, matched by the identity its
  EDID gives it. A connector-derived identity names the HDMI socket, and a
  different TV plugged into the same socket would wear it -- so a profile
  without EDID identity waits and asks the player to switch by hand rather
  than resuming to whatever is on that port now;
- **verified, not merely observed.** `Confidence.OBSERVED` is a reading nobody
  corroborated. Switching a display on it is the blind switch the acceptance
  for this work forbids outright;
- **an unfinished look is not an absent TV,** and must not spend the budget.
  A reader that keeps failing would otherwise exhaust the attempts and give up
  on a TV that was there the whole time;
- **waiting is bounded.** After the budget, this settles into a neutral state
  and stays there. An indefinite "connecting..." is a worse answer than "your
  saved TV was not found", because only one of them lets the player act;
- **nothing here is a model.** No dock or TV is named. A profile is whatever
  identity a previous successful dock produced, so an unrecognised eGPU with a
  perfectly ordinary TV behaves the same as a known one.

Pure. It remembers nothing itself, switches nothing, and authorizes no display
change on its own -- it reports that the saved TV is present and verified, and
the transition that already exists does the rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import Confidence, DisplayKind, DisplayObservation


#: How many finished looks may find nothing before this settles. Bounded so the
#: UI can stop implying a TV is coming; deliberately small, because a player who
#: turns the TV on later re-arms this by docking again.
DEFAULT_MAX_ATTEMPTS = 20


@dataclass(frozen=True, slots=True)
class SavedTvProfile:
    """A TV a previous dock succeeded against, remembered as player intent.

    Only an explicitly successful transition should produce one of these. It is
    intent, not a guess: nothing here is inferred from a TV merely having been
    seen once.
    """

    #: The display identity recorded at save time.
    display_stable_id: str
    #: Whether that identity came from the panel's EDID rather than from the
    #: connector it happened to be plugged into. Captured at save time so this
    #: module never has to know how an adapter spells an identity.
    edid_identified: bool
    #: What to call it for a player. Presentation only, never matched on.
    label: str = ""


class SavedTvState(StrEnum):
    #: No saved TV. Nothing to resume; ordinary behaviour applies.
    NONE = "none"
    #: The saved TV is present and verified. The normal transition may continue.
    READY = "ready"
    #: Not found yet, still looking. The eGPU half is ready and should say so.
    WAITING = "waiting"
    #: The display reading did not finish. Not evidence of an absent TV, and
    #: does not spend the budget.
    UNOBSERVABLE = "unobservable"
    #: Looked the agreed number of times and settled. Neutral, not an error.
    SETTLED = "settled"


@dataclass(frozen=True, slots=True)
class SavedTvDecision:
    state: SavedTvState
    code: str
    #: The identity this decision is about, so a caller cannot act on a
    #: different display than the one that was matched.
    display_stable_id: str = ""
    #: For a player, when there is something worth naming.
    label: str = ""

    @property
    def may_continue(self) -> bool:
        return self.state is SavedTvState.READY


def decide_saved_tv(
    *,
    profile: SavedTvProfile | None,
    displays: tuple[DisplayObservation, ...],
    scan_complete: bool,
    attempts: int = 0,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> SavedTvDecision:
    """Whether the saved TV is present enough to continue the transition.

    ``attempts`` counts finished looks that found nothing. An unfinished look
    returns ``UNOBSERVABLE`` and the caller should not increment it: spending
    the budget on a reading that never happened is how a working TV gets
    abandoned by a flapping reader.
    """

    if profile is None:
        return SavedTvDecision(SavedTvState.NONE, "saved_tv.no_profile")

    if not profile.edid_identified:
        # A connector-derived identity names the socket. Resuming to it would
        # switch to whatever is plugged in there now, which is not the promise.
        return SavedTvDecision(
            SavedTvState.WAITING,
            "saved_tv.identity_not_verifiable",
            display_stable_id=profile.display_stable_id,
            label=profile.label,
        )

    if not scan_complete:
        return SavedTvDecision(
            SavedTvState.UNOBSERVABLE,
            "saved_tv.display_scan_incomplete",
            display_stable_id=profile.display_stable_id,
            label=profile.label,
        )

    def waiting(code: str) -> SavedTvDecision:
        state = (
            SavedTvState.SETTLED if attempts >= max_attempts else SavedTvState.WAITING
        )
        # Settling replaces only "still looking" with "did not find it".
        # Any other reason -- a contradicted identity, an uncorroborated
        # reading -- is why the search ended and must survive it.
        settled_code = (
            "saved_tv.not_found"
            if state is SavedTvState.SETTLED and code == "saved_tv.awaiting_display"
            else code
        )
        return SavedTvDecision(
            state,
            settled_code,
            display_stable_id=profile.display_stable_id,
            label=profile.label,
        )

    match = next(
        (
            display
            for display in displays
            if display.stable_id == profile.display_stable_id
        ),
        None,
    )
    if match is None:
        return waiting("saved_tv.awaiting_display")

    if match.kind is not DisplayKind.EXTERNAL:
        # The saved identity now reports as something other than an external
        # display. That is a contradiction, not a TV to resume to.
        return waiting("saved_tv.identity_contradicted")

    if match.connected is None or match.confidence is not Confidence.VERIFIED:
        # Unreadable, or read without corroboration. Either way not a fact to
        # move a player's display on.
        return waiting("saved_tv.connection_unverified")

    if not match.connected:
        return waiting("saved_tv.awaiting_display")

    return SavedTvDecision(
        SavedTvState.READY,
        "saved_tv.ready",
        display_stable_id=profile.display_stable_id,
        label=profile.label,
    )
