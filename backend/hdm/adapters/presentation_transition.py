"""Guarded Gamescope presentation mechanism for the runtime orchestrator."""

from __future__ import annotations

import hashlib
import time
from typing import Callable, Protocol

from .steamos.commands import (
    UserServiceCommandRunner,
)
from .steamos.audio_handoff import G1AudioHandoff
from ..delivery.gamescope_integration import GamescopeIntegrationStore
from ..delivery.presentation_config import PresentationConfigStore
from ..domain.control_plane import (
    PlacementState,
    PlannedStep,
    TransitionBinding,
    TransitionOutcomeKind,
    TransitionStepCode,
)
from ..domain.inference import infer_placement
from ..domain.models import (
    Confidence,
    DisplayKind,
    GameState,
    GpuRole,
    ObservedSnapshot,
)
from ..ports.transition import MechanismResult
from ..ports.presentation_activation import (
    GamescopeUserResolution,
    UserServiceOperation,
)
from ..profiles.registry import resolve_runtime_profiles


class PresentationTargetStore(Protocol):
    def write_target(
        self,
        *,
        target: PlacementState,
        binding: TransitionBinding,
        snapshot: ObservedSnapshot,
        boot_id: str,
    ) -> object: ...


class PresentationTransitionMechanism:
    def __init__(
        self,
        *,
        integration: GamescopeIntegrationStore,
        config: PresentationConfigStore | PresentationTargetStore,
        commands: UserServiceCommandRunner,
        resolve_user: Callable[[], GamescopeUserResolution],
        read_boot_id: Callable[[], str],
        audio: G1AudioHandoff | None = None,
        trial_store=None,
        active_operation: Callable[[], str] = lambda: "",
        trial_layer_ready: Callable[[], bool] | None = None,
        trial_steam_waiter: Callable[[str], None] | None = None,
    ) -> None:
        self._integration = integration
        self._config = config
        self._commands = commands
        self._resolve_user = resolve_user
        self._read_boot_id = read_boot_id
        self._audio = audio
        self._trial_store = trial_store
        self._active_operation = active_operation
        self._trial_plan = None
        self._trial_layer_ready = trial_layer_ready
        self._trial_steam_waiter = trial_steam_waiter

    def run_portable_trial(self, plan, orchestrator):
        """Called only for a consumed trial-bound permit; reuse the same engine."""
        if self._trial_store is None or self._trial_plan is not None:
            raise ValueError("portable trial unavailable")
        self._trial_plan = plan
        try:
            result = orchestrator.run(plan, portable_vulkan_trial=True)
            from ..application.transition_orchestrator import RuntimeTransitionResult
            if (self._trial_steam_waiter is not None
                    and isinstance(result, RuntimeTransitionResult)
                    and result.durable
                    and result.outcome.kind is TransitionOutcomeKind.SUCCEEDED):
                self._trial_steam_waiter(plan.plan_id)
            return result
        finally:
            try:
                record = self._trial_store.read()
                if record is not None and record['operation_id'] == plan.plan_id:
                    # The exclusive Steam marker linearizes cancellation against
                    # its one-shot claim; waiting never grants fresh authority.
                    self._trial_store.cancel(plan.plan_id)
            finally:
                self._trial_plan = None

    def _current_trial(self):
        operation = self._active_operation()
        if self._trial_store is None or not operation:
            return None
        record = self._trial_store.read()
        if record is None or record['operation_id'] != operation:
            return None
        if record['boot_id_sha256'] != hashlib.sha256(self._read_boot_id().encode()).hexdigest():
            raise ValueError("trial recovery boot changed")
        return record

    def apply(
        self,
        step: PlannedStep,
        binding: TransitionBinding,
        observation: ObservedSnapshot,
    ) -> MechanismResult:
        if step.code is TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU:
            target = PlacementState.DOCKED_EGPU
        elif step.code is TransitionStepCode.PRESENTATION_RESTORE_PORTABLE:
            target = PlacementState.PORTABLE
        else:
            return MechanismResult(False, "presentation.step_unsupported")
        if step.expected_placement is not target:
            return MechanismResult(False, "presentation.step_mismatch")
        return self._attempt(target, binding, observation, "presentation")

    def recover(
        self,
        source: PlacementState,
        binding: TransitionBinding | None,
        observation: ObservedSnapshot | None,
    ) -> MechanismResult:
        # Revoke pending launch authority even if fresh recovery evidence is
        # unavailable. Otherwise a later session could execute the stale trial.
        try:
            record = self._current_trial()
            if record is not None:
                self._trial_store.cancel(record['operation_id'])
        except Exception:
            return MechanismResult(False, "recovery.trial_cancel_failed")
        if source not in {
            PlacementState.PORTABLE,
            PlacementState.DOCKED_IGPU,
            PlacementState.DOCKED_EGPU,
        }:
            return MechanismResult(False, "recovery.target_unsupported")
        if observation is None or observation.game_state is not GameState.IDLE:
            return MechanismResult(False, "recovery.observation_unusable")
        resolved_binding = binding or self._derive_binding(observation)
        if resolved_binding is None:
            return MechanismResult(False, "recovery.binding_unavailable")
        return self._attempt(source, resolved_binding, observation, "recovery")

    def _attempt(
        self,
        target: PlacementState,
        binding: TransitionBinding,
        observation: ObservedSnapshot,
        prefix: str,
    ) -> MechanismResult:
        if observation.game_state is not GameState.IDLE:
            return MechanismResult(False, f"{prefix}.observation_unusable")
        current_binding = self._derive_binding(observation)
        if current_binding is None or current_binding != binding:
            return MechanismResult(False, f"{prefix}.binding_changed")
        if target in {PlacementState.DOCKED_IGPU, PlacementState.DOCKED_EGPU}:
            external = tuple(
                item
                for item in observation.displays
                if item.stable_id == binding.external_display_stable_id
            )
            if len(external) != 1 or external[0].edid_ready is not True:
                return MechanismResult(False, f"{prefix}.display_unready")
        trial = self._trial_plan if prefix == "presentation" else None
        if trial is not None:
            if (target is not PlacementState.PORTABLE
                    or infer_placement(observation) is not PlacementState.DOCKED_EGPU
                    or self._trial_layer_ready is None or not self._trial_layer_ready()):
                return MechanismResult(False, "portable_trial.preconditions_unavailable")
            if self._trial_store.read() is not None:
                return MechanismResult(False, "portable_trial.reconciliation_required")
        status = self._integration.status()
        if not status.ready:
            return MechanismResult(False, f"{prefix}.integration_not_ready")
        resolution = self._resolve_user()
        if not resolution.ok or resolution.context is None:
            return MechanismResult(False, f"{prefix}.user_unavailable")
        user = resolution.context
        if user != self._integration.user:
            return MechanismResult(False, f"{prefix}.user_changed")
        if not self._run(UserServiceOperation.DAEMON_RELOAD, user):
            return MechanismResult(False, f"{prefix}.daemon_reload_failed")
        if not self._run(UserServiceOperation.VERIFY_GAMESCOPE_UNIT, user):
            return MechanismResult(False, f"{prefix}.unit_unavailable")
        if not self._user_still_current(user):
            return MechanismResult(False, f"{prefix}.user_changed")
        current = infer_placement(observation)
        if self._audio is not None and target is PlacementState.DOCKED_EGPU:
            prepared = self._audio.prepare_docked(user)
            if not prepared.succeeded:
                return MechanismResult(False, prepared.code)
        try:
            recovery_record = self._current_trial() if prefix == "recovery" else None
            if recovery_record is not None:
                self._trial_store.restore_original(self._config, recovery_record['operation_id'])
            else:
                original = self._config.load() if trial is not None else None
                boot_id = self._read_boot_id()
                if trial is not None:
                    source_policy = self._config.build_target(
                        target=PlacementState.DOCKED_EGPU, binding=binding,
                        snapshot=observation, boot_id=boot_id,
                    )
                    if original != source_policy:
                        return MechanismResult(False, 'portable_trial.original_policy_unverified')
                    expected = self._config.build_target(
                        target=target, binding=binding, snapshot=observation, boot_id=boot_id,
                    )
                    internal = next(g for g in observation.gpus
                                    if g.stable_id == binding.internal_gpu_stable_id)
                    self._trial_store.arm(
                            operation_id=trial.plan_id, generation=trial.observed_generation,
                            boot_id_sha256=hashlib.sha256(boot_id.encode()).hexdigest(),
                            internal_gpu=internal.vendor_device,
                            internal_connector=expected.internal_connector,
                            egpu_binding_sha256=hashlib.sha256(
                                f"{boot_id}:{binding.egpu_stable_id}".encode()).hexdigest(),
                            original_config=original, expected_config=expected,
                            expires_at=time.monotonic() + 120,
                    )
                self._config.write_target(
                    target=target, binding=binding, snapshot=observation, boot_id=boot_id,
                )
        except Exception:
            if not self._restore_current_config(current, binding, observation):
                return MechanismResult(False, f"{prefix}.config_rollback_failed")
            return MechanismResult(False, f"{prefix}.config_failed")
        if not self._user_still_current(user):
            if not self._restore_current_config(current, binding, observation):
                return MechanismResult(False, f"{prefix}.config_rollback_failed")
            return MechanismResult(False, f"{prefix}.user_changed")
        if not self._run(UserServiceOperation.RESTART_GAMESCOPE_SESSION, user):
            if not self._restore_current_config(current, binding, observation):
                return MechanismResult(False, f"{prefix}.config_rollback_failed")
            return MechanismResult(False, f"{prefix}.restart_failed")
        if self._audio is not None:
            audio_result = self._audio.switch(target, user)
            if not audio_result.succeeded:
                if not self._restore_current_config(current, binding, observation):
                    return MechanismResult(
                        False, f"{prefix}.config_rollback_failed"
                    )
                return MechanismResult(False, audio_result.code)
        return MechanismResult(True, f"{prefix}.restart_queued")

    def _user_still_current(self, expected) -> bool:
        try:
            resolution = self._resolve_user()
            return resolution.ok and resolution.context == expected
        except Exception:
            return False

    def _restore_current_config(self, current, binding, observation) -> bool:
        if current not in {
            PlacementState.PORTABLE,
            PlacementState.DOCKED_IGPU,
            PlacementState.DOCKED_EGPU,
        }:
            return False
        try:
            record = self._current_trial()
            if record is not None:
                self._trial_store.restore_original(self._config, record['operation_id'])
                return True
            self._config.write_target(
                target=current,
                binding=binding,
                snapshot=observation,
                boot_id=self._read_boot_id(),
            )
            return True
        except Exception:
            return False

    def _run(self, operation, user) -> bool:
        try:
            return self._commands.run(
                operation, uid=user.uid, username=user.username
            ).ok
        except Exception:
            return False

    @staticmethod
    def _derive_binding(snapshot: ObservedSnapshot) -> TransitionBinding | None:
        resolved = resolve_runtime_profiles(snapshot)
        if not resolved.exact_host or not resolved.exact_egpu:
            return None

        def exact_gpu(role):
            return tuple(
                item
                for item in snapshot.gpus
                if item.role is role
                and item.present
                and item.confidence is Confidence.VERIFIED
            )

        def exact_display(kind):
            return tuple(
                item
                for item in snapshot.displays
                if item.kind is kind
                and item.connected is True
                and item.confidence is Confidence.VERIFIED
            )

        internal_gpu = exact_gpu(GpuRole.INTERNAL)
        external_gpu = exact_gpu(GpuRole.EXTERNAL)
        internal_display = exact_display(DisplayKind.INTERNAL)
        external_display = exact_display(DisplayKind.EXTERNAL)
        if not all(
            len(values) == 1
            for values in (
                internal_gpu,
                external_gpu,
                internal_display,
                external_display,
            )
        ):
            return None
        if external_gpu[0].stable_id != resolved.egpu_stable_id:
            return None
        return TransitionBinding(
            resolved.capabilities.host_profile_id,
            resolved.capabilities.egpu_profile_id,
            resolved.egpu_stable_id,
            internal_gpu[0].stable_id,
            external_gpu[0].stable_id,
            internal_display[0].stable_id,
            external_display[0].stable_id,
        )
