"""Root Decky delivery adapter for the read-only HDM diagnostics API."""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import decky


PLUGIN_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = PLUGIN_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from hdm.adapters.steamos.discovery import SteamOsDiscovery  # noqa: E402
from hdm.adapters.steamos.topology_wakeup import LinuxTopologyWakeup  # noqa: E402
from hdm.adapters.steamos.drm import DrmDiscovery  # noqa: E402
from hdm.adapters.steamos.pci import PciUsb4Discovery  # noqa: E402
from hdm.adapters.steamos.wake_diagnostics import WakeDiagnosticsDiscovery  # noqa: E402
from hdm.adapters.steamos.commands import (  # noqa: E402
    PipeWireCommandRunner,
    SystemPowerCommandRunner,
    UserServiceCommandRunner,
)
from hdm.adapters.steamos.audio_handoff import G1AudioHandoff  # noqa: E402
from hdm.adapters.steamos.gamescope import GamescopeDiscovery  # noqa: E402
from hdm.adapters.steamos.gamescope_session import (  # noqa: E402
    GamescopeSessionObservationAdapter,
)
from hdm.adapters.steamos.gamescope_user import resolve_gamescope_user  # noqa: E402
from hdm.adapters.steamos.sleep_inhibitor import (  # noqa: E402
    G1SleepGuardHardwareDiscovery,
    SleepGuardController,
)
from hdm.adapters.steamos.process_signal import PosixProcessSignalAdapter  # noqa: E402
from hdm.adapters.game_runtime import CgroupProcGameRuntimeAdapter  # noqa: E402
from hdm.adapters.game_session import (  # noqa: E402
    GameScopeSessionObservationAdapter,
    UserBoundGameScopeScanAdapter,
)
from hdm.adapters.drm_engine_activity import (  # noqa: E402
    ProcfsDrmEngineCounterAdapter,
)
from hdm.adapters.steamos.game_render_binding import (  # noqa: E402
    AllyInternalDrmRenderBindingResolver,
    GpdG1DrmRenderBindingResolver,
)
from hdm.adapters.steamos.game_scopes import SystemdGameScopeDiscovery  # noqa: E402
from hdm.adapters.steamos.version_info import SteamOsVersionDiscovery  # noqa: E402
from hdm.adapters.steamos.peripherals import (  # noqa: E402
    SteamOsPeripheralObservationAdapter,
    peripheral_status_to_public_payload,
)
from hdm.api import DiagnosticsApi  # noqa: E402
from hdm.adapters.transition_runtime import (  # noqa: E402
    BoundedDeadlineWaiter,
    SnapshotTransitionObservationAdapter,
    SystemMonotonicClock,
    versioned_snapshot_observation,
)
from hdm.adapters.presentation_transition import (  # noqa: E402
    PresentationTransitionMechanism,
)
from hdm.application.game_evidence_support import (  # noqa: E402
    SupportGameEvidenceService,
)
from hdm.application.game_gpu_client import GameEgpuClientEvidenceService  # noqa: E402
from hdm.application.game_render_activity import (  # noqa: E402
    GameRenderActivityComparisonService,
)
from hdm.application.diagnostic_logging import (  # noqa: E402
    DiagnosticLoggingController,
    DiagnosticLoggingDuration,
    DiagnosticVerbosity,
)
from hdm.application.action_history import project_action_history  # noqa: E402
from hdm.application.snapshot import report_to_public_dict  # noqa: E402
from hdm.application.attach_readiness import (  # noqa: E402
    AttachReadinessLifecycle,
    AttachReadinessStage,
)
from hdm.application.automatic_dock import (  # noqa: E402
    AutomaticDockCoordinator,
    AutomaticDockStage,
)
from hdm.application.native_portable_recovery import (  # noqa: E402
    NativePortableRecoverySupervisor,
    NativeRecoveryStage,
)
from hdm.application.safe_disconnect_shutdown import (  # noqa: E402
    SafeDisconnectShutdownApprovalStore,
    SafeDisconnectShutdownService,
)
from hdm.application.topology_event_detection import (  # noqa: E402
    TopologyDetectionStatus,
    detect_topology_event,
)
from hdm.application.docked_igpu_exit import DockedIgpuGameExitWatcher  # noqa: E402
from hdm.application.docked_igpu_lifecycle import DockedIgpuWatchLifecycle  # noqa: E402
from hdm.application.docked_igpu_promotion import DockedIgpuPromotionFacade  # noqa: E402
from hdm.application.presentation_activation import (  # noqa: E402
    PresentationActivationApprovalStore,
    PresentationActivationService,
)
from hdm.application.experimental_transition import (  # noqa: E402
    ExperimentalTransitionApprovalStore,
)
from hdm.application.supervised_transition import (  # noqa: E402
    SupervisedPresentationTransitionService,
)
from hdm.application.shared_transition_journal import (  # noqa: E402
    SharedTransitionJournalService,
)
from hdm.application.transition_orchestrator import TransitionOrchestrator  # noqa: E402
from hdm.application.guarded_process_release import (  # noqa: E402
    GuardedProcessReleaseService,
)
from hdm.application.process_release import (  # noqa: E402
    GracefulReleaseReceiptStore,
    ProcessReleaseApprovalStore,
)
from hdm.application.process_release_replay import (  # noqa: E402
    ProcessReleaseJournalRecovery,
    ProcessReleaseRunner,
)
from hdm.application.support_bundle import (  # noqa: E402
    BoundedEventLog,
    SupportBundle,
    SupportBundleContext,
    SupportBundlePreviewStore,
    SupportBundleService,
    WakeDiagnosticsSupportStatus,
)
from hdm.delivery.support_export import SupportBundleFileWriter  # noqa: E402
from hdm.delivery.gamescope_integration import GamescopeIntegrationStore  # noqa: E402
from hdm.delivery.presentation_config import PresentationConfigStore  # noqa: E402
from hdm.delivery.process_release import (  # noqa: E402
    execution_to_payload,
    preview_to_payload,
    status_to_payload,
)
from hdm.delivery.presentation_transition import (  # noqa: E402
    status_to_payload as presentation_transition_status_to_payload,
)
from hdm.delivery.game_evidence_support import (  # noqa: E402
    game_evidence_to_event_details,
)
from hdm.delivery.diagnostic_logging import (  # noqa: E402
    diagnostic_logging_status_to_payload,
)
from hdm.delivery.build_info import load_public_build_info  # noqa: E402
from hdm.delivery.action_history import action_history_to_payload  # noqa: E402
from hdm.delivery.attach_readiness import attach_readiness_to_payload  # noqa: E402
from hdm.delivery.docked_igpu_lifecycle import lifecycle_status_to_payload  # noqa: E402
from hdm.delivery.peripheral_support import peripheral_support_status  # noqa: E402
from hdm.delivery.docked_igpu_scheduler import (  # noqa: E402
    DockedIgpuLifecycleScheduler,
)
from hdm.delivery.runtime_state import RootOwnedRuntimeState  # noqa: E402
from hdm.delivery.automatic_dock_preferences import (  # noqa: E402
    AutomaticDockPreferenceStore,
)
from hdm.delivery.audio_state import PortableAudioStateStore  # noqa: E402
from hdm.delivery.transition_journal_store import FileTransitionJournalStore  # noqa: E402
from hdm.domain.process_release import ReleasePhase  # noqa: E402
from hdm.domain.control_plane import (  # noqa: E402
    PlacementState,
    TransitionOutcomeKind,
)
from hdm.domain.models import GameState, GpuRole  # noqa: E402
from hdm.domain.inference import infer_placement  # noqa: E402
from hdm.profiles.gpd_g1 import match_gpd_g1  # noqa: E402


MAX_JOURNEY_ELAPSED_MS = 24 * 60 * 60 * 1000


def _can_remember_portable_audio(snapshot) -> bool:
    """Do not let attached HDMI overwrite the pre-attach audio baseline."""
    return (
        infer_placement(snapshot) is PlacementState.PORTABLE
        and snapshot.game_state is GameState.IDLE
        and not snapshot.disconnect_readiness.applicable
        and snapshot.disconnect_readiness.scan_complete
        and not snapshot.sleep_guard.required
        and not snapshot.egpu_link.applicable
        and not any(gpu.role is GpuRole.EXTERNAL for gpu in snapshot.gpus)
    )


class Plugin:
    def __init__(self) -> None:
        self._sleep_guard = SleepGuardController()
        self._sleep_hardware = G1SleepGuardHardwareDiscovery()
        self._discovery = SteamOsDiscovery(
            sleep_guard_status=self._sleep_guard.status
        )
        self._api = DiagnosticsApi(self._discovery)
        self._peripherals = SteamOsPeripheralObservationAdapter()
        self._sleep_guard_task: asyncio.Task[None] | None = None
        self._automatic_dock_task: asyncio.Task[None] | None = None
        self._automatic_dock_retry_seconds = 1.0
        self._topology_wakeup = None
        self._topology_wakeup_was_available = False
        self._last_completion_code = ""
        self._automatic_dock = AutomaticDockCoordinator()
        self._native_recovery_task: asyncio.Task[None] | None = None
        self._native_recovery = NativePortableRecoverySupervisor()
        self._last_native_recovery_code = ""
        self._automatic_dock_preference_store: AutomaticDockPreferenceStore | None = None
        self._docked_igpu_scheduler: DockedIgpuLifecycleScheduler | None = None
        self._docked_igpu_task: asyncio.Task[None] | None = None
        self._docked_igpu_retry_seconds = 30.0
        self._last_docked_igpu_lifecycle_code = ""
        self._last_sleep_guard_log: tuple[str, bool, str] | None = None
        self._events = BoundedEventLog()
        self._topology_lock = threading.Lock()
        self._topology_observation = None
        self._attach_readiness = AttachReadinessLifecycle()
        self._last_attach_readiness_code = self._attach_readiness.status().code
        self._journey_clock_ns = time.monotonic_ns
        self._journey_timing_lock = threading.Lock()
        self._journey_started_ns: int | None = None
        self._journey_stage_started_ns: int | None = None
        self._diagnostic_logging = DiagnosticLoggingController(
            self._events,
            boot_session_id=self._boot_session_id,
        )
        self._support_bundles = SupportBundleService()
        self._support_previews = SupportBundlePreviewStore()
        self._support_writer = SupportBundleFileWriter()
        self._presentation_approvals = PresentationActivationApprovalStore()
        self._presentation_transition_approvals = ExperimentalTransitionApprovalStore()
        self._safe_disconnect_shutdown_approvals = (
            SafeDisconnectShutdownApprovalStore()
        )
        self._process_approvals = ProcessReleaseApprovalStore()
        self._process_receipts = GracefulReleaseReceiptStore()
        self._process_release: GuardedProcessReleaseService | None = None
        self._version_info = SteamOsVersionDiscovery().scan()
        self._build_info = load_public_build_info(PLUGIN_ROOT)

    async def get_snapshot(self, _request: object = None) -> dict[str, object]:
        """Return the existing privacy-safe, read-only diagnostics payload."""
        report = await asyncio.to_thread(self._api.get_snapshot_report)
        payload = report_to_public_dict(report)
        payload["diagnostics"]["build"] = self._build_info
        await self._start_docked_igpu_lifecycle_for(report)
        attach_status = await asyncio.to_thread(
            self._record_topology_observation, report.snapshot
        )
        payload["attach_readiness"] = attach_readiness_to_payload(attach_status)
        await asyncio.to_thread(self._record_verbose_snapshot, payload)
        return payload

    async def _start_docked_igpu_lifecycle_for(self, report) -> None:
        """Start the exit watcher only for its exact running Docked-iGPU case."""

        if (
            infer_placement(report.snapshot) is PlacementState.DOCKED_IGPU
            and report.snapshot.game_state is GameState.RUNNING
        ):
            await self._start_docked_igpu_lifecycle()

    def _record_topology_observation(self, snapshot):
        """Log only verified snapshot deltas; never execute recovery from them."""
        current = versioned_snapshot_observation(snapshot)
        with self._topology_lock:
            previous = self._topology_observation
            self._topology_observation = current
            detection = detect_topology_event(previous, current)
            status = self._attach_readiness.update(detection, current)
            readiness_changed = status.code != self._last_attach_readiness_code
            self._last_attach_readiness_code = status.code
        if readiness_changed:
            self._record_attach_readiness_status(status)
        if detection.status is not TopologyDetectionStatus.DETECTED:
            return status
        self._append_journey_event(
            severity="info",
            code=detection.reason_code,
            component="topology",
            stage="observation",
            create_timeline=detection.reason_code != "topology.egpu_removed",
            reset_after=detection.reason_code == "topology.egpu_removed",
        )
        return status

    def _record_attach_readiness_status(self, status) -> None:
        if status.stage is AttachReadinessStage.IDLE:
            return
        self._append_journey_event(
            severity=(
                "warning"
                if status.stage is AttachReadinessStage.ACTION_REQUIRED
                else "info"
            ),
            code=status.code,
            component="connection",
            stage=status.stage.value,
            details={"poll_after_ms": status.poll_after_ms},
        )

    def _append_journey_event(
        self,
        *,
        severity: str,
        code: str,
        component: str,
        stage: str,
        details: dict[str, object] | None = None,
        now_ns: int | None = None,
        create_timeline: bool = True,
        reset_after: bool = False,
    ) -> None:
        observed_ns = self._journey_now_ns() if now_ns is None else now_ns
        timing = self._journey_timing_details(
            observed_ns,
            create=create_timeline,
            reset_after=reset_after,
        )
        event_details = {**timing, **(details or {})}
        try:
            self._diagnostic_logging.append(
                verbosity=DiagnosticVerbosity.NORMAL,
                severity=severity,
                code=code,
                component=component,
                stage=stage,
                details=event_details,
            )
        except Exception:
            try:
                decky.logger.exception("HDM G1 journey support event failed")
            except Exception:
                pass
        try:
            decky.logger.info(
                "HDM G1 journey: component=%s stage=%s code=%s elapsed_ms=%s stage_elapsed_ms=%s",
                component,
                stage,
                code,
                event_details.get("elapsed_ms", "unavailable"),
                event_details.get("stage_elapsed_ms", "unavailable"),
            )
        except Exception:
            pass

    def _journey_timing_details(
        self,
        now_ns: int,
        *,
        create: bool,
        reset_after: bool,
    ) -> dict[str, int]:
        with self._journey_timing_lock:
            if self._journey_started_ns is None:
                if not create:
                    return {}
                self._journey_started_ns = now_ns
                self._journey_stage_started_ns = now_ns
            stage_started = self._journey_stage_started_ns or now_ns
            details = {
                "elapsed_ms": self._bounded_elapsed_ms(
                    self._journey_started_ns, now_ns
                ),
                "stage_elapsed_ms": self._bounded_elapsed_ms(
                    stage_started, now_ns
                ),
            }
            self._journey_stage_started_ns = now_ns
            if reset_after:
                self._journey_started_ns = None
                self._journey_stage_started_ns = None
            return details

    def _journey_now_ns(self) -> int:
        try:
            value = self._journey_clock_ns()
        except Exception:
            return 0
        return value if isinstance(value, int) and value >= 0 else 0

    @staticmethod
    def _bounded_elapsed_ms(started_ns: int, finished_ns: int) -> int:
        return min(
            MAX_JOURNEY_ELAPSED_MS,
            max(0, (finished_ns - started_ns) // 1_000_000),
        )

    async def get_peripheral_status(self, _request: object = None) -> dict[str, object]:
        """Read identity-free controller/audio evidence without any handoff action."""
        try:
            observed = await asyncio.to_thread(self._peripherals.observe)
            return peripheral_status_to_public_payload(observed)
        except Exception:
            return {
                "schema_version": 1,
                "controller": {"complete": False, "exact": False, "builtin_available": None, "external_connected": None, "code": "controller.observation_unavailable"},
                "audio": {"complete": False, "exact": False, "external_available": None, "portable_available": None, "code": "audio.observation_unavailable"},
            }

    async def get_action_history(self, _request: object = None) -> dict[str, object]:
        """Return the bounded, identity-free projection of existing HDM events."""
        try:
            return await asyncio.to_thread(
                lambda: action_history_to_payload(
                    project_action_history(self._events.snapshot())
                )
            )
        except Exception:
            return {"schema_version": 1, "entries": []}

    async def get_automatic_dock_status(
        self, _request: object = None
    ) -> dict[str, object]:
        """Return the persisted opt-in and categorical coordinator state."""
        try:
            enabled = await asyncio.to_thread(self._automatic_dock_preferences().load)
            status = self._automatic_dock.status()
            return {
                "schema_version": 1,
                "enabled": enabled,
                "stage": status.stage.value,
                "code": status.code if enabled else "automatic_dock.disabled",
            }
        except Exception:
            return {
                "schema_version": 1,
                "enabled": False,
                "stage": AutomaticDockStage.ACTION_REQUIRED.value,
                "code": "automatic_dock.preference_unavailable",
            }

    async def set_automatic_dock_enabled(
        self, enabled: bool, user_confirmed: bool
    ) -> dict[str, object]:
        """Persist deliberate player consent; disabling is always permitted."""
        if type(enabled) is not bool or type(user_confirmed) is not bool:
            return self._automatic_dock_failure("automatic_dock.request_invalid")
        if enabled and not user_confirmed:
            return self._automatic_dock_failure(
                "automatic_dock.confirmation_required",
                stage=AutomaticDockStage.DISABLED,
            )
        try:
            await asyncio.to_thread(self._automatic_dock_preferences().save, enabled)
        except Exception:
            return self._automatic_dock_failure(
                "automatic_dock.preference_unavailable"
            )
        code = "automatic_dock.enabled" if enabled else "automatic_dock.disabled"
        if self._topology_wakeup is not None:
            self._topology_wakeup.invalidate()
        self._events.append(
            severity="info",
            code=code,
            component="presentation",
            stage="preference",
        )
        return {
            "schema_version": 1,
            "enabled": enabled,
            "stage": (
                AutomaticDockStage.OBSERVING.value
                if enabled
                else AutomaticDockStage.DISABLED.value
            ),
            "code": code,
        }

    async def get_diagnostic_logging_status(self, _request: object = None) -> dict[str, object]:
        """Return bounded, identity-free status for the opt-in verbose session."""

        try:
            status = await asyncio.to_thread(self._diagnostic_logging.status)
            return diagnostic_logging_status_to_payload(status)
        except Exception:
            return self._diagnostic_logging_unavailable()

    async def enable_diagnostic_logging(
        self, duration: str, user_confirmed: bool
    ) -> dict[str, object]:
        """Enable only one allowlisted, explicitly confirmed ephemeral duration."""

        try:
            selected = DiagnosticLoggingDuration(duration)
            status = await asyncio.to_thread(
                self._diagnostic_logging.enable,
                selected,
                user_confirmed=user_confirmed is True,
            )
            try:
                self._diagnostic_logging.append(
                    verbosity=DiagnosticVerbosity.NORMAL,
                    severity="info",
                    code="diagnostics.verbose_enabled",
                    component="diagnostics",
                    stage="consent",
                    details={"duration": selected.value},
                )
            except Exception:
                pass
            return diagnostic_logging_status_to_payload(status)
        except Exception:
            return self._diagnostic_logging_unavailable(
                "diagnostics.verbose_enable_rejected"
            )

    async def disable_diagnostic_logging(self, _request: object = None) -> dict[str, object]:
        """Disable verbose collection immediately without deleting normal events."""

        try:
            status = await asyncio.to_thread(self._diagnostic_logging.disable)
            try:
                self._diagnostic_logging.append(
                    verbosity=DiagnosticVerbosity.NORMAL,
                    severity="info",
                    code="diagnostics.verbose_disabled",
                    component="diagnostics",
                    stage="consent",
                )
            except Exception:
                pass
            return diagnostic_logging_status_to_payload(status)
        except Exception:
            return self._diagnostic_logging_unavailable()

    def _record_verbose_snapshot(self, payload: dict[str, object]) -> None:
        snapshot = payload.get("snapshot")
        inference = payload.get("inference")
        diagnostics = payload.get("diagnostics")
        if not isinstance(snapshot, dict):
            return
        blocker_codes = []
        blockers = snapshot.get("blockers")
        if isinstance(blockers, list):
            blocker_codes = [
                str(item.get("code", "unknown"))
                for item in blockers[:32]
                if isinstance(item, dict)
            ]
        mode = (
            str(inference.get("mode", "unknown"))
            if isinstance(inference, dict)
            else "unknown"
        )
        timing_rows = (
            diagnostics.get("timings_ms", ())[:32]
            if isinstance(diagnostics, dict)
            and isinstance(diagnostics.get("timings_ms"), list)
            else ()
        )
        self._diagnostic_logging.append(
            verbosity=DiagnosticVerbosity.VERBOSE,
            severity="info",
            code="diagnostics.snapshot_observed",
            component="diagnostics",
            stage="snapshot",
            details={
                "mode": mode,
                "game_state": str(snapshot.get("game_state", "unknown")),
                "support_tier": str(snapshot.get("support_tier", "unknown")),
                "blocker_codes": blocker_codes,
                "timing_count": len(timing_rows),
                "timings_ms": timing_rows,
            },
        )

    @staticmethod
    def _diagnostic_logging_unavailable(
        code: str = "diagnostics.verbose_status_unavailable",
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "enabled": False,
            "mode": "off",
            "duration": "",
            "remaining_seconds": None,
            "code": code,
        }

    @staticmethod
    def _boot_session_id() -> str:
        return Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="ascii"
        ).strip()

    async def get_docked_igpu_status(self, _request: object = None) -> dict[str, object]:
        """Return only categorical state from the read-only natural-exit watch."""

        scheduler = self._docked_igpu_scheduler
        if scheduler is None:
            return {
                "schema_version": 1,
                "stage": "idle",
                "code": "docked_igpu.lifecycle_unavailable",
                "poll_after_ms": 15000,
                "inspection_available": False,
                "acknowledgement_required": False,
            }
        return lifecycle_status_to_payload(scheduler.status())

    async def acknowledge_docked_igpu_status(self, _request: object = None) -> dict[str, object]:
        """Acknowledge only a terminal read-only watch; never approve a transition."""

        scheduler = self._docked_igpu_scheduler
        if scheduler is None:
            return {"schema_version": 1, "acknowledged": False}
        try:
            acknowledged = await asyncio.to_thread(
                scheduler.acknowledge_action
            )
        except Exception:
            acknowledged = False
        if acknowledged:
            scheduler.wake()
        return {"schema_version": 1, "acknowledged": acknowledged}

    async def preview_support_bundle(self, _request: object = None) -> dict[str, object]:
        """Return a redacted preview and one-time approval token."""
        report = await self.get_snapshot()
        peripheral_status = None
        try:
            peripheral = await asyncio.to_thread(self._peripherals.observe)
            peripheral_status = peripheral_support_status(peripheral)
        except Exception:
            pass
        try:
            wake_diagnostics = await asyncio.to_thread(self._support_wake_diagnostics)
        except Exception:
            wake_diagnostics = None
        context = SupportBundleContext(
            peripheral_status=peripheral_status,
            wake_diagnostics=wake_diagnostics,
        )
        await asyncio.to_thread(self._record_support_game_evidence)
        self._events.append(
            severity="info",
            code="support.preview_created",
            component="support",
            stage="preview",
        )
        bundle = await asyncio.to_thread(
            self._support_bundles.build,
            report,
            self._events.snapshot(),
            self._support_versions(),
            self._sensitive_values(),
            context,
        )
        preview = self._support_previews.issue(bundle)
        return {
            "schema_version": 1,
            "preview_token": preview.token,
            "preview_json": bundle.json_text,
            "size_bytes": bundle.size_bytes,
            "event_count": bundle.event_count,
            "manifest": dict(bundle.payload["manifest"]),
        }

    @staticmethod
    def _support_wake_diagnostics() -> WakeDiagnosticsSupportStatus:
        """Read exact G1 wake capability state for an explicit support preview."""
        pci = PciUsb4Discovery()
        g1 = match_gpd_g1(DrmDiscovery().scan(), pci.scan_pci(), pci.scan_usb4())
        observed = WakeDiagnosticsDiscovery().observe(
            g1.root_bdf if g1.verified else "",
            g1.pci_functions if g1.verified else (),
        )
        return WakeDiagnosticsSupportStatus(
            applicable=observed.applicable,
            bridge_wakeup=observed.bridge_wakeup.value,
            function_wakeup_enabled=observed.function_wakeup_enabled,
            function_wakeup_disabled=observed.function_wakeup_disabled,
            function_wakeup_unknown=observed.function_wakeup_unknown,
            function_runtime_active=observed.function_runtime_active,
            function_runtime_suspended=observed.function_runtime_suspended,
            function_runtime_unknown=observed.function_runtime_unknown,
            reason=observed.reason or "wake.observation_unavailable",
        )

    async def save_support_bundle(self, preview_token: str) -> dict[str, object]:
        """Save only the exact bundle represented by a one-time preview token."""
        bundle = self._support_previews.consume(preview_token)
        result = await asyncio.to_thread(self._write_support_bundle, bundle)
        self._events.append(
            severity="info",
            code="support.bundle_saved",
            component="support",
            stage="save",
            details={"size_bytes": bundle.size_bytes},
        )
        return result

    def _record_support_game_evidence(self) -> None:
        try:
            evidence = self._support_game_evidence_service().observe()
            details = game_evidence_to_event_details(evidence)
            unavailable = (
                not evidence.identity_exact
                or evidence.internal_render.status.value == "unknown"
                or evidence.external_render.status.value == "unknown"
            )
            self._events.append(
                severity="warning" if unavailable else "info",
                code=(
                    "game_evidence.incomplete"
                    if unavailable
                    else "game_evidence.captured"
                ),
                component="game_evidence",
                stage="support_preview",
                details=details,
            )
        except Exception:
            self._events.append(
                severity="warning",
                code="game_evidence.unavailable",
                component="game_evidence",
                stage="support_preview",
            )

    def _support_game_evidence_service(self) -> SupportGameEvidenceService:
        resolution = resolve_gamescope_user(GamescopeDiscovery().scan())
        if not resolution.ok or resolution.context is None:
            raise ValueError("Gamescope user is unavailable")
        user_uid = resolution.context.uid
        snapshots = SnapshotTransitionObservationAdapter(self._discovery)
        runtime = CgroupProcGameRuntimeAdapter()
        counters = ProcfsDrmEngineCounterAdapter()
        sessions = GameScopeSessionObservationAdapter(
            UserBoundGameScopeScanAdapter(
                SystemdGameScopeDiscovery(),
                user_uid,
            )
        )
        return SupportGameEvidenceService(
            sessions=sessions,
            egpu_clients=GameEgpuClientEvidenceService(
                runtime=runtime,
                snapshots=snapshots,
            ),
            render_comparison=GameRenderActivityComparisonService(
                runtime=runtime,
                snapshots=snapshots,
                internal_binding=AllyInternalDrmRenderBindingResolver(),
                external_binding=GpdG1DrmRenderBindingResolver(),
                counters=counters,
                waiter=BoundedDeadlineWaiter(),
            ),
            user_uid=user_uid,
            verify_user=self._gamescope_user_matches,
        )

    @staticmethod
    def _gamescope_user_matches(expected_uid: int) -> bool:
        resolution = resolve_gamescope_user(GamescopeDiscovery().scan())
        return bool(
            resolution.ok
            and resolution.context is not None
            and resolution.context.uid == expected_uid
        )

    async def preview_presentation_preparation(self, _request: object = None) -> dict[str, object]:
        """Inspect the reversible integration without writing or restarting."""
        try:
            preview = await asyncio.to_thread(
                self._presentation_service().preview,
                user_confirmed=False,
            )
            return {
                "schema_version": 1,
                "ready": preview.already_ready,
                "blockers": list(preview.blockers),
                "confirmation_required": not preview.blockers,
            }
        except Exception:
            return {
                "schema_version": 1,
                "ready": False,
                "blockers": ["gamescope.user_unavailable"],
                "confirmation_required": False,
            }

    async def approve_presentation_preparation(self, _request: object = None) -> dict[str, object]:
        """Issue one exact approval after the controller confirmation action."""
        try:
            preview = await asyncio.to_thread(
                self._presentation_service().preview,
                user_confirmed=True,
            )
            return {
                "schema_version": 1,
                "approval_token": preview.token,
                "ready": preview.already_ready,
                "blockers": list(preview.blockers),
            }
        except Exception:
            return {
                "schema_version": 1,
                "approval_token": "",
                "ready": False,
                "blockers": ["activation.approval_failed"],
            }

    async def prepare_presentation_integration(
        self, approval_token: str
    ) -> dict[str, object]:
        """Prepare only the approved reversible integration; never restart."""
        try:
            outcome = await asyncio.to_thread(
                self._presentation_service().execute,
                approval_token,
            )
        except Exception:
            return {
                "schema_version": 1,
                "prepared": False,
                "changed": False,
                "code": "activation.user_unavailable",
                "rollback_attempted": False,
                "rollback_succeeded": False,
            }
        self._events.append(
            severity="info" if outcome.prepared else "warning",
            code=outcome.code,
            component="presentation",
            stage="preparation",
            details={
                "prepared": outcome.prepared,
                "changed": outcome.changed,
                "rollback_attempted": outcome.rollback_attempted,
                "rollback_succeeded": outcome.rollback_succeeded,
            },
        )
        return {
            "schema_version": 1,
            "prepared": outcome.prepared,
            "changed": outcome.changed,
            "code": outcome.code,
            "rollback_attempted": outcome.rollback_attempted,
            "rollback_succeeded": outcome.rollback_succeeded,
        }

    async def preview_supervised_tv_switch(
        self, _request: object = None
    ) -> dict[str, object]:
        """Inspect one idle-only display switch without issuing authority."""
        try:
            preview = await asyncio.to_thread(
                self._presentation_transition_service().preview,
                PlacementState.DOCKED_EGPU,
                user_confirmed=False,
            )
            return {
                "schema_version": 1,
                "ready": preview.ready,
                "blockers": list(preview.blockers),
                "confirmation_required": preview.ready,
            }
        except Exception:
            return {
                "schema_version": 1,
                "ready": False,
                "blockers": ["transition.service_unavailable"],
                "confirmation_required": False,
            }

    async def approve_supervised_tv_switch(
        self, _request: object = None
    ) -> dict[str, object]:
        """Issue one short-lived permit after an on-screen player confirmation."""
        try:
            preview = await asyncio.to_thread(
                self._presentation_transition_service().preview,
                PlacementState.DOCKED_EGPU,
                user_confirmed=True,
            )
            return {
                "schema_version": 1,
                "approval_token": preview.approval_token,
                "blockers": list(preview.blockers),
            }
        except Exception:
            return {
                "schema_version": 1,
                "approval_token": "",
                "blockers": ["transition.approval_failed"],
            }

    async def execute_supervised_tv_switch(
        self, approval_token: str
    ) -> dict[str, object]:
        """Execute only one prepared, exact idle TV switch attempt."""
        return await self._execute_supervised_switch(
            approval_token, PlacementState.DOCKED_EGPU
        )

    async def _execute_supervised_switch(
        self, approval_token: str, requested_target: PlacementState
    ) -> dict[str, object]:
        started_ns = self._journey_now_ns()
        self._append_journey_event(
            severity="info",
            code="connection.supervised_transition_started",
            component="connection",
            stage="supervised_transition",
            details={"requested_target": requested_target.value},
            now_ns=started_ns,
        )
        try:
            result = await asyncio.to_thread(
                self._presentation_transition_service().execute, approval_token
            )
        except Exception:
            finished_ns = self._journey_now_ns()
            self._append_journey_event(
                severity="error",
                code="transition.execution_failed",
                component="connection",
                stage="supervised_transition",
                details={
                    "requested_target": requested_target.value,
                    "duration_ms": self._bounded_elapsed_ms(started_ns, finished_ns),
                },
                now_ns=finished_ns,
            )
            return self._presentation_transition_failure("transition.execution_failed")
        outcome = result.outcome
        code = result.code
        finished_ns = self._journey_now_ns()
        succeeded = bool(
            outcome and outcome.kind is TransitionOutcomeKind.SUCCEEDED
        )
        self._append_journey_event(
            severity="info" if succeeded else "warning",
            code=code,
            component="connection",
            stage="supervised_transition",
            details={
                "requested_target": requested_target.value,
                "result_placement": (
                    outcome.placement.value if outcome is not None else "unknown"
                ),
                "duration_ms": self._bounded_elapsed_ms(started_ns, finished_ns),
                "accepted": result.accepted,
                "succeeded": succeeded,
            },
            now_ns=finished_ns,
        )
        self._events.append(
            severity=(
                "info"
                if succeeded
                else "warning"
            ),
            code=code,
            component="presentation",
            stage="supervised_transition",
        )
        return {
            "schema_version": 1,
            "accepted": result.accepted,
            "code": code,
            "acknowledgement_id": result.operation_id,
            "acknowledgement_required": bool(result.operation_id and result.durable),
        }

    async def approve_supervised_portable_switch(
        self, _request: object = None
    ) -> dict[str, object]:
        """Issue one short-lived permit to return a verified idle dock to Portable."""
        try:
            preview = await asyncio.to_thread(
                self._presentation_transition_service().preview,
                PlacementState.PORTABLE,
                user_confirmed=True,
            )
            return {
                "schema_version": 1,
                "approval_token": preview.approval_token,
                "blockers": list(preview.blockers),
            }
        except Exception:
            return {
                "schema_version": 1,
                "approval_token": "",
                "blockers": ["transition.approval_failed"],
            }

    async def execute_supervised_portable_switch(
        self, approval_token: str
    ) -> dict[str, object]:
        """Execute only the approved return-to-Portable transition."""
        return await self._execute_supervised_switch(
            approval_token, PlacementState.PORTABLE
        )

    async def approve_safe_disconnect_shutdown(
        self, _request: object = None
    ) -> dict[str, object]:
        """Approve shutdown only from a fresh idle Portable observation."""
        try:
            preview = await asyncio.to_thread(
                self._safe_disconnect_shutdown_service().preview,
                user_confirmed=True,
            )
            return {
                "schema_version": 1,
                "ready": preview.ready,
                "approval_token": preview.approval_token,
                "blockers": list(preview.blockers),
            }
        except Exception:
            return {
                "schema_version": 1,
                "ready": False,
                "approval_token": "",
                "blockers": ["safe_disconnect.service_unavailable"],
            }

    async def execute_safe_disconnect_shutdown(
        self, approval_token: str
    ) -> dict[str, object]:
        """Queue system power-off; never claim removal safe while still powered."""
        started_ns = self._journey_now_ns()
        self._append_journey_event(
            severity="info",
            code="safe_disconnect.shutdown_started",
            component="safe_disconnect",
            stage="shutdown",
            now_ns=started_ns,
        )
        try:
            result = await asyncio.to_thread(
                self._safe_disconnect_shutdown_service().execute,
                approval_token,
            )
        except Exception:
            result = None
        code = (
            result.code if result is not None else "safe_disconnect.execution_failed"
        )
        accepted = bool(result and result.accepted)
        finished_ns = self._journey_now_ns()
        self._append_journey_event(
            severity="info" if accepted else "warning",
            code=code,
            component="safe_disconnect",
            stage="shutdown",
            details={
                "duration_ms": self._bounded_elapsed_ms(started_ns, finished_ns),
                "accepted": accepted,
                "poweroff_complete": False,
            },
            now_ns=finished_ns,
        )
        return {"schema_version": 1, "accepted": accepted, "code": code}

    async def acknowledge_supervised_tv_switch(
        self, acknowledgement_id: str
    ) -> dict[str, object]:
        """Clear only the exact terminal transition after player acknowledgement."""
        try:
            prior_status = await asyncio.to_thread(
                self._presentation_transition_service().status
            )
        except Exception:
            prior_status = None
        try:
            acknowledged = await asyncio.to_thread(
                self._presentation_transition_service().acknowledge,
                acknowledgement_id,
            )
        except Exception:
            acknowledged = False
        if acknowledged:
            if prior_status and prior_status.target is PlacementState.PORTABLE:
                self._automatic_dock.suppress_current_attachment_after_portable_return()
            else:
                self._automatic_dock.reset_after_acknowledgement()
            if self._topology_wakeup is not None:
                self._topology_wakeup.invalidate()
        return {"schema_version": 1, "acknowledged": acknowledged}

    async def get_supervised_tv_switch_status(
        self, _request: object = None
    ) -> dict[str, object]:
        """Return the durable supervised-TV result after a Gamescope restart."""
        try:
            status = await asyncio.to_thread(
                self._presentation_transition_service().status
            )
            return presentation_transition_status_to_payload(status)
        except Exception:
            return {
                "schema_version": 1,
                "code": "transition.service_unavailable",
                "acknowledgement_required": False,
                "action_required": True,
                "acknowledgement_id": "",
                "durable": False,
                "target": PlacementState.UNKNOWN.value,
            }

    async def get_process_release_status(self, _request: object = None) -> dict[str, object]:
        """Return only categorical durable release state and acknowledgement ID."""
        try:
            status = await asyncio.to_thread(self._process_service().status)
            return status_to_payload(status)
        except Exception:
            return {
                "schema_version": 1,
                "code": "process_release.service_unavailable",
                "acknowledgement_required": False,
                "action_required": True,
                "acknowledgement_id": "",
                "durable": False,
            }

    async def get_transition_journal_status(
        self, _request: object = None
    ) -> dict[str, object]:
        """Identify the categorical owner of the shared durable journal."""
        try:
            status = await asyncio.to_thread(self._transition_journal_service().status)
            return {
                "schema_version": 1,
                "code": status.code,
                "owner": status.owner.value,
                "acknowledgement_required": status.acknowledgement_required,
                "action_required": status.action_required,
                "acknowledgement_id": status.operation_id,
                "durable": status.durable,
            }
        except Exception:
            return {
                "schema_version": 1,
                "code": "journal.unavailable",
                "owner": "unknown",
                "acknowledgement_required": False,
                "action_required": True,
                "acknowledgement_id": "",
                "durable": False,
            }

    async def acknowledge_sleep_journal(
        self, acknowledgement_id: str
    ) -> dict[str, object]:
        """Clear only the exact terminal result owned by canonical sleep."""
        try:
            acknowledged = await asyncio.to_thread(
                self._transition_journal_service().acknowledge_sleep,
                acknowledgement_id,
            )
        except Exception:
            acknowledged = False
        if acknowledged:
            self._automatic_dock.reset_after_acknowledgement()
        return {"schema_version": 1, "acknowledged": acknowledged}

    async def preview_process_release(
        self,
        phase: str,
        force_receipt_token: str = "",
    ) -> dict[str, object]:
        """Inspect exact eligible clients without creating signal authority."""
        try:
            release_phase = ReleasePhase(phase)
            preview = await asyncio.to_thread(
                self._process_service().preview,
                release_phase,
                user_confirmed=False,
                graceful_receipt_token=force_receipt_token,
            )
            return preview_to_payload(preview)
        except Exception:
            return self._process_preview_failure(phase)

    async def approve_process_release(
        self,
        phase: str,
        force_receipt_token: str = "",
    ) -> dict[str, object]:
        """Issue one exact signal approval after controller confirmation."""
        try:
            release_phase = ReleasePhase(phase)
            preview = await asyncio.to_thread(
                self._process_service().preview,
                release_phase,
                user_confirmed=True,
                graceful_receipt_token=force_receipt_token,
            )
            return preview_to_payload(preview)
        except Exception:
            return self._process_preview_failure(phase)

    async def execute_process_release(
        self, approval_token: str
    ) -> dict[str, object]:
        """Execute only a consumed approval through the guarded release runner."""
        try:
            outcome = await asyncio.to_thread(
                self._process_service().execute,
                approval_token,
            )
            payload = execution_to_payload(outcome)
            self._events.append(
                severity="warning" if outcome.action_required else "info",
                code=outcome.code,
                component="process_release",
                stage="execution",
                details={
                    "accepted": outcome.accepted,
                    "action_required": outcome.action_required,
                    "remaining_client_count": payload["remaining_client_count"],
                },
            )
            return payload
        except Exception:
            return {
                "schema_version": 1,
                "accepted": False,
                "code": "process_release.service_unavailable",
                "acknowledgement_id": "",
                "status": "",
                "software_blockers_cleared": False,
                "hardware_removal_authorized": False,
                "remaining_client_count": None,
                "force_receipt_token": "",
                "action_required": True,
            }

    async def acknowledge_process_release(
        self, acknowledgement_id: str
    ) -> dict[str, object]:
        """Clear only an exact terminal process-release operation."""
        try:
            acknowledged = await asyncio.to_thread(
                self._process_service().acknowledge,
                acknowledgement_id,
            )
        except Exception:
            acknowledged = False
        if acknowledged:
            self._automatic_dock.reset_after_acknowledgement()
        return {"schema_version": 1, "acknowledged": acknowledged}

    async def _main(self) -> None:
        build_version = str(self._build_info.get("version", "unknown"))
        build_revision = str(self._build_info.get("revision", "unavailable"))
        decky.logger.info(
            "HDM plugin started: version=%s revision=%s",
            build_version,
            build_revision,
        )
        self._events.append(
            severity="info",
            code="plugin.started",
            component="lifecycle",
            stage="startup",
            details={
                "version": build_version,
                "revision": build_revision,
            },
        )
        try:
            recovery = await asyncio.to_thread(
                self._process_service().recover_interrupted
            )
            if recovery.action_required:
                self._events.append(
                    severity="warning",
                    code=recovery.code,
                    component="process_release",
                    stage="startup_recovery",
                    details={"durable": recovery.durable},
                )
        except Exception:
            self._events.append(
                severity="error",
                code="process_release.startup_recovery_unavailable",
                component="process_release",
                stage="startup_recovery",
            )
        try:
            await self._reconcile_sleep_guard()
            payload = await self.get_snapshot()
            snapshot = payload["snapshot"]
            inference = payload["inference"]
            blocker_codes = [item["code"] for item in snapshot["blockers"]]
            decky.logger.info(
                "HDM diagnostics ready: mode=%s game=%s support=%s blockers=%s",
                inference["mode"],
                snapshot["game_state"],
                snapshot["support_tier"],
                blocker_codes,
            )
            self._events.append(
                severity="info",
                code="diagnostics.ready",
                component="discovery",
                stage="startup",
                details={
                    "mode": inference["mode"],
                    "game_state": snapshot["game_state"],
                    "support_tier": snapshot["support_tier"],
                    "blocker_codes": blocker_codes,
                },
            )
        except Exception:
            decky.logger.exception("HDM initial read-only snapshot failed")
            self._events.append(
                severity="error",
                code="diagnostics.initial_failed",
                component="discovery",
                stage="startup",
            )
        self._topology_wakeup = LinuxTopologyWakeup()
        monitor_ready = self._topology_wakeup.start()
        self._topology_wakeup_was_available = monitor_ready
        self._append_journey_event(
            severity="info" if monitor_ready else "warning",
            code="observation.events_ready" if monitor_ready else "observation.poll_fallback",
            component="connection", stage="observer_start", create_timeline=False,
        )
        self._sleep_guard_task = asyncio.create_task(self._sleep_guard_loop())
        self._automatic_dock_task = asyncio.create_task(self._automatic_dock_loop())
        self._native_recovery_task = asyncio.create_task(
            self._native_portable_recovery_loop()
        )

    async def _native_portable_recovery_loop(self) -> None:
        """Verify SteamOS' native fallback and restore captured Portable audio."""

        observations = SnapshotTransitionObservationAdapter(self._discovery)
        clock = SystemMonotonicClock()
        while True:
            delay_seconds = 1.0
            try:
                enabled = await asyncio.to_thread(
                    self._automatic_dock_preferences().load
                )
                current = await asyncio.to_thread(observations.observe)
                status = self._native_recovery.update(
                    enabled=enabled,
                    current=current,
                    now_ms=clock.now_ms(),
                )
                if status.stage is NativeRecoveryStage.WAITING:
                    delay_seconds = 0.25
                elif status.stage is NativeRecoveryStage.ACTION_REQUIRED:
                    delay_seconds = 2.0
                if status.code != self._last_native_recovery_code:
                    severity = (
                        "error"
                        if status.stage is NativeRecoveryStage.ACTION_REQUIRED
                        else "warning"
                        if status.stage is NativeRecoveryStage.WAITING
                        else "info"
                    )
                    self._events.append(
                        severity=severity,
                        code=status.code,
                        component="native_recovery",
                        stage=status.stage.value,
                    )
                    self._last_native_recovery_code = status.code
                if status.restore_portable_audio:
                    resolution = await asyncio.to_thread(
                        lambda: resolve_gamescope_user(GamescopeDiscovery().scan())
                    )
                    if resolution.ok and resolution.context is not None:
                        audio = await asyncio.to_thread(
                            self._audio_handoff_service().switch,
                            PlacementState.PORTABLE,
                            resolution.context,
                        )
                        self._events.append(
                            severity="info" if audio.succeeded else "warning",
                            code=audio.code,
                            component="native_recovery",
                            stage="audio_restore",
                        )
                    else:
                        self._events.append(
                            severity="warning",
                            code="native_recovery.audio_user_unavailable",
                            component="native_recovery",
                            stage="audio_restore",
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                self._events.append(
                    severity="warning",
                    code="native_recovery.observation_failed",
                    component="native_recovery",
                    stage="observation",
                )
            await asyncio.sleep(delay_seconds)

    async def _automatic_dock_loop(self) -> None:
        """Submit one exact, idle attach request through the shared transition engine."""
        observations = SnapshotTransitionObservationAdapter(self._discovery)
        while True:
            delay_seconds = self._automatic_dock_retry_seconds
            try:
                enabled = await asyncio.to_thread(
                    self._automatic_dock_preferences().load
                )
                current = await asyncio.to_thread(observations.observe)
                completion = await asyncio.to_thread(
                    self._presentation_transition_service().reconcile_completion, current
                )
                if completion.hold_portable:
                    self._automatic_dock.suppress_current_attachment_after_portable_return()
                if completion.code != self._last_completion_code:
                    self._last_completion_code = completion.code
                    self._append_journey_event(
                        severity="warning" if completion.code in {
                            "completion.storage_unavailable", "completion.receipt_unverified"
                        } else "info",
                        code=completion.code, component="presentation", stage="completion",
                        create_timeline=False,
                    )
                if _can_remember_portable_audio(current.snapshot):
                    resolution = await asyncio.to_thread(
                        lambda: resolve_gamescope_user(GamescopeDiscovery().scan())
                    )
                    if resolution.ok and resolution.context is not None:
                        await asyncio.to_thread(
                            self._audio_handoff_service().remember_portable,
                            resolution.context,
                        )
                if not enabled:
                    delay_seconds = 5.0
                    await self._wait_for_topology(delay_seconds)
                    continue
                readiness = await asyncio.to_thread(
                    self._record_topology_observation, current.snapshot
                )
                if enabled and readiness.stage is AttachReadinessStage.IDLE:
                    readiness = await asyncio.to_thread(
                        self._attach_readiness.arm_current, current
                    )
                    with self._topology_lock:
                        readiness_changed = (
                            readiness.code != self._last_attach_readiness_code
                        )
                        self._last_attach_readiness_code = readiness.code
                    if readiness_changed:
                        self._record_attach_readiness_status(readiness)
                decision = self._automatic_dock.update(
                    enabled=enabled,
                    readiness=readiness,
                    current=current,
                )
                delay_seconds = min(
                    delay_seconds, readiness.poll_after_ms / 1_000
                )
                if (
                    self._topology_wakeup is not None
                    and self._topology_wakeup.available
                    and readiness.stage is not AttachReadinessStage.SETTLING
                ):
                    delay_seconds = 5.0
                if decision.status.stage is AutomaticDockStage.DOCKED:
                    delay_seconds = 15.0
                elif readiness.stage is AttachReadinessStage.GAME_RUNNING:
                    delay_seconds = 5.0
                if decision.should_switch:
                    transition_started_ns = self._journey_now_ns()
                    self._append_journey_event(
                        severity="info",
                        code="connection.tv_transition_started",
                        component="connection",
                        stage="automatic_transition",
                        details={"target": PlacementState.DOCKED_EGPU.value},
                        now_ns=transition_started_ns,
                    )
                    try:
                        result = await asyncio.to_thread(
                            self._presentation_transition_service().execute_automatic,
                            PlacementState.DOCKED_EGPU,
                            expected_generation=decision.expected_generation,
                            standing_consent=enabled,
                        )
                    except Exception:
                        transition_finished_ns = self._journey_now_ns()
                        self._append_journey_event(
                            severity="error",
                            code="connection.tv_transition_exception",
                            component="connection",
                            stage="automatic_transition",
                            details={
                                "target": PlacementState.DOCKED_EGPU.value,
                                "duration_ms": self._bounded_elapsed_ms(
                                    transition_started_ns, transition_finished_ns
                                ),
                            },
                            now_ns=transition_finished_ns,
                        )
                        raise
                    succeeded = bool(
                        result.outcome
                        and result.outcome.kind is TransitionOutcomeKind.SUCCEEDED
                    )
                    transition_finished_ns = self._journey_now_ns()
                    self._append_journey_event(
                        severity="info" if succeeded else "warning",
                        code=result.code,
                        component="connection",
                        stage="automatic_transition",
                        details={
                            "target": PlacementState.DOCKED_EGPU.value,
                            "duration_ms": self._bounded_elapsed_ms(
                                transition_started_ns, transition_finished_ns
                            ),
                            "accepted": result.accepted,
                            "succeeded": succeeded,
                        },
                        now_ns=transition_finished_ns,
                    )
                    self._automatic_dock.record_result(
                        result.code, succeeded=succeeded
                    )
                    self._events.append(
                        severity="info" if succeeded else "warning",
                        code=result.code,
                        component="presentation",
                        stage="automatic_dock",
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                delay_seconds = 2.0
                self._events.append(
                    severity="warning",
                    code="automatic_dock.observation_failed",
                    component="presentation",
                    stage="automatic_dock",
                )
            await self._wait_for_topology(delay_seconds)

    async def _wait_for_topology(self, delay_seconds: float) -> None:
        """Events are invalidations only; the next iteration re-collects evidence."""
        monitor = self._topology_wakeup
        if monitor is None:
            await asyncio.sleep(delay_seconds)
            return
        was_available = self._topology_wakeup_was_available or monitor.available
        await monitor.wait(delay_seconds)
        self._topology_wakeup_was_available = monitor.available
        if was_available and not monitor.available:
            self._append_journey_event(
                severity="warning", code="observation.poll_fallback",
                component="connection", stage="observer_degraded", create_timeline=False,
            )

    async def _start_docked_igpu_lifecycle(self) -> None:
        if self._docked_igpu_task is not None:
            return
        self._docked_igpu_task = asyncio.create_task(
            self._docked_igpu_supervisor_loop()
        )

    async def _docked_igpu_supervisor_loop(self) -> None:
        while True:
            try:
                scheduler = await asyncio.to_thread(
                    self._build_docked_igpu_scheduler
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                self._record_docked_igpu_lifecycle(
                    "docked_igpu.lifecycle_unavailable", "warning"
                )
                await asyncio.sleep(self._docked_igpu_retry_seconds)
                continue
            self._docked_igpu_scheduler = scheduler
            self._record_docked_igpu_lifecycle(
                "docked_igpu.lifecycle_started", "info"
            )
            try:
                await scheduler.run()
                self._record_docked_igpu_lifecycle(
                    "docked_igpu.lifecycle_stopped", "warning"
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                self._record_docked_igpu_lifecycle(
                    "docked_igpu.lifecycle_failed", "warning"
                )
            finally:
                self._docked_igpu_scheduler = None
            await asyncio.sleep(self._docked_igpu_retry_seconds)

    def _record_docked_igpu_lifecycle(self, code: str, severity: str) -> None:
        if code == self._last_docked_igpu_lifecycle_code:
            return
        self._last_docked_igpu_lifecycle_code = code
        self._events.append(
            severity=severity,
            code=code,
            component="docked_igpu",
            stage="runtime",
        )

    def _build_docked_igpu_scheduler(self) -> DockedIgpuLifecycleScheduler:
        resolution = resolve_gamescope_user(GamescopeDiscovery().scan())
        if not resolution.ok or resolution.context is None:
            raise ValueError("Gamescope user is unavailable")
        snapshots = SnapshotTransitionObservationAdapter(self._discovery)
        games = GameScopeSessionObservationAdapter(
            UserBoundGameScopeScanAdapter(
                SystemdGameScopeDiscovery(),
                resolution.context.uid,
            )
        )
        watcher = DockedIgpuGameExitWatcher(
            snapshots=snapshots,
            games=games,
            gamescope_sessions=GamescopeSessionObservationAdapter(
                GamescopeDiscovery()
            ),
            clock=SystemMonotonicClock(),
        )
        promotion = DockedIgpuPromotionFacade(watcher=watcher)
        return DockedIgpuLifecycleScheduler(
            DockedIgpuWatchLifecycle(
                promotion,
                poll_interval_ms=5000,
                idle_poll_interval_ms=15000,
            )
        )

    async def _reconcile_sleep_guard(self) -> None:
        presence = await asyncio.to_thread(self._sleep_hardware.observe_presence)
        status = await asyncio.to_thread(self._sleep_guard.reconcile, presence)
        current = (presence.value, status.active, status.error)
        if current != self._last_sleep_guard_log:
            now_ns = self._journey_now_ns()
            journey_details = (
                self._journey_timing_details(
                    now_ns,
                    create=presence.value == "present",
                    reset_after=presence.value == "absent",
                )
                if presence.value in {"present", "absent"}
                else {}
            )
            decky.logger.info(
                "HDM sleep guard: presence=%s active=%s error=%s elapsed_ms=%s",
                presence.value,
                status.active,
                bool(status.error),
                journey_details.get("elapsed_ms", "unavailable"),
            )
            self._events.append(
                severity="warning" if status.error else "info",
                code="sleep_guard.state_changed",
                component="sleep_guard",
                stage="reconcile",
                details={
                    "presence": presence.value,
                    "active": status.active,
                    "error": bool(status.error),
                    **journey_details,
                },
            )
            self._last_sleep_guard_log = current

    async def _sleep_guard_loop(self) -> None:
        while True:
            try:
                await self._reconcile_sleep_guard()
            except Exception:
                decky.logger.exception("HDM sleep guard reconciliation failed")
                self._events.append(
                    severity="error",
                    code="sleep_guard.reconcile_failed",
                    component="sleep_guard",
                    stage="reconcile",
                )
            await asyncio.sleep(1)

    async def _unload(self) -> None:
        started_ns = self._journey_now_ns()
        self._record_shutdown_checkpoint("unload_started", started_ns)
        try:
            self._events.append(
                severity="info", code="plugin.unloading",
                component="lifecycle", stage="shutdown",
            )
        except Exception:
            pass
        # An already-failed observer must not prevent retiring our other tasks
        # or releasing the HDM-owned inhibitor. Never touch Steam/driver clients.
        for attribute in (
            "_automatic_dock_task", "_native_recovery_task",
            "_docked_igpu_task", "_sleep_guard_task",
        ):
            task = getattr(self, attribute)
            setattr(self, attribute, None)
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                self._record_shutdown_checkpoint("observer_stop_failed", started_ns)
        self._docked_igpu_scheduler = None
        if self._topology_wakeup is not None:
            try:
                self._topology_wakeup.close()
            except Exception:
                self._record_shutdown_checkpoint("observer_stop_failed", started_ns)
            self._topology_wakeup = None
        self._record_shutdown_checkpoint("observers_stopped", started_ns)
        self._record_shutdown_checkpoint("sleep_guard_release_started", started_ns)
        try:
            status = await asyncio.to_thread(self._sleep_guard.close)
        except Exception:
            self._record_shutdown_checkpoint("sleep_guard_release_failed", started_ns)
            return
        if status.active or status.error:
            self._record_shutdown_checkpoint("sleep_guard_release_failed", started_ns)
            return
        self._record_shutdown_checkpoint("sleep_guard_released", started_ns)
        self._record_shutdown_checkpoint("unload_complete", started_ns)
        # Do not drain asyncio's shared executor here. Cancellation stops the
        # coroutine that requested a read-only scan, but cannot cancel a scan
        # already running in a worker thread. Waiting for that worker can hold
        # Decky's unload hook past its five-second deadline and cause a forced
        # stop. Decky owns backend-process retirement after this hook returns;
        # HDM only owns and stops the tasks and resources it created.

    def _record_shutdown_checkpoint(self, stage: str, started_ns: int) -> None:
        """Existing journal only: no new collector, disk sync, or shutdown hook.

        Plugin unload may be an update, not poweroff. Completion never proves
        kernel teardown or physical poweroff; missing markers prove neither.
        """
        try:
            elapsed = self._bounded_elapsed_ms(started_ns, self._journey_now_ns())
            decky.logger.info(
                "HDM shutdown checkpoint: stage=%s elapsed_ms=%s", stage, elapsed
            )
        except Exception:
            pass

    async def _stop_docked_igpu_lifecycle(self) -> None:
        task = self._docked_igpu_task
        self._docked_igpu_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                self._events.append(
                    severity="warning",
                    code="docked_igpu.lifecycle_close_incomplete",
                    component="docked_igpu",
                    stage="shutdown",
                )
        self._docked_igpu_scheduler = None

    def _support_versions(self) -> dict[str, str]:
        return {
            "hdm": "0.2.0",
            "decky": str(getattr(decky, "DECKY_VERSION", "unknown")),
            "steamos": self._version_info.steamos,
            "kernel": self._version_info.kernel,
        }

    @staticmethod
    def _sensitive_values() -> tuple[str, ...]:
        home = str(getattr(decky, "DECKY_USER_HOME", ""))
        username = os.environ.get("DECKY_USER", "")
        return tuple(
            value
            for value in (home, Path(home).name if home else "", username, socket.gethostname())
            if value
        )

    def _write_support_bundle(self, bundle: SupportBundle) -> dict[str, object]:
        raw_home = Path(str(getattr(decky, "DECKY_USER_HOME", "")))
        result = self._support_writer.save(raw_home, bundle)
        return {
            "ok": True,
            "relative_path": result.relative_path,
            "size_bytes": result.size_bytes,
        }

    def _presentation_service(self) -> PresentationActivationService:
        resolution = resolve_gamescope_user(GamescopeDiscovery().scan())
        if not resolution.ok or resolution.context is None:
            raise ValueError("Gamescope user is unavailable")
        integration = GamescopeIntegrationStore(
            plugin_root=PLUGIN_ROOT,
            user=resolution.context,
        )
        return PresentationActivationService(
            observations=SnapshotTransitionObservationAdapter(self._discovery),
            integration=integration,
            commands=UserServiceCommandRunner(),
            resolve_user=lambda: resolve_gamescope_user(GamescopeDiscovery().scan()),
            approvals=self._presentation_approvals,
        )

    def _presentation_transition_service(self) -> SupervisedPresentationTransitionService:
        """Compose the exact prepared integration with the one transition engine."""
        resolution = resolve_gamescope_user(GamescopeDiscovery().scan())
        if not resolution.ok or resolution.context is None:
            raise ValueError("Gamescope user is unavailable")
        integration = GamescopeIntegrationStore(
            plugin_root=PLUGIN_ROOT,
            user=resolution.context,
        )
        journal_root = RootOwnedRuntimeState().ensure()
        presentation_state_root = (
            resolution.context.home / ".local" / "share" / "handheld-dock-mode"
        )
        observations = SnapshotTransitionObservationAdapter(self._discovery)
        journal = FileTransitionJournalStore(journal_root)
        mechanism = PresentationTransitionMechanism(
            integration=integration,
            # The prepared drop-in passes this exact per-user path to the shim.
            # The transaction journal remains root-only and is intentionally a
            # different store; placing launch config there makes the shim fall
            # back safely to the internal panel after a restart.
            config=PresentationConfigStore(presentation_state_root),
            commands=UserServiceCommandRunner(),
            resolve_user=lambda: resolve_gamescope_user(GamescopeDiscovery().scan()),
            read_boot_id=self._boot_session_id,
            audio=self._audio_handoff_service(),
        )
        orchestrator = TransitionOrchestrator(
            observations=observations,
            mechanism=mechanism,
            journal_store=journal,
            clock=SystemMonotonicClock(),
            waiter=BoundedDeadlineWaiter(),
        )
        return SupervisedPresentationTransitionService(
            observations=observations,
            orchestrator=orchestrator,
            journal_store=journal,
            integration_ready=lambda: integration.status().ready,
            approvals=self._presentation_transition_approvals,
        )

    def _audio_handoff_service(self) -> G1AudioHandoff:
        return G1AudioHandoff(
            commands=PipeWireCommandRunner(),
            state=PortableAudioStateStore(RootOwnedRuntimeState().ensure()),
            resolve_g1_audio_bdf=self._verified_g1_audio_bdf,
            report_result=self._record_audio_handoff_result,
        )

    def _record_audio_handoff_result(self, target, result) -> None:
        self._append_journey_event(
            severity="info" if result.succeeded else "warning",
            code=result.code,
            component="audio",
            stage="restore_portable" if target is PlacementState.PORTABLE else "select_tv",
            details={"target": target.value, "succeeded": result.succeeded},
        )

    def _safe_disconnect_shutdown_service(self) -> SafeDisconnectShutdownService:
        return SafeDisconnectShutdownService(
            observations=SnapshotTransitionObservationAdapter(self._discovery),
            power=SystemPowerCommandRunner(),
            approvals=self._safe_disconnect_shutdown_approvals,
        )

    @staticmethod
    def _verified_g1_audio_bdf() -> str:
        """Return the audio function only from a fresh exact G1 topology match."""
        pci = PciUsb4Discovery()
        matched = match_gpd_g1(
            DrmDiscovery().scan(), pci.scan_pci(), pci.scan_usb4()
        )
        return matched.audio_bdf if matched.verified else ""

    def _automatic_dock_preferences(self) -> AutomaticDockPreferenceStore:
        if self._automatic_dock_preference_store is None:
            self._automatic_dock_preference_store = AutomaticDockPreferenceStore(
                RootOwnedRuntimeState().ensure()
            )
        return self._automatic_dock_preference_store

    @staticmethod
    def _automatic_dock_failure(
        code: str,
        *,
        stage: AutomaticDockStage = AutomaticDockStage.ACTION_REQUIRED,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "enabled": False,
            "stage": stage.value,
            "code": code,
        }

    @staticmethod
    def _presentation_transition_failure(code: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "accepted": False,
            "code": code,
            "acknowledgement_id": "",
            "acknowledgement_required": False,
        }

    def _process_service(self) -> GuardedProcessReleaseService:
        if self._process_release is not None:
            return self._process_release
        state_root = RootOwnedRuntimeState().ensure()
        journal = FileTransitionJournalStore(state_root)
        observations = SnapshotTransitionObservationAdapter(self._discovery)
        occurred_at = lambda: datetime.now(timezone.utc).isoformat()
        recovery = ProcessReleaseJournalRecovery(
            journal,
            occurred_at=occurred_at,
        )
        runner = ProcessReleaseRunner(
            observations,
            PosixProcessSignalAdapter(),
            SystemMonotonicClock(),
            journal_store=journal,
            occurred_at=occurred_at,
        )
        self._process_release = GuardedProcessReleaseService(
            observations=observations,
            approvals=self._process_approvals,
            receipts=self._process_receipts,
            runner=runner,
            journal_store=journal,
            recovery=recovery,
        )
        return self._process_release

    @staticmethod
    def _transition_journal_service() -> SharedTransitionJournalService:
        return SharedTransitionJournalService(
            FileTransitionJournalStore(RootOwnedRuntimeState().ensure())
        )

    @staticmethod
    def _process_preview_failure(phase: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "phase": phase if phase in {item.value for item in ReleasePhase} else "",
            "ready": False,
            "approval_token": "",
            "expires_in_seconds": 0,
            "targets": [],
            "protected_client_count": 0,
            "blockers": ["process_release.service_unavailable"],
            "confirmation_required": False,
        }
