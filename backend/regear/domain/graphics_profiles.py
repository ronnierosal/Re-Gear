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
from .models import OperatingMode


#: The modes a profile may bind. Boosted handheld, unknown and degraded are
#: deliberately absent: this milestone changes settings for the two placements a
#: player explicitly recognizes, and an unknown placement must never select one.
SUPPORTED_MODES = (OperatingMode.PORTABLE, OperatingMode.TV_DOCKED)

VALUE_RE = re.compile(r"^[^\r\n\x00]{0,256}$")
MAX_MANAGED_KEYS = 32


class ValueKind(StrEnum):
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ENUMERATED = "enumerated"


class SupportTier(StrEnum):
    MANAGED = "managed"
    ADVISOR = "advisor"


class PlanRefusal(StrEnum):
    """Why a profile cannot be applied as a managed write."""

    KEY_ABSENT = "graphics_profile.key_absent"
    VALUE_REJECTED = "graphics_profile.value_rejected"
    MODE_UNSUPPORTED = "graphics_profile.mode_unsupported"


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
    """The settings one game should have in one mode."""

    steam_app_id: str
    mode: OperatingMode
    config_filename: str
    settings: Mapping[str, str]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[1-9][0-9]{0,9}", self.steam_app_id):
            raise ValueError("graphics profile Steam AppID is invalid")
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
) -> ProfilePlan:
    """Decide, purely, what this profile would change in this document.

    Any single key that is absent or holds a rejected value drops the whole
    profile to Advisor. Applying the half that happens to be valid would leave
    the game in a combination the player never chose and Re-Gear cannot name.
    """
    if profile.mode not in SUPPORTED_MODES:
        return ProfilePlan(
            SupportTier.ADVISOR,
            {},
            (),
            ((profile.config_filename, PlanRefusal.MODE_UNSUPPORTED),),
            ("Re-Gear only adjusts graphics settings for Portable and TV Docked.",),
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
