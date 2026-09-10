"""Composite, observation-only controller/audio handoff planning."""

from __future__ import annotations

from ..domain.control_plane import EffectiveCapabilities
from ..domain.peripheral_handoff import (
    AudioDirective,
    AudioHandoffObservation,
    ControllerDirective,
    ControllerHandoffObservation,
    ControllerHandoffPolicy,
    HandoffDirection,
    PeripheralHandoffPlan,
    PeripheralObservation,
    PeripheralPlanStatus,
    PeripheralPlanStep,
    PeripheralStepKind,
    is_peripheral_token,
    plan_audio_handoff,
    plan_controller_handoff,
)
from ..ports.peripheral_handoff import PeripheralObservationPort


class PeripheralHandoffPlanningService:
    """Plan typed child steps; this service has no mutation authority."""

    def __init__(self, observations: PeripheralObservationPort) -> None:
        self._observations = observations

    def preview(
        self,
        direction: HandoffDirection,
        capabilities: EffectiveCapabilities,
        policy: ControllerHandoffPolicy = ControllerHandoffPolicy(),
    ) -> PeripheralHandoffPlan:
        return plan_peripheral_handoff(
            direction,
            self._observations.observe(),
            capabilities,
            policy,
        )

    def revalidate(
        self,
        direction: HandoffDirection,
        capabilities: EffectiveCapabilities,
        *,
        expected_generation: str,
        previous_sample_id: str,
        policy: ControllerHandoffPolicy = ControllerHandoffPolicy(),
    ) -> PeripheralHandoffPlan:
        if not is_peripheral_token(expected_generation) or not is_peripheral_token(
            previous_sample_id
        ):
            raise ValueError("peripheral revalidation identity is invalid")
        return plan_peripheral_handoff(
            direction,
            self._observations.observe(),
            capabilities,
            policy,
            expected_generation=expected_generation,
            previous_sample_id=previous_sample_id,
        )


def plan_peripheral_handoff(
    direction: HandoffDirection,
    observed: PeripheralObservation,
    capabilities: EffectiveCapabilities,
    policy: ControllerHandoffPolicy = ControllerHandoffPolicy(),
    *,
    expected_generation: str = "",
    previous_sample_id: str = "",
) -> PeripheralHandoffPlan:
    global_blockers = []
    if expected_generation and observed.generation != expected_generation:
        global_blockers.append("peripheral.generation_changed")
    if previous_sample_id and observed.sample_id == previous_sample_id:
        global_blockers.append("peripheral.sample_not_fresh")
    if global_blockers:
        return _plan(observed, direction, (), global_blockers)

    controller_state = observed.controller
    if not controller_state.complete or not controller_state.exact:
        controller_steps = ()
        controller_blockers = (controller_state.failure_code,)
    else:
        controller = plan_controller_handoff(
            direction,
            ControllerHandoffObservation(
                builtin_available=controller_state.builtin_available,
                builtin_input_verified=controller_state.builtin_input_verified,
                external_connected=controller_state.external_connected,
                external_input_verified=controller_state.external_input_verified,
                builtin_restore_verified=controller_state.builtin_restore_verified,
            ),
            capabilities,
            policy,
        )
        controller_steps, controller_blockers = _controller_steps(
            direction, observed, controller.directives, controller.blockers
        )
    audio_state = observed.audio
    if not audio_state.complete or not audio_state.exact:
        audio_steps = ()
        audio_blockers = (audio_state.failure_code,)
    else:
        audio = plan_audio_handoff(
            direction,
            AudioHandoffObservation(
                current_output=audio_state.current_output,
                current_output_usable_verified=audio_state.current_output_usable_verified,
                external_output_available=audio_state.external_output_available,
                external_output_verified=audio_state.external_output_verified,
                portable_output_available=audio_state.portable_output_available,
                portable_output_verified=audio_state.portable_output_verified,
                rollback_output_verified=audio_state.rollback_output_verified,
            ),
            capabilities,
        )
        audio_steps, audio_blockers = _audio_steps(
            observed, audio.directives, audio.blockers
        )

    if direction is HandoffDirection.DOCK:
        promotion = tuple(
            step
            for step in controller_steps
            if step.kind is PeripheralStepKind.PROMOTE_EXTERNAL_CONTROLLER
        )
        suppression = tuple(
            step
            for step in controller_steps
            if step.kind is PeripheralStepKind.SUPPRESS_BUILTIN_CONTROLLER
        )
        if suppression and not promotion:
            suppression = ()
            controller_blockers = tuple(
                dict.fromkeys(
                    (
                        *controller_blockers,
                        "controller.suppression_requires_promotion_step",
                    )
                )
            )
        steps = (*promotion, *audio_steps, *suppression)
    else:
        final_external = tuple(
            step
            for step in controller_steps
            if step.kind
            in {
                PeripheralStepKind.DISCONNECT_EXTERNAL_CONTROLLER,
                PeripheralStepKind.POWER_OFF_EXTERNAL_CONTROLLER,
            }
        )
        recovery = tuple(step for step in controller_steps if step not in final_external)
        steps = (*recovery, *audio_steps, *final_external)
    return _plan(
        observed,
        direction,
        steps,
        (*controller_blockers, *audio_blockers),
    )


def _controller_steps(direction, observed, directives, blockers):
    state = observed.controller
    steps = []
    binding_blockers = []
    for directive in directives:
        if directive in {ControllerDirective.KEEP_CURRENT, ControllerDirective.ACTION_REQUIRED}:
            continue
        if directive in {
            ControllerDirective.PROMOTE_EXTERNAL,
            ControllerDirective.DISCONNECT_EXTERNAL,
            ControllerDirective.POWER_OFF_EXTERNAL,
        }:
            binding = state.external_binding
            if not binding:
                binding_blockers.append("controller.external_binding_missing")
                continue
        else:
            binding = state.builtin_binding
            if not binding:
                binding_blockers.append("controller.builtin_binding_missing")
                continue
        kind = {
            ControllerDirective.PROMOTE_EXTERNAL: PeripheralStepKind.PROMOTE_EXTERNAL_CONTROLLER,
            ControllerDirective.SUPPRESS_BUILTIN: PeripheralStepKind.SUPPRESS_BUILTIN_CONTROLLER,
            ControllerDirective.RESTORE_BUILTIN: PeripheralStepKind.RESTORE_BUILTIN_CONTROLLER,
            ControllerDirective.PROMOTE_BUILTIN: PeripheralStepKind.PROMOTE_BUILTIN_CONTROLLER,
            ControllerDirective.DISCONNECT_EXTERNAL: PeripheralStepKind.DISCONNECT_EXTERNAL_CONTROLLER,
            ControllerDirective.POWER_OFF_EXTERNAL: PeripheralStepKind.POWER_OFF_EXTERNAL_CONTROLLER,
        }[directive]
        rollback = (
            state.builtin_binding
            if direction is HandoffDirection.DOCK
            and directive
            in {ControllerDirective.PROMOTE_EXTERNAL, ControllerDirective.SUPPRESS_BUILTIN}
            else ""
        )
        if direction is HandoffDirection.DOCK and not rollback:
            binding_blockers.append("controller.rollback_binding_missing")
            continue
        steps.append(PeripheralPlanStep(kind, binding, rollback))
    return tuple(steps), tuple(dict.fromkeys((*blockers, *binding_blockers)))


def _audio_steps(observed, directives, blockers):
    state = observed.audio
    steps = []
    binding_blockers = []
    for directive in directives:
        if directive in {AudioDirective.KEEP_CURRENT, AudioDirective.ACTION_REQUIRED}:
            continue
        if directive is AudioDirective.SELECT_EXTERNAL:
            target = state.external_output_binding
            kind = PeripheralStepKind.SELECT_EXTERNAL_AUDIO
        else:
            target = state.portable_output_binding
            kind = PeripheralStepKind.RESTORE_PORTABLE_AUDIO
        if not target:
            binding_blockers.append("audio.target_binding_missing")
            continue
        if not state.current_output_binding:
            binding_blockers.append("audio.rollback_binding_missing")
            continue
        steps.append(PeripheralPlanStep(kind, target, state.current_output_binding))
    return tuple(steps), tuple(dict.fromkeys((*blockers, *binding_blockers)))


def _plan(observed, direction, steps, blockers):
    unique_blockers = tuple(dict.fromkeys(blockers))
    if steps and unique_blockers:
        status = PeripheralPlanStatus.PARTIAL
    elif steps:
        status = PeripheralPlanStatus.READY
    elif unique_blockers:
        status = PeripheralPlanStatus.ACTION_REQUIRED
    else:
        status = PeripheralPlanStatus.NOOP
    return PeripheralHandoffPlan(
        status=status,
        direction=direction,
        observed_generation=observed.generation,
        observed_sample_id=observed.sample_id,
        steps=tuple(steps),
        blockers=unique_blockers,
    )
