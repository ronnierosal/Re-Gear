"""First-run setup states for external frame generation, from supplied facts.

This is the specification for what a future setup screen says, expressed as a
model rather than a UI. It never looks anything up: no Steam store query, no
library scan, no filesystem probe, no installer. The caller supplies what it
knows, and an unknown fact stays unknown -- "Re-Gear could not tell" is a
different message from "this is missing", and conflating them would send a
player to buy something they already own.

Two ideas are kept apart everywhere:

* **installed** means the pieces appear to be present;
* **validated** means a specific game was measured working in a specific
  context.

Installing everything never makes a game validated. The best a correct
installation reaches on its own is INSTALLED_UNVALIDATED. The only
eligible state this milestone can produce is ELIGIBLE_FIXTURE_CONFIGURATION,
which is scoped to synthetic fixtures by name, and is never real-game support.

Ownership and installation are the player's. Re-Gear does not purchase,
install, download, unpack or redistribute Lossless Scaling or LSFG-VK; each
state's guidance tells the player what to do themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .frame_generation_provider import LSFG_VK_VERSION


class SetupState(StrEnum):
    #: Not enough was supplied to say anything.
    UNKNOWN = "framegen_setup.unknown"
    #: Lossless Scaling is not owned/installed (Re-Gear cannot tell which).
    LOSSLESS_SCALING_MISSING = "framegen_setup.lossless_scaling_missing"
    #: Lossless Scaling is present but its lsfg-vk component is not.
    LSFG_COMPONENT_MISSING = "framegen_setup.lsfg_component_missing"
    #: The Linux layer is not installed, or not visible where games run.
    LINUX_COMPONENT_MISSING = "framegen_setup.linux_component_missing"
    #: Installed, but not the version Re-Gear's configuration targets.
    VERSION_MISMATCH = "framegen_setup.version_mismatch"
    #: Everything appears present; no game is validated for it here.
    INSTALLED_UNVALIDATED = "framegen_setup.installed_unvalidated"
    #: A synthetic fixture configuration is eligible. Never a real game.
    ELIGIBLE_FIXTURE_CONFIGURATION = "framegen_setup.eligible_fixture_configuration"


@dataclass(frozen=True, slots=True)
class SetupFacts:
    """What the caller established. ``None`` always means "not known"."""

    lossless_scaling_installed: bool | None = None
    #: Whether Lossless Scaling's lsfg-vk component (``lsfg-vk.dll``) is present.
    lsfg_component_present: bool | None = None
    linux_component_present: bool | None = None
    linux_component_version: str | None = None
    #: Whether the layer is visible inside Steam's runtime for the game's bitness.
    layer_visible_to_games: bool | None = None
    #: Whether a validated compatibility record exists for the game in question.
    validated_record_available: bool = False
    #: True only for synthetic fixtures. Real games are never "fixture".
    fixture: bool = False


@dataclass(frozen=True, slots=True)
class SetupAssessment:
    state: SetupState
    installed: bool
    validated: bool
    fixture_only: bool
    next_steps: tuple[str, ...]
    unknown: tuple[str, ...] = ()


def assess_setup(facts: SetupFacts, expected_version: str = LSFG_VK_VERSION) -> SetupAssessment:
    """Name the first thing standing between the player and a validated setup."""
    unknown = tuple(
        name
        for name, value in (
            ("lossless_scaling_installed", facts.lossless_scaling_installed),
            ("lsfg_component_present", facts.lsfg_component_present),
            ("linux_component_present", facts.linux_component_present),
            ("layer_visible_to_games", facts.layer_visible_to_games),
        )
        if value is None
    )

    if facts.lossless_scaling_installed is False:
        return _assessment(
            SetupState.LOSSLESS_SCALING_MISSING,
            unknown,
            "Buy and install Lossless Scaling from Steam yourself. Re-Gear does not "
            "purchase, download or install it.",
        )
    if facts.lsfg_component_present is False:
        return _assessment(
            SetupState.LSFG_COMPONENT_MISSING,
            unknown,
            "In Steam, switch Lossless Scaling to the lsfg-vk branch its Linux "
            "documentation names, so the lsfg-vk component is installed.",
        )
    if facts.linux_component_present is False or facts.layer_visible_to_games is False:
        return _assessment(
            SetupState.LINUX_COMPONENT_MISSING,
            unknown,
            "Install the LSFG-VK Linux component yourself, following its own "
            "instructions, so that it is visible to games launched by Steam.",
        )
    if (
        facts.linux_component_present
        and facts.linux_component_version is not None
        and facts.linux_component_version != expected_version
    ):
        return _assessment(
            SetupState.VERSION_MISMATCH,
            unknown,
            f"Re-Gear's configuration targets LSFG-VK {expected_version}; the "
            f"installed component reports {facts.linux_component_version}. "
            "Re-Gear will not generate configuration for a version it does not target.",
        )
    if unknown or facts.linux_component_version is None:
        missing = unknown + (
            ("linux_component_version",) if facts.linux_component_version is None else ()
        )
        return _assessment(
            SetupState.UNKNOWN,
            missing,
            "Re-Gear could not confirm every part of the setup. Nothing is assumed "
            "missing and nothing is assumed present.",
        )

    # Everything that can be installed appears to be installed.
    if facts.fixture and facts.validated_record_available:
        # Validated *within fixture scope*: fixture_only says how far that goes.
        return SetupAssessment(
            SetupState.ELIGIBLE_FIXTURE_CONFIGURATION,
            installed=True,
            validated=True,
            fixture_only=True,
            next_steps=(
                "A synthetic fixture configuration is eligible for an inert plan. "
                "This is not support for any real game.",
            ),
        )
    if facts.validated_record_available:
        # A real game cannot reach an eligible state in this milestone: real-game
        # validation is a supervised gate that has not happened. Reporting it
        # as eligible because a record claims so would be the first real-game
        # support claim, made by a model rather than by evidence review.
        step = (
            "The components appear to be installed and a record exists, but "
            "real-game validation is a supervised gate this build does not "
            "pass on its own; frame generation stays off."
        )
    else:
        step = (
            "The components appear to be installed. No game is validated for "
            "frame generation here yet, so Re-Gear will not turn it on "
            "automatically; installation is not validation."
        )
    return SetupAssessment(
        SetupState.INSTALLED_UNVALIDATED,
        installed=True,
        validated=False,
        fixture_only=False,
        next_steps=(step,),
    )


def _assessment(
    state: SetupState, unknown: tuple[str, ...], step: str
) -> SetupAssessment:
    return SetupAssessment(
        state,
        installed=False,
        validated=False,
        fixture_only=False,
        next_steps=(step,),
        unknown=unknown,
    )
