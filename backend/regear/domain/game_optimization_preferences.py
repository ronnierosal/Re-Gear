"""What the player asked for: automatic game optimization, globally and per game.

Two layers, one rule. A global switch says whether Re-Gear optimizes games at
all; a per-game choice says what one game does under it:

* ``INHERIT``   -- follow the global switch (the state of every game not
  mentioned);
* ``AUTOMATIC`` -- the player opted this game in;
* ``MANUAL``    -- the player manages this game themselves.

The global switch is a master switch. Off means off: a per-game AUTOMATIC does
not outvote it, and nothing pending survives it. That is what makes "turn it
off" something a player can trust without auditing every game.

Turning optimization off never rewrites a setting. Restore My Settings is a
separate, explicit engine operation, and this module has no opinion about it.

Preferences that cannot be believed -- a corrupt or unrecognised record -- are
not "off" and are not "on": they are *untrusted*, and untrusted withholds all
automatic management. Guessing either way would be the store deciding for the
player.

Everything here is pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from .game_compatibility import STEAM_APP_ID_RE
from .mode_profiles import ExperienceTarget


PREFERENCES_VERSION = 1
#: A large library's worth of explicit choices. Games never mentioned inherit,
#: so the bound limits only explicit choices.
MAX_GAME_PREFERENCES = 512
#: Nothing stored yet means opted out. Changing this default is a product
#: decision for Ronnie and the primary, not a storage detail.
DEFAULT_GLOBAL_ENABLED = False
DEFAULT_PREFERENCE = ExperienceTarget.BALANCED


class GameChoice(StrEnum):
    INHERIT = "inherit"
    AUTOMATIC = "automatic"
    MANUAL = "manual"


class IntentReason(StrEnum):
    """Why a game is, or is not, automatically managed right now."""

    AUTOMATIC_INHERITED = "intent.automatic_inherited"
    AUTOMATIC_CHOSEN = "intent.automatic_chosen"
    GLOBAL_DISABLED = "intent.global_disabled"
    GAME_MANUAL = "intent.game_manual"
    PREFERENCES_UNTRUSTED = "intent.preferences_untrusted"


@dataclass(frozen=True, slots=True)
class GamePreference:
    choice: GameChoice = GameChoice.INHERIT
    #: None follows the global preference.
    preference: ExperienceTarget | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.choice, GameChoice):
            raise ValueError("a game choice is inherit, automatic or manual")
        if self.preference is not None and not isinstance(self.preference, ExperienceTarget):
            raise ValueError("a game preference is an experience target")

    @property
    def is_default(self) -> bool:
        return self.choice is GameChoice.INHERIT and self.preference is None


@dataclass(frozen=True, slots=True)
class OptimizationPreferences:
    global_enabled: bool = DEFAULT_GLOBAL_ENABLED
    default_preference: ExperienceTarget = DEFAULT_PREFERENCE
    games: Mapping[str, GamePreference] = field(default_factory=dict)
    #: Increases on every stored change. Lets a writer refuse to overwrite a
    #: change it has not seen, instead of silently losing it.
    revision: int = 0

    def __post_init__(self) -> None:
        if type(self.global_enabled) is not bool:
            raise ValueError("global enablement is a boolean")
        if not isinstance(self.default_preference, ExperienceTarget):
            raise ValueError("the default preference is an experience target")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 0:
            raise ValueError("preference revision is a non-negative integer")
        games = dict(self.games)
        if len(games) > MAX_GAME_PREFERENCES:
            raise ValueError("too many per-game preferences")
        for app_id, preference in games.items():
            if not isinstance(app_id, str) or not STEAM_APP_ID_RE.fullmatch(app_id):
                raise ValueError("a per-game preference needs a Steam app id")
            if not isinstance(preference, GamePreference):
                raise ValueError("a per-game preference is a GamePreference")
        object.__setattr__(self, "games", games)

    def game(self, steam_app_id: str) -> GamePreference:
        return self.games.get(steam_app_id, GamePreference())

    def with_global(self, enabled: bool) -> OptimizationPreferences:
        return OptimizationPreferences(
            enabled, self.default_preference, self.games, self.revision + 1
        )

    def with_default_preference(self, preference: ExperienceTarget) -> OptimizationPreferences:
        return OptimizationPreferences(
            self.global_enabled, preference, self.games, self.revision + 1
        )

    def with_game(self, steam_app_id: str, preference: GamePreference) -> OptimizationPreferences:
        """Set one game's choice. Returning a game to INHERIT drops its entry."""
        if not STEAM_APP_ID_RE.fullmatch(steam_app_id):
            raise ValueError("a per-game preference needs a Steam app id")
        games = dict(self.games)
        games.pop(steam_app_id, None)
        if not preference.is_default:
            if len(games) >= MAX_GAME_PREFERENCES:
                # Refused rather than evicting: dropping another game's
                # explicit MANUAL would silently re-enable management there.
                raise ValueError("too many per-game preferences")
            games[steam_app_id] = preference
        return OptimizationPreferences(
            self.global_enabled, self.default_preference, games, self.revision + 1
        )


@dataclass(frozen=True, slots=True)
class EffectiveIntent:
    """The single answer a launch path needs: manage this game, and how."""

    steam_app_id: str
    automatic: bool
    preference: ExperienceTarget
    reason: IntentReason


def resolve_intent(
    preferences: OptimizationPreferences | None, steam_app_id: str
) -> EffectiveIntent:
    """The effective intent for one game. ``None`` means untrusted preferences."""
    if preferences is None:
        return EffectiveIntent(
            steam_app_id, False, DEFAULT_PREFERENCE, IntentReason.PREFERENCES_UNTRUSTED
        )
    game = preferences.game(steam_app_id)
    preference = game.preference or preferences.default_preference
    if not preferences.global_enabled:
        return EffectiveIntent(steam_app_id, False, preference, IntentReason.GLOBAL_DISABLED)
    if game.choice is GameChoice.MANUAL:
        return EffectiveIntent(steam_app_id, False, preference, IntentReason.GAME_MANUAL)
    if game.choice is GameChoice.AUTOMATIC:
        return EffectiveIntent(steam_app_id, True, preference, IntentReason.AUTOMATIC_CHOSEN)
    return EffectiveIntent(steam_app_id, True, preference, IntentReason.AUTOMATIC_INHERITED)
