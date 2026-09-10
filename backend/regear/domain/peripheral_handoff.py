"""Pure controller/audio handoff policy with verified fallback requirements."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .control_plane import CapabilitySupport, EffectiveCapabilities


class HandoffDirection(StrEnum):
    DOCK = "dock"
    UNDOCK = "undock"
    EXTERNAL_CONTROLLER_LOST = "external_controller_lost"


class ControllerDirective(StrEnum):
    KEEP_CURRENT = "keep_current"
    PROMOTE_EXTERNAL = "promote_external"
    SUPPRESS_BUILTIN = "suppress_builtin"
    RESTORE_BUILTIN = "restore_builtin"
    PROMOTE_BUILTIN = "promote_builtin"
    DISCONNECT_EXTERNAL = "disconnect_external"
    POWER_OFF_EXTERNAL = "power_off_external"
    ACTION_REQUIRED = "action_required"


class AudioOutput(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    OTHER_PORTABLE = "other_portable"
    UNKNOWN = "unknown"


class AudioDirective(StrEnum):
    KEEP_CURRENT = "keep_current"
    SELECT_EXTERNAL = "select_external"
    RESTORE_PORTABLE = "restore_portable"
    ACTION_REQUIRED = "action_required"


_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def is_peripheral_token(value: str) -> bool:
    return bool(_TOKEN_RE.fullmatch(value))


class PeripheralPlanStatus(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    NOOP = "noop"
    ACTION_REQUIRED = "action_required"


class PeripheralMappingEvidenceKind(StrEnum):
    SUPERVISED_HARDWARE_TEST = "supervised_hardware_test"


class PeripheralStepKind(StrEnum):
    PROMOTE_EXTERNAL_CONTROLLER = "promote_external_controller"
    SELECT_EXTERNAL_AUDIO = "select_external_audio"
    SUPPRESS_BUILTIN_CONTROLLER = "suppress_builtin_controller"
    RESTORE_BUILTIN_CONTROLLER = "restore_builtin_controller"
    PROMOTE_BUILTIN_CONTROLLER = "promote_builtin_controller"
    RESTORE_PORTABLE_AUDIO = "restore_portable_audio"
    DISCONNECT_EXTERNAL_CONTROLLER = "disconnect_external_controller"
    POWER_OFF_EXTERNAL_CONTROLLER = "power_off_external_controller"


@dataclass(frozen=True, slots=True)
class ControllerPeripheralState:
    complete: bool
    exact: bool
    failure_code: str
    builtin_binding: str
    builtin_available: bool | None
    builtin_input_verified: bool
    builtin_restore_verified: bool
    external_binding: str
    external_connected: bool | None
    external_input_verified: bool

    def __post_init__(self) -> None:
        _validate_subsystem_status(self.complete, self.exact, self.failure_code)
        for value in (self.builtin_binding, self.external_binding):
            if value and not is_peripheral_token(value):
                raise ValueError("controller binding must be an opaque token")


@dataclass(frozen=True, slots=True)
class AudioPeripheralState:
    complete: bool
    exact: bool
    failure_code: str
    current_output: AudioOutput
    current_output_binding: str
    current_output_usable_verified: bool
    external_output_binding: str
    external_output_available: bool | None
    external_output_verified: bool
    portable_output_binding: str
    portable_output_available: bool | None
    portable_output_verified: bool
    rollback_output_verified: bool

    def __post_init__(self) -> None:
        _validate_subsystem_status(self.complete, self.exact, self.failure_code)
        for value in (
            self.current_output_binding,
            self.external_output_binding,
            self.portable_output_binding,
        ):
            if value and not is_peripheral_token(value):
                raise ValueError("audio binding must be an opaque token")


@dataclass(frozen=True, slots=True)
class PeripheralObservation:
    schema_version: int
    generation: str
    sample_id: str
    controller: ControllerPeripheralState
    audio: AudioPeripheralState

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("peripheral observation schema is unsupported")
        if not is_peripheral_token(self.generation) or not is_peripheral_token(
            self.sample_id
        ):
            raise ValueError("peripheral observation identity is invalid")


@dataclass(frozen=True, slots=True)
class PeripheralIdentityHints:
    """Private opaque bindings from one explicitly reviewed mapping exercise."""

    builtin_controller_binding: str = ""
    external_controller_binding: str = ""
    current_audio_binding: str = ""
    external_audio_binding: str = ""
    portable_audio_binding: str = ""

    def __post_init__(self) -> None:
        values = (
            self.builtin_controller_binding,
            self.external_controller_binding,
            self.current_audio_binding,
            self.external_audio_binding,
            self.portable_audio_binding,
        )
        if any(value and not is_peripheral_token(value) for value in values):
            raise ValueError("peripheral mapping binding must be opaque")
        if (
            self.builtin_controller_binding
            and self.builtin_controller_binding == self.external_controller_binding
        ):
            raise ValueError("built-in and external controller bindings must differ")


@dataclass(frozen=True, slots=True)
class PeripheralMappingEvidence:
    """Private reviewed mapping, bound to exactly one inventory fingerprint.

    This is identity evidence only. It is deliberately insufficient to claim a
    usable controller, a default audio output, or authority for a handoff.
    """

    mapping_id: str
    inventory_generation: str
    captured_at: str
    kind: PeripheralMappingEvidenceKind
    intentional_test: bool
    reviewed: bool
    hints: PeripheralIdentityHints

    def __post_init__(self) -> None:
        if not is_peripheral_token(self.mapping_id) or not is_peripheral_token(
            self.inventory_generation
        ):
            raise ValueError("peripheral mapping evidence identity is invalid")
        if not self.captured_at:
            raise ValueError("peripheral mapping evidence timestamp is required")
        if self.kind is not PeripheralMappingEvidenceKind.SUPERVISED_HARDWARE_TEST:
            raise ValueError("peripheral mapping evidence kind is invalid")
        if not self.intentional_test or not self.reviewed:
            raise ValueError("peripheral mapping evidence requires intentional review")
        if not any(
            (
                self.hints.builtin_controller_binding,
                self.hints.external_controller_binding,
                self.hints.current_audio_binding,
                self.hints.external_audio_binding,
                self.hints.portable_audio_binding,
            )
        ):
            raise ValueError("peripheral mapping evidence requires a binding")


def _validate_subsystem_status(complete: bool, exact: bool, failure_code: str) -> None:
    if failure_code and not is_peripheral_token(failure_code):
        raise ValueError("peripheral failure code must be categorical")
    if complete and exact:
        if failure_code:
            raise ValueError("exact peripheral state cannot carry a failure")
    elif not failure_code:
        raise ValueError("incomplete peripheral state requires a failure")


@dataclass(frozen=True, slots=True)
class PeripheralPlanStep:
    kind: PeripheralStepKind
    target_binding: str
    rollback_binding: str = ""
    verify_after: bool = True

    def __post_init__(self) -> None:
        if not is_peripheral_token(self.target_binding):
            raise ValueError("peripheral step requires an opaque target binding")
        if self.rollback_binding and not is_peripheral_token(self.rollback_binding):
            raise ValueError("peripheral rollback binding must be opaque")
        if not self.verify_after:
            raise ValueError("every peripheral step requires fresh verification")


@dataclass(frozen=True, slots=True)
class PeripheralHandoffPlan:
    status: PeripheralPlanStatus
    direction: HandoffDirection
    observed_generation: str
    observed_sample_id: str
    steps: tuple[PeripheralPlanStep, ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not is_peripheral_token(self.observed_generation) or not is_peripheral_token(
            self.observed_sample_id
        ):
            raise ValueError("peripheral plan observation identity is invalid")
        if self.status is PeripheralPlanStatus.READY and not self.steps:
            raise ValueError("ready peripheral plan requires steps")
        if self.status is PeripheralPlanStatus.PARTIAL and (
            not self.steps or not self.blockers
        ):
            raise ValueError("partial peripheral plan requires work and blockers")
        if self.status is PeripheralPlanStatus.READY and self.blockers:
            raise ValueError("ready peripheral plan cannot carry blockers")
        if self.status is PeripheralPlanStatus.NOOP and (self.steps or self.blockers):
            raise ValueError("no-op peripheral plan cannot carry work or blockers")
        if self.status is PeripheralPlanStatus.ACTION_REQUIRED and not self.blockers:
            raise ValueError("action-required peripheral plan needs blockers")

    def public_trace(self) -> dict[str, object]:
        """Expose categorical planning evidence without private bindings."""
        return {
            "schema_version": 1,
            "status": self.status.value,
            "direction": self.direction.value,
            "steps": [step.kind.value for step in self.steps],
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class ControllerHandoffObservation:
    builtin_available: bool | None
    builtin_input_verified: bool
    external_connected: bool | None
    external_input_verified: bool
    builtin_restore_verified: bool


@dataclass(frozen=True, slots=True)
class ControllerHandoffPolicy:
    suppress_builtin_when_docked: bool = False
    disconnect_external_when_undocked: bool = False
    power_off_external_when_undocked: bool = False


@dataclass(frozen=True, slots=True)
class ControllerHandoffDecision:
    directives: tuple[ControllerDirective, ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.directives:
            raise ValueError("controller handoff decision requires a directive")
        if ControllerDirective.ACTION_REQUIRED in self.directives and not self.blockers:
            raise ValueError("controller action-required decision needs blockers")
        if ControllerDirective.SUPPRESS_BUILTIN in self.directives and (
            ControllerDirective.PROMOTE_EXTERNAL not in self.directives
        ):
            raise ValueError("built-in suppression requires external promotion")


@dataclass(frozen=True, slots=True)
class AudioHandoffObservation:
    current_output: AudioOutput
    current_output_usable_verified: bool
    external_output_available: bool | None
    external_output_verified: bool
    portable_output_available: bool | None
    portable_output_verified: bool
    rollback_output_verified: bool


@dataclass(frozen=True, slots=True)
class AudioHandoffDecision:
    directives: tuple[AudioDirective, ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.directives:
            raise ValueError("audio handoff decision requires a directive")
        if AudioDirective.ACTION_REQUIRED in self.directives and not self.blockers:
            raise ValueError("audio action-required decision needs blockers")


def plan_controller_handoff(
    direction: HandoffDirection,
    observation: ControllerHandoffObservation,
    capabilities: EffectiveCapabilities,
    policy: ControllerHandoffPolicy = ControllerHandoffPolicy(),
) -> ControllerHandoffDecision:
    if direction in {HandoffDirection.UNDOCK, HandoffDirection.EXTERNAL_CONTROLLER_LOST}:
        blockers: list[str] = []
        if observation.builtin_available is not True:
            blockers.append("controller.builtin_unavailable_or_unknown")
        if not observation.builtin_input_verified:
            blockers.append("controller.builtin_input_unverified")
        if not observation.builtin_restore_verified:
            blockers.append("controller.builtin_restore_unverified")
        if blockers:
            return ControllerHandoffDecision(
                (ControllerDirective.ACTION_REQUIRED,),
                tuple(blockers),
            )
        directives = [
            ControllerDirective.RESTORE_BUILTIN,
            ControllerDirective.PROMOTE_BUILTIN,
        ]
        if direction is HandoffDirection.UNDOCK and observation.external_connected is True:
            if policy.power_off_external_when_undocked:
                if capabilities.external_controller_power_off is CapabilitySupport.VERIFIED:
                    directives.append(ControllerDirective.POWER_OFF_EXTERNAL)
                elif (
                    policy.disconnect_external_when_undocked
                    and capabilities.external_controller_disconnect is CapabilitySupport.VERIFIED
                ):
                    directives.append(ControllerDirective.DISCONNECT_EXTERNAL)
                else:
                    blockers.append(
                        "capability.external_controller_power_off_unverified"
                    )
                    if policy.disconnect_external_when_undocked:
                        blockers.append(
                            "capability.external_controller_disconnect_unverified"
                        )
            elif (
                policy.disconnect_external_when_undocked
                and capabilities.external_controller_disconnect is CapabilitySupport.VERIFIED
            ):
                directives.append(ControllerDirective.DISCONNECT_EXTERNAL)
            elif policy.disconnect_external_when_undocked:
                blockers.append(
                    "capability.external_controller_disconnect_unverified"
                )
        elif (
            direction is HandoffDirection.UNDOCK
            and observation.external_connected is None
            and (
                policy.disconnect_external_when_undocked
                or policy.power_off_external_when_undocked
            )
        ):
            blockers.append("controller.external_presence_unknown")
        return ControllerHandoffDecision(tuple(directives), tuple(blockers))

    if observation.external_connected is False:
        if observation.builtin_available is True and observation.builtin_input_verified:
            return ControllerHandoffDecision((ControllerDirective.KEEP_CURRENT,), ())
        return ControllerHandoffDecision(
            (ControllerDirective.ACTION_REQUIRED,),
            ("controller.no_verified_input",),
        )
    blockers = []
    if observation.external_connected is not True:
        blockers.append("controller.external_presence_unknown")
    if not observation.external_input_verified:
        blockers.append("controller.external_input_unverified")
    if capabilities.external_controller_promotion is not CapabilitySupport.VERIFIED:
        blockers.append("capability.external_controller_promotion_unverified")
    if blockers:
        return ControllerHandoffDecision(
            (ControllerDirective.ACTION_REQUIRED,),
            tuple(blockers),
        )
    directives = [ControllerDirective.PROMOTE_EXTERNAL]
    if policy.suppress_builtin_when_docked:
        if (
            capabilities.internal_controller_suppression is CapabilitySupport.VERIFIED
            and observation.builtin_restore_verified
            and observation.builtin_available is True
            and observation.builtin_input_verified
        ):
            directives.append(ControllerDirective.SUPPRESS_BUILTIN)
        else:
            return ControllerHandoffDecision(
                (ControllerDirective.PROMOTE_EXTERNAL,),
                ("controller.suppression_recovery_unverified",),
            )
    return ControllerHandoffDecision(tuple(directives), ())


def plan_audio_handoff(
    direction: HandoffDirection,
    observation: AudioHandoffObservation,
    capabilities: EffectiveCapabilities,
) -> AudioHandoffDecision:
    if direction is HandoffDirection.EXTERNAL_CONTROLLER_LOST:
        return AudioHandoffDecision((AudioDirective.KEEP_CURRENT,), ())
    if capabilities.audio_handoff is not CapabilitySupport.VERIFIED:
        return AudioHandoffDecision(
            (AudioDirective.KEEP_CURRENT, AudioDirective.ACTION_REQUIRED),
            ("capability.audio_handoff_unverified",),
        )
    if not observation.rollback_output_verified:
        return AudioHandoffDecision(
            (AudioDirective.KEEP_CURRENT, AudioDirective.ACTION_REQUIRED),
            ("audio.rollback_unverified",),
        )
    if direction is HandoffDirection.DOCK:
        if observation.external_output_available is True and observation.external_output_verified:
            return AudioHandoffDecision((AudioDirective.SELECT_EXTERNAL,), ())
        if observation.current_output_usable_verified:
            return AudioHandoffDecision(
                (AudioDirective.KEEP_CURRENT,),
                ("audio.external_unavailable_or_unverified",),
            )
        return AudioHandoffDecision(
            (AudioDirective.ACTION_REQUIRED,),
            ("audio.no_verified_output",),
        )
    if observation.portable_output_available is True and observation.portable_output_verified:
        return AudioHandoffDecision((AudioDirective.RESTORE_PORTABLE,), ())
    return AudioHandoffDecision(
        (AudioDirective.KEEP_CURRENT, AudioDirective.ACTION_REQUIRED),
        ("audio.portable_output_unavailable_or_unverified",),
    )
