"""Decide whether closing a running game may proceed, and what to ask first.

Two different player actions have the same consequence. Disconnecting the eGPU
takes away the device the game renders on; sleeping the handheld suspends it
while a game holds that device. Neither can happen underneath a running game,
so in both cases the game has to end first -- and ending a game is the player's
call, not Re-Gear's, because what is at stake is their unsaved progress.

So the question here is not "may we close it". It is **what does the player
need to be told, and have they already answered**. Both intents ask it the same
way on purpose: a player who has learned what the prompt means for sleep should
not have to learn a second, different prompt for a disconnect.

Three facts decide it:

- **which game is running**, exactly. An unidentified game cannot be matched to
  a remembered answer and cannot be relaunched afterwards, so it is always
  asked about;
- **what the reviewed catalog knows** about closing that game. `UNTESTED` is
  the common case and the honest answer is that Re-Gear does not know -- which
  is said plainly rather than rounded into reassurance;
- **the player's standing answer for that one game**, if they gave one.

A remembered answer is deliberately narrow. It is stored per game *and* per
intent, so agreeing that Hades may be closed for sleep is not agreement that it
may be closed for a disconnect -- the two cost the player different things, and
consent to the cheaper one is not consent to the dearer one. It also never
transfers to another game: a preference whose app id does not match the running
game is not a near miss to be tolerated, it is evidence the caller is confused,
and it is refused rather than applied.

One case overrides the player, and only one: a game the catalog has reviewed
evidence *loses progress* on close is confirmed every time, and the "do not ask
again" box is not offered for it. That prompt is not there to collect consent
already given; it is there because at that moment it carries something the
player needs to act on -- save first -- and a box ticked last week cannot carry
it.

Pure. This closes nothing, observes nothing and remembers nothing; it maps
facts a caller has already gathered onto a decision and the facts a prompt must
show. It emits codes, not sentences: the words a player reads have one owner on
the delivery side, and duplicating them here would create a second.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .game_compatibility import GameSaveCapability


class InterruptIntent(StrEnum):
    """What the player asked for, which is about to end their game."""

    #: Remove the eGPU in software while the handheld stays powered.
    DISCONNECT = "disconnect"
    #: Suspend the handheld.
    SLEEP = "sleep"


#: Capabilities the catalog has *reviewed evidence* about that say closing this
#: game costs progress. These are not the absence of knowledge -- that is
#: ``UNTESTED`` -- they are knowledge that the answer is bad.
PROGRESS_AT_RISK: frozenset[GameSaveCapability] = frozenset(
    {
        GameSaveCapability.MANUAL_SAVE_REQUIRED,
        GameSaveCapability.UNSAFE_UNKNOWN,
    }
)

#: Capabilities the catalog has reviewed evidence about that say closing this
#: game keeps progress.
PROGRESS_SAFE: frozenset[GameSaveCapability] = frozenset(
    {
        GameSaveCapability.VERIFIED_TRIGGERABLE_AUTOSAVE,
        GameSaveCapability.VERIFIED_SAVE_ON_EXIT,
        GameSaveCapability.GRACEFUL_EXIT_VERIFIED,
    }
)


@dataclass(frozen=True, slots=True)
class RunningGame:
    """The game holding the eGPU, as far as it could be established.

    ``identity_exact`` is separate from being non-None on purpose. Something is
    rendering either way; the difference is whether Re-Gear can say what, and a
    caller that cannot say what must not act as though it can.
    """

    steam_app_id: str
    #: From the reviewed catalog when it holds this game, otherwise empty. A
    #: caller resolves a display name itself rather than being handed a guess.
    title: str
    save_capability: GameSaveCapability
    #: Whether the running game was identified exactly, rather than inferred.
    identity_exact: bool = True

    @property
    def save_known(self) -> bool:
        """Whether the catalog says how this game handles being closed."""
        return self.save_capability is not GameSaveCapability.UNTESTED


@dataclass(frozen=True, slots=True)
class GameClosePreference:
    """A player's standing answer, for one game and one intent.

    Both keys are load-bearing. Without the app id a preference would leak onto
    the next game the player launches; without the intent, agreeing to lose a
    session to sleep would silently agree to lose one to a disconnect.
    """

    steam_app_id: str
    intent: InterruptIntent
    #: Close without asking again for this game and this intent.
    skip_confirmation: bool = False
    #: Reopen the game once the action has finished.
    relaunch_after: bool = False


class ConsentDecision(StrEnum):
    #: No game is running, over a scan that finished: nothing to close.
    NOTHING_TO_CLOSE = "nothing_to_close"
    #: Ask the player before closing anything.
    CONFIRM = "confirm"
    #: The player has already agreed, for this game and this intent.
    REMEMBERED = "remembered"


@dataclass(frozen=True, slots=True)
class GameClosePrompt:
    """What a caller must do next, and what a prompt has to show if it asks.

    The fields are facts, not sentences. Whether a checkbox appears, whether a
    relaunch is on offer and how urgent the save warning is are decisions; the
    English that expresses them belongs to the delivery layer, which already
    owns every other player-facing string.
    """

    decision: ConsentDecision
    #: Why, in a token a caller can branch on and a bug report can carry.
    code: str
    intent: InterruptIntent
    game: RunningGame | None = None
    #: Whether closing this game is known to cost progress.
    progress_at_risk: bool = False
    #: Whether the catalog has reviewed evidence either way.
    save_known: bool = False
    #: Whether to offer "do not ask again for this game".
    remember_offered: bool = False
    #: Whether to offer reopening the game afterwards.
    relaunch_offered: bool = False
    #: Whether the player has already asked for a relaunch afterwards.
    relaunch_requested: bool = False

    @property
    def may_proceed_without_asking(self) -> bool:
        """Whether a caller may act with no further player interaction."""
        return self.decision in (
            ConsentDecision.NOTHING_TO_CLOSE,
            ConsentDecision.REMEMBERED,
        )


def decide_game_close(
    intent: InterruptIntent,
    game: RunningGame | None,
    preference: GameClosePreference | None = None,
    *,
    scan_complete: bool = True,
) -> GameClosePrompt:
    """Decide whether to ask, and what the asking must show.

    ``game`` of None means no game is running, and only that. It must never be
    used to mean "we could not tell": a caller whose scan did not finish says
    so with ``scan_complete`` false, and a caller that saw a game but could not
    name it passes a ``RunningGame`` with ``identity_exact`` false. Both are
    asked about, because an unfinished look is not evidence of an empty screen
    and an unnamed game still has a save to lose.
    """

    if game is None:
        if not scan_complete:
            return GameClosePrompt(
                ConsentDecision.CONFIRM,
                "game_close.scan_incomplete",
                intent,
            )
        return GameClosePrompt(
            ConsentDecision.NOTHING_TO_CLOSE,
            "game_close.no_game_running",
            intent,
        )

    at_risk = game.save_capability in PROGRESS_AT_RISK
    # An unidentified game is asked about every time. There is nothing to match
    # a remembered answer against, and nothing to reopen afterwards.
    if not game.identity_exact:
        return GameClosePrompt(
            ConsentDecision.CONFIRM,
            "game_close.identity_unverified",
            intent,
            game=game,
            progress_at_risk=at_risk,
            save_known=game.save_known,
        )

    remember_offered = not at_risk
    base = GameClosePrompt(
        ConsentDecision.CONFIRM,
        "game_close.confirmation_required",
        intent,
        game=game,
        progress_at_risk=at_risk,
        save_known=game.save_known,
        remember_offered=remember_offered,
        relaunch_offered=True,
    )

    if preference is None:
        return base

    # A preference for another game, or for the other intent, is not a weaker
    # match to be applied cautiously. It is a caller handing over the wrong
    # record, and applying any part of it -- including the relaunch box -- would
    # act on an answer the player gave about something else.
    if preference.steam_app_id != game.steam_app_id:
        return _replace_code(base, "game_close.preference_game_mismatch")
    if preference.intent is not intent:
        return _replace_code(base, "game_close.preference_intent_mismatch")

    if at_risk:
        # Reviewed evidence says progress is lost. The prompt stands, and the
        # box that would have skipped it was never offered, so a stored skip is
        # either stale or was written around this rule.
        return GameClosePrompt(
            ConsentDecision.CONFIRM,
            "game_close.progress_at_risk",
            intent,
            game=game,
            progress_at_risk=True,
            save_known=game.save_known,
            remember_offered=False,
            relaunch_offered=True,
            relaunch_requested=preference.relaunch_after,
        )

    if not preference.skip_confirmation:
        return GameClosePrompt(
            ConsentDecision.CONFIRM,
            "game_close.confirmation_required",
            intent,
            game=game,
            progress_at_risk=False,
            save_known=game.save_known,
            remember_offered=True,
            relaunch_offered=True,
            relaunch_requested=preference.relaunch_after,
        )

    return GameClosePrompt(
        ConsentDecision.REMEMBERED,
        "game_close.player_agreed_for_this_game",
        intent,
        game=game,
        progress_at_risk=False,
        save_known=game.save_known,
        remember_offered=True,
        relaunch_offered=True,
        relaunch_requested=preference.relaunch_after,
    )


def _replace_code(prompt: GameClosePrompt, code: str) -> GameClosePrompt:
    return GameClosePrompt(
        prompt.decision,
        code,
        prompt.intent,
        game=prompt.game,
        progress_at_risk=prompt.progress_at_risk,
        save_known=prompt.save_known,
        remember_offered=prompt.remember_offered,
        relaunch_offered=prompt.relaunch_offered,
        relaunch_requested=prompt.relaunch_requested,
    )
