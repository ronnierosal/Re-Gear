"""Inert APU power-mode intent and observed-state contracts.

These values never dispatch work.  Selection and persistence describe player
preference; an explicit request records only what the player asked for against
the generation they observed.  Runtime ownership, admission and writes remain
the responsibility of the existing TDP control plane.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum

from .auto_tdp import AutoTdpPolicy


class PowerMode(StrEnum):
    BATTERY_SAVER = "battery_saver"
    BALANCED = "balanced"
    PERFORMANCE = "performance"
    AUTO = "auto"
    SYSTEM_CONTROL = "system_control"


class PowerRequestKind(StrEnum):
    ACTIVATE_SELECTED = "activate_selected"
    STOP_AUTO_KEEP_LIMIT = "stop_auto_keep_limit"
    DISABLE_REGEAR_CONDITIONAL_RESTORE = "disable_regear_conditional_restore"
    RESTORE_PREVIOUS = "restore_previous"


class PowerModePhase(StrEnum):
    IDLE = "idle"
    APPLYING = "applying"
    ACTIVE = "active"
    PAUSED = "paused"
    UNSUPPORTED = "unsupported"
    CONFLICT = "conflict"
    RECOVERY = "recovery"
    UNKNOWN = "unknown"


class PassivePowerEvent(StrEnum):
    PREFERENCE_LOADED = "preference_loaded"
    MENU_REFRESHED = "menu_refreshed"
    RESUMED = "resumed"
    CONTEXT_CHANGED = "context_changed"


def _identifier(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} is required")


def _positive_int(value: object, label: str) -> None:
    if type(value) is not int or not 0 < value <= 0xFFFFFFFF:
        raise ValueError(f"{label} must be a positive unsigned integer")


def _optional_positive_number(value: object, label: str) -> None:
    if value is None:
        return
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be finite and positive")


@dataclass(frozen=True, slots=True)
class PowerModePreference:
    selected: PowerMode
    auto_policy: AutoTdpPolicy | None = None

    def __post_init__(self) -> None:
        if type(self.selected) is not PowerMode:
            raise ValueError("power mode preference is invalid")
        if self.selected is PowerMode.AUTO:
            if type(self.auto_policy) is not AutoTdpPolicy:
                raise ValueError("Auto preference requires a validated Auto TDP policy")
        elif self.auto_policy is not None:
            raise ValueError("Auto TDP policy belongs only to Auto preference")

    @property
    def authorizes_activation(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class PowerModeRequest:
    kind: PowerRequestKind
    observed_generation: int
    requested_mode: PowerMode | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not PowerRequestKind:
            raise ValueError("power request kind is invalid")
        _positive_int(self.observed_generation, "observed generation")
        if self.kind is PowerRequestKind.ACTIVATE_SELECTED:
            if type(self.requested_mode) is not PowerMode:
                raise ValueError("activation request requires an explicit mode")
        elif self.requested_mode is not None:
            raise ValueError("control requests do not carry an implicit mode")

    @property
    def authorizes_activation(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class LastVerifiedPowerReceipt:
    receipt_id: str
    generation: int
    effective_mode: PowerMode
    configured_limit_watts: int

    def __post_init__(self) -> None:
        _identifier(self.receipt_id, "receipt ID")
        _positive_int(self.generation, "receipt generation")
        if type(self.effective_mode) is not PowerMode:
            raise ValueError("receipt effective mode is invalid")
        _positive_int(self.configured_limit_watts, "configured limit")


@dataclass(frozen=True, slots=True)
class RestorationBaseline:
    generation: int
    configured_limit_watts: int
    evidence_id: str

    def __post_init__(self) -> None:
        _positive_int(self.generation, "baseline generation")
        _positive_int(self.configured_limit_watts, "baseline configured limit")
        _identifier(self.evidence_id, "baseline evidence ID")


@dataclass(frozen=True, slots=True)
class PowerModeState:
    """Presentation state; configured limit is not measured package power."""

    selected: PowerMode
    generation: int
    phase: PowerModePhase = PowerModePhase.IDLE
    requested: PowerMode | None = None
    observed_effective: PowerMode | None = None
    verified_effective: PowerMode | None = None
    configured_limit_watts: int | None = None
    measured_package_watts: float | None = None
    last_verified: LastVerifiedPowerReceipt | None = None
    restoration_baseline: RestorationBaseline | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if type(self.selected) is not PowerMode:
            raise ValueError("selected power mode is invalid")
        _positive_int(self.generation, "state generation")
        if type(self.phase) is not PowerModePhase:
            raise ValueError("power mode phase is invalid")
        if self.requested is not None and type(self.requested) is not PowerMode:
            raise ValueError("requested power mode is invalid")
        if self.observed_effective is not None and type(self.observed_effective) is not PowerMode:
            raise ValueError("observed effective power mode is invalid")
        if self.verified_effective is not None and type(self.verified_effective) is not PowerMode:
            raise ValueError("verified effective power mode is invalid")
        if self.configured_limit_watts is not None:
            _positive_int(self.configured_limit_watts, "configured limit")
        _optional_positive_number(self.measured_package_watts, "measured package power")
        if self.last_verified is not None:
            if type(self.last_verified) is not LastVerifiedPowerReceipt:
                raise ValueError("last verified receipt is invalid")
            if self.last_verified.generation > self.generation:
                raise ValueError("last verified receipt is from a future generation")
            if (
                self.verified_effective is not None
                and (
                    self.last_verified.generation != self.generation
                    or self.last_verified.effective_mode is not self.verified_effective
                )
            ):
                raise ValueError("verified effective mode needs a current matching receipt")
        elif self.verified_effective is not None:
            raise ValueError("verified effective mode requires a verification receipt")
        if self.restoration_baseline is not None:
            if type(self.restoration_baseline) is not RestorationBaseline:
                raise ValueError("restoration baseline is invalid")
            if self.restoration_baseline.generation > self.generation:
                raise ValueError("restoration baseline is from a future generation")
        if self.phase in (PowerModePhase.RECOVERY, PowerModePhase.UNKNOWN) and self.verified_effective is not None:
            raise ValueError("unknown or recovery state cannot claim a verified effective mode")

    @property
    def authorizes_activation(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class PassivePowerUpdate:
    state: PowerModeState
    event: PassivePowerEvent
    request: None = None

    @property
    def authorizes_activation(self) -> bool:
        return False


def observe_passive_power_event(
    state: PowerModeState,
    event: PassivePowerEvent,
    *,
    selected: PowerMode | None = None,
    new_generation: int | None = None,
) -> PassivePowerUpdate:
    """Apply passive data without synthesizing a live request.

    Resume and context changes are admission boundaries.  They advance the
    observed generation and discard current observations/verification while
    retaining the player's selected/requested intent and historical restoration
    baseline.  Fresh runtime evidence is required to claim an effective mode.
    """
    if type(state) is not PowerModeState or type(event) is not PassivePowerEvent:
        raise ValueError("passive power update input is invalid")
    if selected is not None and type(selected) is not PowerMode:
        raise ValueError("passive selection is invalid")
    updated = replace(state, selected=selected) if selected is not None else state
    invalidates_context = event in {
        PassivePowerEvent.RESUMED,
        PassivePowerEvent.CONTEXT_CHANGED,
    }
    if invalidates_context:
        _positive_int(new_generation, "new context generation")
        if new_generation <= state.generation:
            raise ValueError("new context generation must advance")
        updated = replace(
            updated,
            generation=new_generation,
            phase=PowerModePhase.PAUSED,
            observed_effective=None,
            verified_effective=None,
            configured_limit_watts=None,
            measured_package_watts=None,
            last_verified=None,
            reason=f"power_mode.{event.value}_requires_fresh_evidence",
        )
    elif new_generation is not None:
        raise ValueError("generation changes require a resume or context event")
    return PassivePowerUpdate(updated, event)


def explicit_power_request(
    preference: PowerModePreference,
    *,
    observed_generation: int,
) -> PowerModeRequest:
    """Record a generation-bound player request; still no execution authority."""
    if type(preference) is not PowerModePreference:
        raise ValueError("validated preference is required")
    return PowerModeRequest(
        PowerRequestKind.ACTIVATE_SELECTED,
        observed_generation,
        preference.selected,
    )
