"""Per-game graphics profiles: what Re-Gear may change, and the pure plan.

A profile is a statement of intent about a small, named set of keys in one
game's configuration. It is never evidence that the game is installed, that the
file exists, that the keys exist, or that a mode change happened. Planning is
pure: it takes an already-parsed document and a profile and answers what would
change. Nothing here reads, writes or authorizes anything.

Two support tiers, and nothing between them. MANAGED means every managed key is
present in the document and every requested value passes the key's own
validator. ADVISOR means Re-Gear tells the player what to change and writes
nothing. A partially applied profile is not a tier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from .graphics_config_format import ConfigDocument, KEY_RE, split_address
from .graphics_schema import SchemaAssessment
from .models import OperatingMode


#: The modes a profile may bind. Unknown and degraded are deliberately absent:
#: an unrecognised placement must never select settings for a player. Boosted
#: handheld is bindable, but only where a game adapter declares a translation
#: for it -- the vocabulary existing is not permission to invent values.
SUPPORTED_MODES = (
    OperatingMode.PORTABLE,
    OperatingMode.BOOSTED_HANDHELD,
    OperatingMode.TV_DOCKED,
)

VALUE_RE = re.compile(r"^[^\r\n\x00]{0,256}$")
MAX_MANAGED_KEYS = 32


class ValueKind(StrEnum):
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ENUMERATED = "enumerated"


class SupportTier(StrEnum):
    """Support level 0, 1 and 2, in the assignment's vocabulary.

    UNKNOWN is not a degenerate ADVISOR: Advisor means Re-Gear knows what to
    tell the player to change, Unknown means it does not even recognise the
    file. Both write nothing; only one can give advice.
    """

    UNKNOWN = "unknown"
    ADVISOR = "advisor"
    MANAGED = "managed"


class PlanRefusal(StrEnum):
    """Why a profile cannot be applied as a managed write."""

    KEY_ABSENT = "graphics_profile.key_absent"
    VALUE_REJECTED = "graphics_profile.value_rejected"
    MODE_UNSUPPORTED = "graphics_profile.mode_unsupported"
    SCHEMA_UNRECOGNISED = "graphics_profile.schema_unrecognised"
    CURRENT_VALUE_UNSUPPORTED = "graphics_profile.current_value_unsupported"


@dataclass(frozen=True, slots=True)
class ManagedKey:
    """One key Re-Gear is allowed to rewrite, and the values it may hold."""

    section: str
    key: str
    kind: ValueKind
    allowed: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None

    def __post_init__(self) -> None:
        if not KEY_RE.fullmatch(self.key):
            raise ValueError("managed key name is invalid")
        # Validates the section and raises for a malformed one.
        split_address(self.address)
        if self.kind is ValueKind.ENUMERATED and not self.allowed:
            raise ValueError("an enumerated managed key needs allowed values")
        if self.kind is not ValueKind.ENUMERATED and self.allowed:
            raise ValueError("allowed values belong to enumerated keys only")
        if self.kind is ValueKind.INTEGER:
            if self.minimum is None or self.maximum is None:
                raise ValueError("an integer managed key needs a bounded range")
            if self.minimum > self.maximum:
                raise ValueError("integer managed key range is inverted")
        elif self.minimum is not None or self.maximum is not None:
            raise ValueError("a range belongs to integer keys only")

    @property
    def address(self) -> str:
        return f"{self.section}/{self.key}"

    def accepts(self, value: str) -> bool:
        """Whether this key may hold that exact literal."""
        if not isinstance(value, str) or not VALUE_RE.fullmatch(value):
            return False
        if self.kind is ValueKind.ENUMERATED:
            return value in self.allowed
        if self.kind is ValueKind.BOOLEAN:
            return value in ("0", "1", "true", "false", "True", "False")
        stripped = value.strip()
        if not re.fullmatch(r"-?[0-9]{1,9}", stripped):
            return False
        number = int(stripped)
        assert self.minimum is not None and self.maximum is not None
        return self.minimum <= number <= self.maximum


@dataclass(frozen=True, slots=True)
class GraphicsProfile:
    """The settings one game should have in one mode.

    A profile is versioned and bound to a schema. Both travel with every write
    Re-Gear records, so a profile written by an older Re-Gear against an older
    game layout is recognisable as such later rather than assumed compatible.
    """

    steam_app_id: str
    mode: OperatingMode
    config_filename: str
    settings: Mapping[str, str]
    profile_version: int = 1
    schema_id: str = ""

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[1-9][0-9]{0,9}", self.steam_app_id):
            raise ValueError("graphics profile Steam AppID is invalid")
        if not isinstance(self.profile_version, int) or self.profile_version < 1:
            raise ValueError("graphics profile version is invalid")
        if self.mode not in SUPPORTED_MODES:
            raise ValueError("graphics profile mode is not supported")
        if not self.config_filename or "/" in self.config_filename:
            raise ValueError("graphics profile config filename is invalid")
        if not self.settings:
            raise ValueError("graphics profile names no settings")
        if len(self.settings) > MAX_MANAGED_KEYS:
            raise ValueError("graphics profile manages too many keys")
        for key_address in self.settings:
            split_address(key_address)

    @property
    def managed_addresses(self) -> tuple[str, ...]:
        return tuple(sorted(self.settings))


@dataclass(frozen=True, slots=True)
class ProfilePlan:
    """What applying a profile to one document would do, and whether it may."""

    tier: SupportTier
    changes: Mapping[str, str]
    unchanged: tuple[str, ...]
    refusals: tuple[tuple[str, PlanRefusal], ...]
    advice: tuple[str, ...] = ()

    @property
    def writes_anything(self) -> bool:
        return self.tier is SupportTier.MANAGED and bool(self.changes)


def plan_application(
    document: ConfigDocument,
    profile: GraphicsProfile,
    managed_keys: Mapping[str, ManagedKey],
    schema: SchemaAssessment | None = None,
) -> ProfilePlan:
    """Decide, purely, what this profile would change in this document.

    The schema assessment comes first. Without a matched schema the support
    level is UNKNOWN and no advice is offered about individual keys, because an
    unrecognised file is one whose keys Re-Gear cannot claim to understand.

    After that, any single key that is absent or holds a rejected value drops
    the whole profile to Advisor. Applying the half that happens to be valid
    would leave the game in a combination the player never chose and Re-Gear
    cannot name.
    """
    if profile.mode not in SUPPORTED_MODES:
        return ProfilePlan(
            SupportTier.ADVISOR,
            {},
            (),
            ((profile.config_filename, PlanRefusal.MODE_UNSUPPORTED),),
            ("Re-Gear only adjusts graphics settings for placements it recognises.",),
        )
    if schema is None or not schema.matched:
        detail = schema.detail if schema is not None else "no schema was assessed"
        return ProfilePlan(
            SupportTier.UNKNOWN,
            {},
            (),
            ((profile.config_filename, PlanRefusal.SCHEMA_UNRECOGNISED),),
            (
                "Re-Gear does not recognise this game's configuration layout "
                f"({detail}); change these settings in the game itself.",
            ),
        )
    present = document.values()
    changes: dict[str, str] = {}
    unchanged: list[str] = []
    refusals: list[tuple[str, PlanRefusal]] = []
    advice: list[str] = []
    for key_address in profile.managed_addresses:
        requested = profile.settings[key_address]
        definition = managed_keys.get(key_address)
        if definition is None or not definition.accepts(requested):
            refusals.append((key_address, PlanRefusal.VALUE_REJECTED))
            advice.append(f"{key_address}: Re-Gear will not write {requested!r}.")
            continue
        if key_address not in present:
            refusals.append((key_address, PlanRefusal.KEY_ABSENT))
            advice.append(
                f"{key_address}: set this to {requested!r} in the game's own "
                "settings; Re-Gear does not add keys a game never wrote."
            )
            continue
        if not definition.accepts(present[key_address]):
            # The file holds something this adapter cannot describe. Rewriting
            # it would discard a value Re-Gear never understood.
            refusals.append((key_address, PlanRefusal.CURRENT_VALUE_UNSUPPORTED))
            advice.append(
                f"{key_address}: currently {present[key_address]!r}, which Re-Gear "
                "does not recognise, so it will not be replaced."
            )
            continue
        if present[key_address] == requested:
            unchanged.append(key_address)
        else:
            changes[key_address] = requested
    if refusals:
        return ProfilePlan(SupportTier.ADVISOR, {}, tuple(unchanged), tuple(refusals), tuple(advice))
    return ProfilePlan(SupportTier.MANAGED, changes, tuple(unchanged), (), ())


def verify_application(
    document: ConfigDocument,
    profile: GraphicsProfile,
    before_remainder: Mapping[str, str],
) -> tuple[bool, tuple[str, ...]]:
    """Check a re-read document really holds the profile and nothing else moved."""
    problems: list[str] = []
    values = document.values()
    for key_address, expected in profile.settings.items():
        actual = values.get(key_address)
        if actual != expected:
            problems.append(f"{key_address}: expected {expected!r}, found {actual!r}")
    managed = set(profile.settings)
    after_remainder = {
        key_address: value
        for key_address, value in values.items()
        if key_address not in managed
    }
    if after_remainder != dict(before_remainder):
        moved = sorted(
            set(after_remainder) ^ set(before_remainder)
            | {
                key_address
                for key_address in set(after_remainder) & set(before_remainder)
                if after_remainder[key_address] != before_remainder[key_address]
            }
        )
        problems.append("unmanaged settings changed: " + ", ".join(moved))
    return (not problems, tuple(problems))
