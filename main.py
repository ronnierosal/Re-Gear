"""Root Decky delivery adapter for the read-only Re-Gear diagnostics API."""

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

from regear.adapters.steamos.discovery import SteamOsDiscovery  # noqa: E402
from regear.adapters.steamos.topology_wakeup import LinuxTopologyWakeup  # noqa: E402
from regear.adapters.steamos.tdp_provider import SteamOsManagerTdpProvider  # noqa: E402
from regear.adapters.steamos.tdp_conflicts import KnownTdpControllerScan  # noqa: E402
from regear.delivery.tdp_journal import FileTdpJournal  # noqa: E402
from regear.delivery.tdp_runtime import TdpRuntime, unavailable_status  # noqa: E402
from regear.delivery.tdp_writer_lease import FileTdpWriterLease  # noqa: E402
from regear.delivery.auto_tdp_configuration import FileAutoTdpConfiguration  # noqa: E402
from regear.delivery.auto_tdp_factory import AutoTdpSessionFactory  # noqa: E402
from regear.delivery.auto_tdp_evidence import AutoTdpEligibility  # noqa: E402
from regear.delivery.auto_tdp_status import auto_tdp_status  # noqa: E402
from regear.delivery.auto_tdp_benchmark import benchmark_auto_tdp  # noqa: E402
from regear.adapters.steamos.auto_tdp_host import AutoTdpHostDiscovery  # noqa: E402
from regear.adapters.steamos.gamescope_performance_target import GamescopePerformanceTargetResolver, PerformanceTargetResolution  # noqa: E402
from regear.domain.auto_tdp import AutoTdpPolicy  # noqa: E402
from regear.domain.telemetry import TelemetryAdmissionKind, admit_telemetry_collection  # noqa: E402
from regear.adapters.steamos.drm import DrmDiscovery  # noqa: E402
from regear.adapters.steamos.pci import PciUsb4Discovery  # noqa: E402
from regear.adapters.steamos.wake_diagnostics import WakeDiagnosticsDiscovery  # noqa: E402
from regear.adapters.steamos.commands import (  # noqa: E402
    PipeWireCommandRunner,
    SystemPowerCommandRunner,
    UserServiceCommandRunner,
)
from regear.adapters.steamos.audio_handoff import G1AudioHandoff, G1AudioReadiness  # noqa: E402
from regear.adapters.steamos.connection_readiness import G1ConnectionTopologyDiscovery  # noqa: E402
from regear.adapters.steamos.gamescope import GamescopeDiscovery  # noqa: E402
from regear.adapters.steamos.gamescope_session import (  # noqa: E402
    GamescopeSessionObservationAdapter,
)
from regear.adapters.steamos.gamescope_user import resolve_gamescope_user  # noqa: E402
from regear.adapters.steamos.owner_identity import read_boot_hash  # noqa: E402
from regear.delivery.game_close_preferences import (  # noqa: E402
    GameClosePreferenceStore,
)
from regear.delivery.relaunch_intent_store import RelaunchIntentStore  # noqa: E402
from regear.domain.relaunch_intent import (  # noqa: E402
    RelaunchClock,
    RelaunchIntent,
    decide_relaunch,
)
from regear.delivery.live_disconnect_runtime import (  # noqa: E402
    CATALOG_ROOT,
    close_prompt_to_payload,
    DisconnectAvailability,
    LiveDisconnectRuntime,
    build_live_disconnect_runtime,
    disconnect_result_to_payload,
    disconnect_status_to_payload,
)
from regear.domain.game_close_consent import (  # noqa: E402
    GameClosePreference,
    InterruptIntent,
    decide_game_close,
)
from regear.domain.game_compatibility import STEAM_APP_ID_RE  # noqa: E402
from regear.adapters.steamos.sleep_inhibitor import (  # noqa: E402
    G1SleepGuardHardwareDiscovery,
    SleepGuardController,
)
from regear.adapters.steamos.process_signal import PosixProcessSignalAdapter  # noqa: E402
from regear.adapters.game_runtime import CgroupProcGameRuntimeAdapter  # noqa: E402
from regear.adapters.game_session import (  # noqa: E402
    GameScopeSessionObservationAdapter,
    UserBoundGameScopeScanAdapter,
)
from regear.adapters.drm_engine_activity import (  # noqa: E402
    ProcfsDrmEngineCounterAdapter,
)
from regear.adapters.steamos.game_render_binding import (  # noqa: E402
    AllyInternalDrmRenderBindingResolver,
    GpdG1DrmRenderBindingResolver,
)
from regear.adapters.steamos.game_scopes import SystemdGameScopeDiscovery  # noqa: E402
from regear.adapters.steamos.version_info import SteamOsVersionDiscovery  # noqa: E402
from regear.adapters.steamos.peripherals import (  # noqa: E402
    SteamOsPeripheralObservationAdapter,
    peripheral_status_to_public_payload,
)
from regear.api import DiagnosticsApi  # noqa: E402
from regear.adapters.steamos.offline_steam_details import project_steam_app_details  # noqa: E402
from regear.application.offline_details import classify_minimized_steam_details  # noqa: E402
from regear.adapters.transition_runtime import (  # noqa: E402
    BoundedDeadlineWaiter,
    SnapshotTransitionObservationAdapter,
    SystemMonotonicClock,
    versioned_snapshot_observation,
)
from regear.adapters.presentation_transition import (  # noqa: E402
    PresentationTransitionMechanism,
)
from regear.application.game_evidence_support import (  # noqa: E402
    SupportGameEvidenceService,
)
from regear.application.game_gpu_client import GameEgpuClientEvidenceService  # noqa: E402
from regear.application.game_render_activity import (  # noqa: E402
    GameRenderActivityComparisonService,
)
from regear.application.diagnostic_logging import (  # noqa: E402
    DiagnosticLoggingController,
    DiagnosticLoggingDuration,
    DiagnosticVerbosity,
)
from regear.application.action_history import project_action_history  # noqa: E402
from regear.application.snapshot import report_to_public_dict  # noqa: E402
from regear.application.attach_readiness import (  # noqa: E402
    AttachReadinessLifecycle,
    AttachReadinessStage,
)
from regear.application.connection_readiness import (  # noqa: E402
    ConnectionReadinessLifecycle,
    ConnectionReadinessObservation,
    ConnectionReadinessStage,
)
from regear.application.link_recovery import (  # noqa: E402
    LinkRecoveryService,
    LinkRecoveryStrategy,
    strategy_is_implemented,
)
from regear.domain.link_training_recovery import (  # noqa: E402
    LinkRecoveryAvailability,
)
from regear.application.automatic_dock import (  # noqa: E402
    AutomaticDockCoordinator,
    AutomaticDockStage,
    verified_egpu_absent,
)
from regear.application.saved_tv_search import SavedTvSearch  # noqa: E402
from regear.application.native_portable_recovery import (  # noqa: E402
    NativePortableRecoverySupervisor,
    NativeRecoveryStage,
)
from regear.application.safe_disconnect_shutdown import (  # noqa: E402
    SafeDisconnectShutdownApprovalStore,
    SafeDisconnectShutdownService,
)
from regear.application.topology_event_detection import (  # noqa: E402
    TopologyDetectionStatus,
    detect_topology_event,
)
from regear.application.docked_igpu_exit import DockedIgpuGameExitWatcher  # noqa: E402
from regear.application.docked_igpu_lifecycle import DockedIgpuWatchLifecycle  # noqa: E402
from regear.application.docked_igpu_promotion import DockedIgpuPromotionFacade  # noqa: E402
from regear.application.presentation_activation import (  # noqa: E402
    PresentationActivationApprovalStore,
    PresentationActivationService,
)
from regear.application.experimental_transition import (  # noqa: E402
    ExperimentalTransitionApprovalStore,
)
from regear.application.supervised_transition import (  # noqa: E402
    SupervisedPresentationTransitionService,
)
from regear.application.shared_transition_journal import (  # noqa: E402
    SharedTransitionJournalService,
)
from regear.application.transition_orchestrator import TransitionOrchestrator  # noqa: E402
from regear.application.guarded_process_release import (  # noqa: E402
    GuardedProcessReleaseService,
)
from regear.application.process_release import (  # noqa: E402
    GracefulReleaseReceiptStore,
    ProcessReleaseApprovalStore,
)
from regear.application.process_release_replay import (  # noqa: E402
    ProcessReleaseJournalRecovery,
    ProcessReleaseRunner,
)
from regear.application.support_bundle import (  # noqa: E402
    BoundedEventLog,
    SupportBundle,
    SupportBundleContext,
    SupportBundlePreviewStore,
    SupportBundleService,
    WakeDiagnosticsSupportStatus,
)
from regear.delivery.support_export import SupportBundleFileWriter  # noqa: E402
from regear.delivery.gamescope_integration import GamescopeIntegrationStore  # noqa: E402
from regear.delivery.presentation_config import PresentationConfigStore  # noqa: E402
from regear.delivery.process_release import (  # noqa: E402
    execution_to_payload,
    preview_to_payload,
    status_to_payload,
)
from regear.delivery.presentation_transition import (  # noqa: E402
    status_to_payload as presentation_transition_status_to_payload,
)
from regear.delivery.game_evidence_support import (  # noqa: E402
    game_evidence_to_event_details,
)
from regear.delivery.diagnostic_logging import (  # noqa: E402
    diagnostic_logging_status_to_payload,
)
from regear.delivery.build_info import load_public_build_info  # noqa: E402
from regear.delivery.action_history import action_history_to_payload  # noqa: E402
from regear.delivery.attach_readiness import attach_readiness_to_payload  # noqa: E402
from regear.delivery.docked_igpu_lifecycle import lifecycle_status_to_payload  # noqa: E402
from regear.delivery.peripheral_support import peripheral_support_status  # noqa: E402
from regear.delivery.docked_igpu_scheduler import (  # noqa: E402
    DockedIgpuLifecycleScheduler,
)
from regear.delivery.runtime_state import RootOwnedRuntimeState  # noqa: E402
from regear.delivery.automatic_dock_preferences import (  # noqa: E402
    AutomaticDockPreferenceStore,
)
from regear.delivery.saved_tv_store import SavedTvStore  # noqa: E402
from regear.delivery.audio_state import PortableAudioStateStore  # noqa: E402
from regear.delivery.transition_journal_store import FileTransitionJournalStore  # noqa: E402
from regear.domain.process_release import ReleasePhase  # noqa: E402
from regear.domain.control_plane import (  # noqa: E402
    PlacementState,
    TransitionOutcomeKind,
)
from regear.domain.models import Confidence, EgpuLinkState, GameState, GpuRole, EgpuPresence, OperatingMode  # noqa: E402
from regear.domain.inference import infer_operating_mode  # noqa: E402
from regear.domain.tdp_placement import tdp_placement_readiness  # noqa: E402
from regear.domain.auto_tdp_preferences import AutoTdpModePreference  # noqa: E402
from regear.delivery.auto_tdp_preferences import FileAutoTdpPreferences  # noqa: E402
from regear.domain.inference import infer_placement  # noqa: E402
from regear.domain.saved_tv import DEFAULT_MAX_ATTEMPTS  # noqa: E402
from regear.profiles.gpd_g1 import match_gpd_g1  # noqa: E402


MAX_JOURNEY_ELAPSED_MS = 24 * 60 * 60 * 1000
UNLOAD_OBSERVER_TIMEOUT_SECONDS = 1.0
UNLOAD_GUARD_TIMEOUT_SECONDS = 3.0


def _relaunch_now(clock: RelaunchClock) -> float:
    """Read the clock a relaunch intent is aged against.

    Never the wall clock: an NTP step during a session restart must not make a
    stale intent look fresh. Which of the two matters, and the record says
    which it was written for -- `BOOTTIME` keeps counting through a suspend,
    `MONOTONIC` does not, and that difference is the whole reason a sleep can
    be reopened hours later while a disconnect cannot.
    """
    if clock is RelaunchClock.BOOTTIME:
        boottime = getattr(time, "CLOCK_BOOTTIME", None)
        if boottime is not None:
            try:
                return time.clock_gettime(boottime)
            except OSError:
                pass
    return time.monotonic()


def _relaunch_clock_for(intent: InterruptIntent) -> RelaunchClock:
    """Which clock ages a reopen asked for by this action."""
    return (
        RelaunchClock.MONOTONIC
        if intent is InterruptIntent.SLEEP
        else RelaunchClock.BOOTTIME
    )


def _parse_intent(value: object) -> InterruptIntent | None:
    """The action a caller names, or None when it names nothing known.

    Not defaulted. An answer filed against the wrong action is an answer the
    player did not give, and guessing which one they meant is exactly the
    mistake the per-intent key exists to prevent.
    """
    try:
        return InterruptIntent(value)
    except ValueError:
        return None


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


def _exact_g1_link_is_up(snapshot) -> bool:
    """Accept the exact bridge's read-only observed Up state."""
    return bool(
        snapshot.egpu_link.applicable
        and snapshot.egpu_link.state is EgpuLinkState.UP
        and snapshot.egpu_link.confidence
        in {Confidence.OBSERVED, Confidence.VERIFIED}
    )


def _display_scan_complete(snapshot) -> bool:
    """Whether the connector inventory was actually read on this observation.

    An unavailable DRM inventory is not evidence that a TV is absent, and must
    not spend the bounded saved-TV search: a reader that keeps failing would
    otherwise exhaust the budget and abandon a TV that was there all along.
    """
    return bool(snapshot.displays) and not any(
        blocker.code == "drm_inventory_unavailable" for blocker in snapshot.blockers
    )


def _docked_tv_display(snapshot):
    """The one external display a completed dock is actually presenting on.

    Read from the observation rather than taken from the request, so what earns
    a saved profile is the TV the player ended up on -- external, connected and
    verifiably driving the session -- and not the target a transition set out
    to reach.
    """
    if infer_placement(snapshot) is not PlacementState.DOCKED_EGPU:
        return None
    active = [display for display in snapshot.displays if display.active is True]
    return active[0] if len(active) == 1 else None



#: The eGPU's GPU function on the tested profile, matching the default the
#: operator tools use, so the backend and the CLI act on the same device.
#:
#: Fixed rather than discovered because the supported set is one device on one
#: host, and a wrong address here would compose a plan for something else. A
#: second supported eGPU needs this resolved from the observation instead.
EGPU_GPU_FUNCTION = "0000:08:00.0"

class Plugin:
    def __init__(self) -> None:
        self._unloading = False
        self._background_operations: set[asyncio.Task] = set()
        self._retiring_tasks: set[asyncio.Task] = set()
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
        self._connection_wake_source = "startup"
        self._last_completion_code = ""
        self._last_audio_readiness_code = ""
        self._automatic_dock = AutomaticDockCoordinator()
        # One instance for the life of the plugin, deliberately. Its latch is
        # the whole point, and a service rebuilt per call would arrive with a
        # fresh latch every time and offer the same failed recovery forever.
        self._link_recovery: LinkRecoveryService | None = None
        self._last_readiness_observation: ConnectionReadinessObservation | None = None
        self._native_recovery_task: asyncio.Task[None] | None = None
        self._native_recovery = NativePortableRecoverySupervisor()
        self._last_native_recovery_code = ""
        self._automatic_dock_preference_store: AutomaticDockPreferenceStore | None = None
        self._saved_tv: SavedTvSearch | None = None
        self._saved_tv_decision = None
        self._saved_tv_attempts = 0
        # An explicitly successful TV transition, not yet observed presenting.
        self._saved_tv_pending_dock = False
        self._saved_tv_armed = False
        self._last_saved_tv_code = ""
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
        self._connection_readiness = ConnectionReadinessLifecycle()
        self._connection_checks = None
        self._connection_checks_at = 0.0
        self._connection_topology = G1ConnectionTopologyDiscovery()
        self._last_connection_readiness_code = self._connection_readiness.status().code
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
        self._steam_trial_approvals = PresentationActivationApprovalStore()
        self._presentation_transition_approvals = ExperimentalTransitionApprovalStore()
        self._safe_disconnect_shutdown_approvals = (
            SafeDisconnectShutdownApprovalStore()
        )
        self._process_approvals = ProcessReleaseApprovalStore()
        self._process_receipts = GracefulReleaseReceiptStore()
        self._process_release: GuardedProcessReleaseService | None = None
        self._version_info = SteamOsVersionDiscovery().scan()
        self._build_info = load_public_build_info(PLUGIN_ROOT)
        self._tdp_runtime: TdpRuntime | None = None
        self._live_disconnect: LiveDisconnectRuntime | None = None
        self._live_disconnect_key: tuple[str, int] | None = None
        self._live_disconnect_lock = threading.Lock()
        self._tdp_init_lock = threading.Lock()
        self._tdp_closing = threading.Event()
        self._auto_request_lock = threading.Lock()
        self._auto_request_generation = 0
        self._benchmark_request_generation = 0
        self._auto_cancel_requested = threading.Event()
        self._auto_cancel_requested.set()

    async def get_tdp_status(self, _request: object = None) -> dict[str, object]:
        return await self._tdp_call("status")

    async def set_tdp_enabled(self, enabled: bool) -> dict[str, object]:
        if enabled is False:
            self._cancel_auto_request()
        return await self._tdp_call("set_enabled", enabled)

    async def apply_tdp_limit(self, watts: int) -> dict[str, object]:
        self._cancel_auto_request()
        return await self._tdp_call("apply", watts)

    async def restore_tdp_limit(self) -> dict[str, object]:
        self._cancel_auto_request()
        return await self._tdp_call("restore")

    async def get_auto_tdp_status(self, _request: object = None) -> dict[str, object]:
        return await asyncio.to_thread(self._auto_tdp_status_sync)

    async def start_auto_tdp(self, target_fps: float, minimum_watts: int, maximum_watts: int) -> dict[str, object]:
        try:
            policy = AutoTdpPolicy(minimum_watts, maximum_watts, target_fps)
        except (TypeError, ValueError):
            return auto_tdp_status("auto_tdp.request_invalid", self._tdp_runtime)
        with self._auto_request_lock:
            generation = self._auto_request_generation
            self._auto_cancel_requested.clear()
        def start():
            before = self._auto_tdp_status_sync()
            if not before["can_start"]:
                return before
            with self._auto_request_lock:
                if generation != self._auto_request_generation:
                    return auto_tdp_status("auto_tdp.stopped", self._tdp_runtime)
            runtime = self._tdp_service()
            if runtime.start_auto(policy, admission_guard=lambda: self._auto_request_generation == generation
                                  and not self._tdp_closing.is_set()) is None:
                return auto_tdp_status("auto_tdp.start_unavailable", runtime)
            return self._auto_tdp_status_sync()
        try:
            return await asyncio.to_thread(start)
        except Exception:
            return auto_tdp_status("auto_tdp.runtime_unavailable", self._tdp_runtime)

    def _cancel_auto_request(self):
        with self._auto_request_lock:
            self._auto_request_generation += 1
            self._benchmark_request_generation += 1
            self._auto_cancel_requested.set()
        if self._tdp_runtime is not None:
            self._tdp_runtime.cancel_benchmark()

    async def stop_auto_tdp(self) -> dict[str, object]:
        # Revoke admission immediately, including while another RPC reads state.
        self._cancel_auto_request()
        runtime = self._tdp_runtime
        if runtime is not None:
            runtime.stop_auto()
        return auto_tdp_status("auto_tdp.stopped", runtime)

    def _auto_configuration(self):
        return FileAutoTdpConfiguration(RootOwnedRuntimeState().ensure()).load()

    def _auto_preferences_store(self):
        with self._tdp_init_lock:
            if not hasattr(self, "_auto_preferences_file"):
                self._auto_preferences_file = FileAutoTdpPreferences(RootOwnedRuntimeState().ensure())
            return self._auto_preferences_file

    @staticmethod
    def _auto_preferences_payload(result):
        return {"schema_version": 1, "code": result.code, "preferences": [] if result.preferences is None else [
            {"placement": item.placement.value, "target_fps": item.target_fps,
             "minimum_watts": item.minimum_watts, "maximum_watts": item.maximum_watts}
            for item in result.preferences.preferences]}

    async def get_auto_tdp_preferences(self):
        try:
            result = await asyncio.to_thread(lambda: self._auto_preferences_store().load())
            return self._auto_preferences_payload(result)
        except Exception:
            return {"schema_version": 1, "code": "auto_tdp_preferences.invalid", "preferences": []}

    async def save_auto_tdp_preference(self, placement, target_fps, minimum_watts, maximum_watts):
        try:
            preference = AutoTdpModePreference(PlacementState(placement), AutoTdpPolicy(minimum_watts, maximum_watts, target_fps))
            result = await asyncio.to_thread(lambda: self._auto_preferences_store().save_preference(preference))
            return self._auto_preferences_payload(result)
        except Exception:
            return {"schema_version": 1, "code": "auto_tdp_preferences.save_failed", "preferences": []}

    def _benchmark_status(self, code=None):
        runtime = self._tdp_runtime
        if runtime is not None:
            return runtime.benchmark_status(code)
        return {"schema_version": 1, "running": False, "cancelling": False,
                "code": code or "auto_tdp.benchmark_idle", "result": None}

    async def get_auto_tdp_benchmark_status(self) -> dict[str, object]:
        return self._benchmark_status()

    async def cancel_auto_tdp_benchmark(self) -> dict[str, object]:
        with self._auto_request_lock:
            self._benchmark_request_generation += 1
        if self._tdp_runtime is not None:
            self._tdp_runtime.cancel_benchmark()
        return self._benchmark_status()

    async def run_auto_tdp_benchmark(self) -> dict[str, object]:
        with self._auto_request_lock:
            generation = self._benchmark_request_generation
        def run():
            if self._tdp_closing.is_set():
                return self._benchmark_status("tdp.closing")
            loaded = self._auto_configuration()
            if loaded.configuration is None:
                return self._benchmark_status(loaded.code)
            config = loaded.configuration
            if not self._auto_eligibility().ready:
                return self._benchmark_status("auto_tdp.game_or_render_unverified")
            runtime = self._tdp_service()
            def measure(provider, cancel):
                factory = self._configured_auto_factory(config, self._auto_eligibility)
                return benchmark_auto_tdp(factory.create_evidence(provider), cancel=cancel,
                                         interval_ms=config.collection_contract.interval_ms)
            return runtime.run_benchmark(measure, admission_guard=lambda:
                generation == self._benchmark_request_generation and not self._tdp_closing.is_set())
        try:
            return await asyncio.to_thread(run)
        except Exception:
            return self._benchmark_status("auto_tdp.benchmark_unavailable")

    def _auto_eligibility(self):
        if self._tdp_closing.is_set():
            return AutoTdpEligibility(GameState.UNKNOWN, False)
        snapshot = self._api.get_snapshot_report().snapshot
        return AutoTdpEligibility(snapshot.game_state,
            infer_operating_mode(snapshot).mode is OperatingMode.PORTABLE
            and self._tdp_preflight() == "tdp.ready")

    @staticmethod
    def _auto_target():
        gamescope = GamescopeDiscovery().scan()
        user = resolve_gamescope_user(gamescope).context
        if user is None:
            return PerformanceTargetResolution("performance.game_unverified")
        game = SystemdGameScopeDiscovery().scan(user_uid=user.uid)
        return GamescopePerformanceTargetResolver().resolve(game, gamescope)

    def _auto_session(self, actuator, provider):
        config = self._auto_configuration().configuration
        if config is None:
            raise ValueError("Auto TDP configuration unavailable")
        factory = self._configured_auto_factory(config, lambda:
            AutoTdpEligibility(GameState.UNKNOWN, False)
            if self._auto_cancel_requested.is_set() else self._auto_eligibility())
        return factory(actuator, provider)

    def _configured_auto_factory(self, config, eligibility):
        return AutoTdpSessionFactory(resolve=self._auto_target, eligibility=eligibility,
            sensor_config=config.sensor_config,
            host_context_key=config.host_context_key,
            thermal_evidence_reference=config.thermal_evidence_reference,
            contract=config.collection_contract)

    def _auto_tdp_status_sync(self):
        runtime = self._tdp_runtime
        try:
            if self._tdp_closing.is_set():
                return auto_tdp_status("auto_tdp.closing", runtime)
            loaded = self._auto_configuration()
            config = loaded.configuration
            if config is None:
                return auto_tdp_status(loaded.code, runtime)
            runtime = self._tdp_service()
            manual = runtime.status()
            if not manual["ready"]:
                return auto_tdp_status(manual["code"], runtime)
            eligibility = self._auto_eligibility()
            if not eligibility.ready:
                return auto_tdp_status("auto_tdp.game_or_render_unverified", runtime)
            admission = admit_telemetry_collection(config.collection_contract,
                eligibility.game_state, auto_tdp_enabled=True)
            if admission.kind is not TelemetryAdmissionKind.ADMIT:
                return auto_tdp_status(admission.reason, runtime)
            reading = runtime.auto_context()
            observed = AutoTdpHostDiscovery().observe(reading)
            if observed.context_key != config.host_context_key:
                return auto_tdp_status("auto_tdp.configuration_context_changed", runtime)
            return auto_tdp_status("auto_tdp.ready", runtime)
        except Exception:
            return auto_tdp_status("auto_tdp.runtime_unavailable", runtime)

    async def _tdp_call(self, operation: str, *args) -> dict[str, object]:
        if self._tdp_closing.is_set():
            return unavailable_status("tdp.closing")
        def call():
            runtime = self._tdp_service()
            return getattr(runtime, operation)(*args)
        try:
            return await asyncio.to_thread(call)
        except Exception:
            return unavailable_status()

    @staticmethod
    def _tdp_user():
        return resolve_gamescope_user(GamescopeDiscovery().scan()).context

    def _tdp_preflight(self) -> str:
        if self._tdp_closing.is_set():
            return "tdp.closing"
        journal = self._transition_journal_service().status()
        if not journal.durable or journal.owner.value != "none":
            return "tdp.transition_active"
        snapshot = self._api.get_snapshot_report().snapshot
        if snapshot.game_state is GameState.UNKNOWN:
            return "tdp.game_unknown"
        placement = tdp_placement_readiness(snapshot, self._sleep_hardware.observe_presence())
        if placement != "tdp.ready":
            return placement
        user = self._tdp_user()
        if user is None:
            return "tdp.user_unverified"
        conflicts = KnownTdpControllerScan(plugins_root=user.home / "homebrew/plugins").scan()
        if conflicts.conflicts:
            return "tdp.conflict"
        if not conflicts.complete:
            return "tdp.conflict_scan_unavailable"
        return "tdp.ready"

    def _tdp_service(self) -> TdpRuntime:
        with self._tdp_init_lock:
            if self._tdp_closing.is_set():
                raise RuntimeError("TDP runtime is closing")
            if self._tdp_runtime is None:
                state_root = RootOwnedRuntimeState().ensure()
                self._tdp_runtime = TdpRuntime(
                    provider_factory=lambda ready: SteamOsManagerTdpProvider(
                        user_resolver=self._tdp_user, ownership_ready=ready,
                    ),
                    journal=FileTdpJournal(state_root),
                    lease=FileTdpWriterLease(state_root),
                    preflight=self._tdp_preflight,
                    auto_session_factory=self._auto_session,
                )
            if self._tdp_closing.is_set():
                self._tdp_runtime.close()
                raise RuntimeError("TDP runtime is closing")
            return self._tdp_runtime

    async def classify_offline_details(self, details: object = None) -> dict[str, object]:
        """Classify one minimized report without starting a hardware lifecycle."""
        try:
            report = await asyncio.to_thread(self._api.get_snapshot_report)
            game_state = report.snapshot.game_state
        except Exception:
            # Do not log exceptions or raw Steam data across this privacy boundary.
            game_state = GameState.UNKNOWN
        return classify_minimized_steam_details(
            details, game_state=game_state, project_details=project_steam_app_details,
        )

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
        connection = self._connection_readiness.status()
        payload["connection_readiness"] = {
            "schema_version": 1,
            "stage": connection.stage.value,
            "code": connection.code,
            "poll_after_ms": connection.poll_after_ms,
            "window_age_ms": connection.window_age_ms,
            "checks": getattr(self, "_connection_checks", None),
            "checks_age_ms": max(0, int((time.monotonic() - getattr(self, "_connection_checks_at", 0.0)) * 1000)),
        }
        payload["saved_tv"] = self._saved_tv_status()
        await asyncio.to_thread(self._record_verbose_snapshot, payload)
        return payload

    def _saved_tv_status(self) -> dict[str, object]:
        """Categorical state for the waiting half of a dock.

        The saved display identity, and the label EDID gave it, stay on the
        root-owned record and never cross this boundary. A state and a code are
        all a caller needs to tell "the eGPU is ready and your saved TV has not
        appeared" from "it was not found" from a flat failure -- and `searching`
        says whether a search is running at all, so no state has to be invented
        for the times one is not.
        """
        decision = self._saved_tv_decision
        return {
            "schema_version": 1,
            "searching": decision is not None,
            "state": decision.state.value if decision is not None else "",
            "code": decision.code if decision is not None else "",
            "attempts": self._saved_tv_attempts,
            "max_attempts": DEFAULT_MAX_ATTEMPTS,
        }

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
            # Attachment checks do not include managed session integration.
            # Keep their ready event distinct from full connection readiness.
            component="attach_readiness",
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
                decky.logger.exception("Re-Gear G1 journey support event failed")
            except Exception:
                pass
        try:
            decky.logger.info(
                "Re-Gear G1 journey: component=%s stage=%s code=%s elapsed_ms=%s stage_elapsed_ms=%s",
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
        """Return the bounded, identity-free projection of existing Re-Gear events."""
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

    async def get_link_recovery_status(
        self, _request: object = None
    ) -> dict[str, object]:
        """Say whether bouncing the session would be worth offering. Changes nothing.

        Safe to poll. Answers from the reading the readiness loop already took,
        so asking never probes hardware and never disagrees with the panel.

        Also reports which mechanisms exist and which are built, because the
        mechanism is an open question: the link is observed about a second
        after a new session starts, and nothing has isolated why.
        """
        service = self._link_recovery_service()
        strategies = [
            {
                "strategy": candidate.value,
                "implemented": strategy_is_implemented(candidate),
            }
            for candidate in LinkRecoveryStrategy
        ]
        observation = self._last_readiness_observation
        if observation is None:
            return {
                "schema_version": 1,
                "availability": LinkRecoveryAvailability.UNAVAILABLE.value,
                "offered": False,
                "code": "link_recovery.no_observation",
                "default_strategy": service.default_strategy.value,
                "strategies": strategies,
            }
        assessment = service.assess(
            readiness_exhausted=(
                self._connection_readiness.status().stage
                is ConnectionReadinessStage.TIMED_OUT
            ),
            transport_present=observation.transport_present,
            pci_complete=observation.pci_complete,
            game_state=observation.game_state,
        )
        return {
            "schema_version": 1,
            "availability": assessment.availability.value,
            "offered": assessment.offered,
            "code": assessment.code,
            "default_strategy": service.default_strategy.value,
            "strategies": strategies,
        }

    async def execute_link_recovery(
        self, confirm: bool = False, strategy: str = ""
    ) -> dict[str, object]:
        """Bounce the session by the chosen mechanism and watch for the link.

        This closes whatever is on screen. It is never automatic and never
        implied: `confirm` has to be exactly True, the same shape the automatic
        dock opt-in uses, so no caller reaches it by passing a truthy default.

        `strategy` picks which mechanism to try and defaults to the plain
        session bounce. It exists because the mechanism is not settled -- the
        link is observed about a second after a new session starts and nobody
        has isolated why -- so the rungs must be comparable on hardware without
        the code being rewritten between them. A name that is not a known
        strategy is refused, and so is a known one that is not built.

        The offer is re-checked here against a fresh reading rather than the
        one the panel rendered. A player can start a game between seeing the
        button and pressing it, and that has to refuse.
        """
        if confirm is not True:
            return self._link_recovery_failure("link_recovery.confirmation_required")
        try:
            chosen = (
                self._link_recovery_service().default_strategy
                if strategy == ""
                else LinkRecoveryStrategy(strategy)
            )
        except ValueError:
            return self._link_recovery_failure("link_recovery.strategy_unknown")
        if not strategy_is_implemented(chosen):
            return self._link_recovery_failure(
                "link_recovery.strategy_not_implemented", strategy=chosen.value
            )
        try:
            observations = SnapshotTransitionObservationAdapter(self._discovery)
            current = await asyncio.to_thread(observations.observe)
            connection = await self._observe_connection_readiness(current)
        except Exception:
            return self._link_recovery_failure("link_recovery.observation_unavailable")
        observation = self._last_readiness_observation
        if observation is None:
            return self._link_recovery_failure("link_recovery.no_observation")
        service = self._link_recovery_service()
        assessment = service.assess(
            readiness_exhausted=(
                connection.stage is ConnectionReadinessStage.TIMED_OUT
            ),
            transport_present=observation.transport_present,
            pci_complete=observation.pci_complete,
            game_state=observation.game_state,
        )
        if not assessment.offered:
            return self._link_recovery_failure(
                assessment.code, strategy=chosen.value
            )
        resolution = await asyncio.to_thread(
            lambda: resolve_gamescope_user(GamescopeDiscovery().scan())
        )
        if not resolution.ok or resolution.context is None:
            return self._link_recovery_failure(
                "link_recovery.session_unavailable", strategy=chosen.value
            )
        self._append_journey_event(
            severity="info",
            code="link_recovery.started",
            component="connection",
            stage="link_recovery",
            details={"strategy": chosen.value},
        )
        outcome = await asyncio.to_thread(
            lambda: service.recover(resolution.context, strategy=chosen)
        )
        self._append_journey_event(
            severity="info" if outcome.ok else "warning",
            code=outcome.code,
            component="connection",
            stage="link_recovery",
            details={
                "seconds": outcome.seconds,
                "session_restored": outcome.session_restored,
                # Recorded with every number: a timing from one rung means
                # nothing next to a timing from another.
                "strategy": outcome.strategy,
            },
        )
        return {
            "schema_version": 1,
            "ok": outcome.ok,
            "code": outcome.code,
            "seconds": outcome.seconds,
            "session_restored": outcome.session_restored,
            "strategy": outcome.strategy,
        }

    @staticmethod
    def _link_recovery_failure(code: str, *, strategy: str = "") -> dict[str, object]:
        return {
            "schema_version": 1,
            "ok": False,
            "code": code,
            "seconds": None,
            "session_restored": True,
            "strategy": strategy,
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


    # -- live eGPU disconnect -------------------------------------------

    def _live_disconnect_runtime(self) -> LiveDisconnectRuntime | None:
        """Build the runtime for the eGPU and session user in front of us.

        Rebuilt when either changes, because a runtime is bound to one device
        and one session: a grant taken over a different user manager, or a
        plan composed for a different eGPU, must not be reused.
        """
        user = resolve_gamescope_user(GamescopeDiscovery().scan()).context
        if user is None:
            return None
        key = (EGPU_GPU_FUNCTION, user.uid)
        with self._live_disconnect_lock:
            if self._live_disconnect is None or self._live_disconnect_key != key:
                self._live_disconnect = build_live_disconnect_runtime(
                    gpu_bdf=EGPU_GPU_FUNCTION,
                    uid=user.uid,
                    username=user.username,
                )
                self._live_disconnect_key = key
            return self._live_disconnect

    async def get_egpu_disconnect_status(
        self, _request: object = None
    ) -> dict[str, object]:
        """Report what a live disconnect would do now. Changes nothing.

        Safe to poll. No filter is armed, no DRM master taken, and no display
        touched by asking.
        """
        try:
            runtime = await asyncio.to_thread(self._live_disconnect_runtime)
        except Exception:
            runtime = None
        if runtime is None:
            return {
                "schema_version": 1,
                "availability": DisconnectAvailability.UNAVAILABLE.value,
                "code": "live_disconnect.session_unavailable",
                "ready": False,
                "busy": False,
            }
        try:
            status = await asyncio.to_thread(runtime.status)
        except Exception:
            return {
                "schema_version": 1,
                "availability": DisconnectAvailability.UNAVAILABLE.value,
                "code": "live_disconnect.status_unavailable",
                "ready": False,
                "busy": False,
            }
        return disconnect_status_to_payload(status)

    async def execute_egpu_disconnect(
        self,
        release_display: bool = False,
        relaunch_app_id: str = "",
        relaunch_intent: str = "disconnect",
    ) -> dict[str, object]:
        """Remove the eGPU in software. NOT clearance to unplug anything.

        `release_display` is a separate approval from the disconnect itself:
        it turns the external output off for the duration, which is visible to
        whoever is watching it, so a caller has to ask for it explicitly.

        `relaunch_app_id` records a wish to reopen one game afterwards, and is
        written down here rather than remembered by the caller because the
        caller is about to be destroyed: freeing the device restarts the Steam
        session, which is exactly what happens when a game was running. The
        record is picked up by `take_pending_relaunch`, from whichever panel is
        alive to ask, and it is cleared if the removal leaves the device
        somewhere it has never been.

        `relaunch_intent` says what the player was doing, which decides how the
        wish ages: a disconnect that lived through a suspend has gone wrong and
        expires, while a sleep is meant to be reopened when they come back. An
        unrecognised value records nothing rather than guessing.
        """
        relaunch = RelaunchIntentStore(CATALOG_ROOT)
        parsed_intent = _parse_intent(relaunch_intent)
        if (
            relaunch_app_id
            and parsed_intent is not None
            and STEAM_APP_ID_RE.fullmatch(str(relaunch_app_id))
        ):
            clock = _relaunch_clock_for(parsed_intent)
            try:
                await asyncio.to_thread(
                    relaunch.record,
                    RelaunchIntent(
                        str(relaunch_app_id),
                        read_boot_hash(),
                        _relaunch_now(clock),
                        clock,
                    ),
                )
            except Exception:
                # A wish that could not be written costs a manual relaunch. It
                # is not a reason to refuse the disconnect the player asked for.
                pass
        try:
            runtime = await asyncio.to_thread(self._live_disconnect_runtime)
        except Exception:
            runtime = None
        if runtime is None:
            return {
                "schema_version": 1,
                "stage": "invalid",
                "code": "live_disconnect.session_unavailable",
                "ok": False,
            }
        try:
            result = await asyncio.to_thread(
                lambda: runtime.execute(release_display=bool(release_display))
            )
        except Exception:
            return {
                "schema_version": 1,
                "stage": "invalid",
                "code": "live_disconnect.attempt_failed",
                "ok": False,
            }
        if result.device_disturbed:
            # A half-detached eGPU needs a person, not a game launching into it.
            try:
                await asyncio.to_thread(relaunch.clear)
            except Exception:
                pass
        return disconnect_result_to_payload(result)

    async def take_pending_relaunch(
        self, _request: object = None
    ) -> dict[str, object]:
        """Claim the game a disconnect closed, if it may still be reopened.

        Consuming, and consuming on refusal too: an intent that could not be
        honoured now is not one to keep offering. Every guard lives in
        `decide_relaunch`, so a panel calling this cannot widen them.
        """
        store = RelaunchIntentStore(CATALOG_ROOT)
        try:
            intent = await asyncio.to_thread(store.take)
        except Exception:
            return {"steam_app_id": "", "code": "relaunch.record_unreadable"}
        try:
            boot_hash = await asyncio.to_thread(read_boot_hash)
        except Exception:
            boot_hash = ""
        decision = decide_relaunch(
            intent,
            boot_hash=boot_hash,
            # Read the same clock the record was written against; comparing a
            # suspend-excluding reading to a suspend-including one would give
            # an age that means nothing.
            now_boot_seconds=_relaunch_now(
                RelaunchClock.BOOTTIME if intent is None else intent.clock
            ),
        )
        return {
            "steam_app_id": decision.steam_app_id if decision.should_relaunch else "",
            "code": decision.code,
        }

    async def get_sleep_readiness(
        self, _request: object = None
    ) -> dict[str, object]:
        """Report what sleeping would take right now. Changes nothing.

        Sleep is blocked outright while the eGPU is attached, because the dock
        is known to wake this handheld immediately. So on this hardware
        "sleep with a game running on the eGPU" is not a thing that can happen:
        the honest offer is *disconnect, then sleep*, and this says whether
        that is what pressing sleep would mean and what it would cost.

        The close prompt is re-derived for the sleep intent rather than reusing
        the disconnect one, so a player who agreed that a game may be closed
        for a disconnect is still asked before it is closed for a sleep.
        """
        try:
            presence = await asyncio.to_thread(
                self._sleep_hardware.observe_presence
            )
        except Exception:
            presence = EgpuPresence.UNKNOWN
        if presence is EgpuPresence.ABSENT:
            # Nothing of ours is in the way. Steam sleeps as it always does.
            return {
                "schema_version": 1,
                "code": "sleep.available",
                "requires_disconnect": False,
                "game": None,
                "close_prompt": close_prompt_to_payload(
                    decide_game_close(InterruptIntent.SLEEP, None)
                ),
            }
        if presence is not EgpuPresence.PRESENT:
            # Presence could not be established, so neither can what sleeping
            # would take. Saying "just sleep" here would be a guess about the
            # one thing the guard exists to prevent.
            return {
                "schema_version": 1,
                "code": "sleep.readiness_unknown",
                "requires_disconnect": True,
                "game": None,
                "close_prompt": close_prompt_to_payload(
                    decide_game_close(
                        InterruptIntent.SLEEP, None, scan_complete=False
                    )
                ),
            }
        try:
            runtime = await asyncio.to_thread(self._live_disconnect_runtime)
            status = (
                None if runtime is None else await asyncio.to_thread(runtime.status)
            )
        except Exception:
            status = None
        if status is None:
            return {
                "schema_version": 1,
                "code": "sleep.readiness_unknown",
                "requires_disconnect": True,
                "game": None,
                "close_prompt": close_prompt_to_payload(
                    decide_game_close(
                        InterruptIntent.SLEEP, None, scan_complete=False
                    )
                ),
            }
        game = status.game
        preference = None
        if game is not None and game.identity_exact:
            try:
                preference = await asyncio.to_thread(
                    GameClosePreferenceStore(CATALOG_ROOT).load,
                    game.app_id,
                    InterruptIntent.SLEEP,
                )
            except Exception:
                preference = None
        prompt = decide_game_close(
            InterruptIntent.SLEEP,
            None if game is None else game.as_running_game(),
            preference,
            # A status that could answer at all looked; a status that could not
            # was handled above.
            scan_complete=True,
        )
        payload = disconnect_status_to_payload(status)
        return {
            "schema_version": 1,
            "code": "sleep.requires_disconnect",
            # The eGPU is attached, so sleeping means disconnecting first.
            "requires_disconnect": True,
            "game": payload["game"],
            "close_prompt": close_prompt_to_payload(prompt),
            # Passed through so a caller renders one set of facts rather than
            # asking twice and reconciling two readings taken moments apart.
            "disconnect": payload,
        }

    async def remember_game_close_choice(
        self,
        steam_app_id: str,
        intent: str = "disconnect",
        skip_confirmation: bool = False,
        relaunch_after: bool = False,
    ) -> dict[str, object]:
        """Store the player's answer for one game and one action.

        `intent` is part of the key, not a detail: agreeing that a game may be
        closed for sleep is not agreeing that it may be closed for a
        disconnect. An unrecognised value is refused rather than defaulted,
        because filing an answer against the wrong action files an answer the
        player did not give.

        Two things are checked here rather than trusted from the caller, both
        because a frontend can be stale and neither failure is visible to the
        player until it costs them a save:

        - the game must be the one actually running and named exactly, so an
          answer cannot be filed against a game the player was not looking at;
        - "do not ask again" is refused for a game the catalog has reviewed
          evidence loses progress on close, which is the same rule the consent
          decision applies when reading a stored answer back.

        Forgetting is not guarded the same way, because forgetting only ever
        results in the player being asked more often.
        """
        if not isinstance(steam_app_id, str) or not STEAM_APP_ID_RE.fullmatch(
            steam_app_id
        ):
            return {"ok": False, "code": "game_close.app_id_invalid"}
        parsed_intent = _parse_intent(intent)
        if parsed_intent is None:
            return {"ok": False, "code": "game_close.intent_invalid"}
        try:
            runtime = await asyncio.to_thread(self._live_disconnect_runtime)
        except Exception:
            runtime = None
        if runtime is None:
            return {"ok": False, "code": "live_disconnect.session_unavailable"}
        try:
            status = await asyncio.to_thread(runtime.status)
        except Exception:
            return {"ok": False, "code": "live_disconnect.status_unavailable"}
        prompt = status.close_prompt
        if prompt is None or prompt.game is None or not prompt.game.identity_exact:
            return {"ok": False, "code": "game_close.identity_unverified"}
        if prompt.game.steam_app_id != steam_app_id:
            return {"ok": False, "code": "game_close.preference_game_mismatch"}
        if skip_confirmation and not prompt.remember_offered:
            return {"ok": False, "code": "game_close.progress_at_risk"}
        preference = GameClosePreference(
            steam_app_id,
            parsed_intent,
            skip_confirmation=bool(skip_confirmation),
            relaunch_after=bool(relaunch_after),
        )
        try:
            await asyncio.to_thread(
                GameClosePreferenceStore(CATALOG_ROOT).remember, preference
            )
        except Exception:
            return {"ok": False, "code": "game_close.preference_write_failed"}
        return {
            "ok": True,
            "code": "game_close.preference_stored",
            "steam_app_id": steam_app_id,
            "intent": parsed_intent.value,
            "skip_confirmation": preference.skip_confirmation,
            "relaunch_after": preference.relaunch_after,
        }

    async def forget_game_close_choice(
        self, steam_app_id: str, intent: str = "disconnect"
    ) -> dict[str, object]:
        """Return one game to being asked about before one action."""
        if not isinstance(steam_app_id, str) or not STEAM_APP_ID_RE.fullmatch(
            steam_app_id
        ):
            return {"ok": False, "code": "game_close.app_id_invalid"}
        parsed_intent = _parse_intent(intent)
        if parsed_intent is None:
            return {"ok": False, "code": "game_close.intent_invalid"}
        try:
            await asyncio.to_thread(
                GameClosePreferenceStore(CATALOG_ROOT).forget,
                steam_app_id,
                parsed_intent,
            )
        except Exception:
            return {"ok": False, "code": "game_close.preference_write_failed"}
        return {"ok": True, "code": "game_close.preference_cleared"}

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
                lambda: self._presentation_transition_service().preview(
                    PlacementState.DOCKED_EGPU, user_confirmed=False
                ),
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
                lambda: self._presentation_transition_service().preview(
                    PlacementState.DOCKED_EGPU, user_confirmed=True
                ),
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
                lambda: self._presentation_transition_service().execute(approval_token)
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
        if succeeded and requested_target is PlacementState.DOCKED_EGPU:
            # A player's own TV switch is intent too, and earns a record on the
            # same evidence: the display the dock is observed presenting on.
            self._saved_tv_pending_dock = True
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
                lambda: self._presentation_transition_service().preview(
                    PlacementState.PORTABLE, user_confirmed=True
                ),
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

    async def approve_supervised_portable_vulkan_trial(self) -> dict[str, object]:
        """Developer-supervised one-shot session trial; never safe-unplug approval."""
        try:
            if not await asyncio.to_thread(self._steam_trial_integration().verify_effective):
                return {"schema_version": 1, "approval_token": "",
                        "blockers": ["portable_trial.steam_integration_required"], "safe_to_unplug": False}
            preview = await asyncio.to_thread(
                lambda: self._presentation_transition_service().preview(
                    PlacementState.PORTABLE, user_confirmed=True, portable_vulkan_trial=True,
                )
            )
            return {"schema_version": 1, "approval_token": preview.approval_token,
                    "blockers": list(preview.blockers), "safe_to_unplug": False}
        except Exception:
            return {"schema_version": 1, "approval_token": "",
                    "blockers": ["portable_trial.approval_failed"], "safe_to_unplug": False}

    async def approve_supervised_portable_graphics_trial(self) -> dict[str, object]:
        """Explicit OpenGL + Vulkan one-shot trial; never safe-unplug approval."""
        try:
            if not await asyncio.to_thread(self._steam_trial_integration().verify_effective):
                return {"schema_version": 1, "approval_token": "",
                        "blockers": ["portable_trial.steam_integration_required"], "safe_to_unplug": False}
            preview = await asyncio.to_thread(
                lambda: self._presentation_transition_service().preview(
                    PlacementState.PORTABLE, user_confirmed=True, portable_vulkan_trial=True,
                    portable_trial_schema_version=2,
                )
            )
            return {"schema_version": 1, "approval_token": preview.approval_token,
                    "blockers": list(preview.blockers), "safe_to_unplug": False}
        except Exception:
            return {"schema_version": 1, "approval_token": "",
                    "blockers": ["portable_trial.approval_failed"], "safe_to_unplug": False}

    async def approve_supervised_steam_trial_preparation(self) -> dict[str, object]:
        """Detached idle preparation only; no service restart or trial grant."""
        try:
            preview = await asyncio.to_thread(self._steam_trial_preparation_service().preview,
                                              user_confirmed=True)
            return {"schema_version": 1, "approval_token": preview.token,
                    "ready": preview.already_ready, "blockers": list(preview.blockers)}
        except Exception:
            return {"schema_version": 1, "approval_token": "", "ready": False,
                    "blockers": ["steam_trial.preparation_unavailable"]}

    async def prepare_supervised_steam_trial_integration(self, approval_token: str) -> dict[str, object]:
        """Prepare the fixed Steam shim under the existing single-use approval owner."""
        try:
            outcome = await asyncio.to_thread(self._steam_trial_preparation_service().execute,
                                              approval_token)
            return {"schema_version": 1, "prepared": outcome.prepared,
                    "changed": outcome.changed, "code": outcome.code,
                    "rollback_attempted": outcome.rollback_attempted,
                    "rollback_succeeded": outcome.rollback_succeeded}
        except Exception:
            return {"schema_version": 1, "prepared": False, "changed": False,
                    "code": "steam_trial.preparation_failed"}

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
                lambda: self._presentation_transition_service().status()
            )
        except Exception:
            prior_status = None
        try:
            acknowledged = await asyncio.to_thread(
                lambda: self._presentation_transition_service().acknowledge(acknowledgement_id),
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
                lambda: self._presentation_transition_service().status()
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
            "Re-Gear plugin started: version=%s revision=%s",
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
                "Re-Gear diagnostics ready: mode=%s game=%s support=%s blockers=%s",
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
            decky.logger.exception("Re-Gear initial read-only snapshot failed")
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
        while not self._unloading:
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
                        audio = await self._run_background_operation(
                            lambda: self._audio_handoff_service().switch(
                                PlacementState.PORTABLE, resolution.context
                            ),
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
        while not self._unloading:
            delay_seconds = self._automatic_dock_retry_seconds
            try:
                enabled = await asyncio.to_thread(
                    self._automatic_dock_preferences().load
                )
                current = await asyncio.to_thread(observations.observe)
                connection = await self._observe_connection_readiness(current)
                if connection.code != self._last_connection_readiness_code:
                    self._last_connection_readiness_code = connection.code
                    self._record_connection_wake("readiness_observation")
                    self._append_journey_event(
                        severity=(
                            "warning"
                            if connection.stage in {
                                ConnectionReadinessStage.ACTION_REQUIRED,
                                ConnectionReadinessStage.LINK_TRAINING_FAILED,
                                ConnectionReadinessStage.TIMED_OUT,
                            }
                            else "info"
                        ),
                        code=connection.code,
                        component="connection",
                        stage=connection.stage.value,
                        details={
                            "poll_after_ms": connection.poll_after_ms,
                            "window_age_ms": connection.window_age_ms,
            "checks": getattr(self, "_connection_checks", None),
            "checks_age_ms": max(0, int((time.monotonic() - getattr(self, "_connection_checks_at", 0.0)) * 1000)),
                        },
                    )
                completion = await asyncio.to_thread(
                    lambda: self._presentation_transition_service().reconcile_completion(current)
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
                            lambda: self._audio_handoff_service().remember_portable(resolution.context),
                        )
                # Before the opt-in gate: a TV the player switched to by hand
                # is intent too, and the record has to be re-armed when a dock
                # ends whether or not automatic docking is enabled.
                await self._update_saved_tv(current, connection)
                if not enabled:
                    delay_seconds = 5.0
                    await self._wait_for_topology(delay_seconds)
                    continue
                decision = self._automatic_dock.update(
                    enabled=enabled,
                    readiness=connection,
                    current=current,
                )
                delay_seconds = min(
                    delay_seconds, connection.poll_after_ms / 1_000
                )
                if (
                    self._topology_wakeup is not None
                    and self._topology_wakeup.available
                    and connection.stage
                    not in {
                        ConnectionReadinessStage.TRANSPORT_DETECTED,
                        ConnectionReadinessStage.WAITING_FOR_PCI,
                        ConnectionReadinessStage.WAITING_FOR_DRIVER,
                        ConnectionReadinessStage.WAITING_FOR_LINK,
                        ConnectionReadinessStage.WAITING_FOR_HDMI,
                        ConnectionReadinessStage.WAITING_FOR_AUDIO,
                        ConnectionReadinessStage.WAITING_FOR_SESSION,
                        ConnectionReadinessStage.STABILIZING,
                    }
                ):
                    delay_seconds = 5.0
                if decision.status.stage is AutomaticDockStage.DOCKED:
                    delay_seconds = 15.0
                elif connection.stage is ConnectionReadinessStage.GAME_RUNNING:
                    delay_seconds = 5.0
                if decision.should_switch:
                    self._record_connection_wake("automatic_transition_observation")
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
                        result = await self._run_background_operation(
                            lambda: self._presentation_transition_service().execute_automatic(
                                PlacementState.DOCKED_EGPU,
                                expected_generation=decision.expected_generation,
                                standing_consent=enabled,
                            ),
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
                    if succeeded:
                        # Recorded on a later observation, once the dock is seen
                        # presenting on the display it actually reached.
                        self._saved_tv_pending_dock = True
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

    async def _observe_connection_readiness(self, current):
        """Collect each independent readiness fact without changing hardware."""
        topology = await asyncio.to_thread(self._connection_topology.observe)
        audio_ready = False
        session_ready = False
        if topology.g1_identity:
            resolution = await asyncio.to_thread(
                lambda: resolve_gamescope_user(GamescopeDiscovery().scan())
            )
            if resolution.ok and resolution.context is not None:
                audio = await asyncio.to_thread(
                    lambda: self._audio_readiness_service().observe_before_display(resolution.context)
                )
                audio_ready = audio.ready
                if audio.code != self._last_audio_readiness_code:
                    self._last_audio_readiness_code = audio.code
                    self._append_journey_event(
                        severity="info" if audio.ready else "warning",
                        code=audio.code, component="connection", stage="audio_preflight",
                    )
                session_ready = await asyncio.to_thread(
                    lambda: GamescopeIntegrationStore(
                        plugin_root=PLUGIN_ROOT, user=resolution.context
                    ).status().ready
                )
        observation = ConnectionReadinessObservation(
                sample_id=current.sample_id,
                transport_identity=topology.transport_identity,
                transport_present=topology.transport_present,
                transport_absent_verified=topology.transport_absent_verified,
                g1_identity=topology.g1_identity,
                pci_complete=topology.pci_complete,
                driver_ready=topology.driver_ready,
                link_up=bool(
                    topology.link_applicable
                    and _exact_g1_link_is_up(current.snapshot)
                ),
                hdmi_ready=topology.hdmi_ready,
                audio_ready=audio_ready,
                session_ready=bool(
                    session_ready
                    and current.snapshot.gamescope.running is True
                    and current.snapshot.gamescope.confidence is Confidence.VERIFIED
                ),
                game_state=current.snapshot.game_state,
            )
        self._connection_checks = {
            "gpu": bool(observation.g1_identity and observation.pci_complete and observation.driver_ready),
            "link": observation.link_up,
            "hdmi": observation.hdmi_ready,
            "audio": observation.audio_ready,
            "session": observation.session_ready,
            "idle": observation.game_state is GameState.IDLE,
        }
        self._connection_checks_at = time.monotonic()
        # Kept so the link-recovery RPCs can answer from the reading the loop
        # already took. Re-observing inside an RPC would probe hardware on a
        # pollable call and could disagree with what the panel is showing.
        self._last_readiness_observation = observation
        self._link_recovery_service().observe_transport(observation.transport_present)
        return self._connection_readiness.update(observation)

    def _record_connection_wake(self, stage: str) -> None:
        """Describe the latest scan wake, not proof of device-specific causality."""
        self._append_journey_event(
            severity="info", code="observation.wake." + self._connection_wake_source,
            component="connection", stage=stage, create_timeline=False,
        )

    async def _wait_for_topology(self, delay_seconds: float) -> None:
        """Events are invalidations only; the next iteration re-collects evidence."""
        monitor = self._topology_wakeup
        if monitor is None:
            await asyncio.sleep(delay_seconds)
            self._connection_wake_source = "poll_timer"
            return
        was_available = self._topology_wakeup_was_available or monitor.available
        await monitor.wait(delay_seconds)
        self._connection_wake_source = monitor.last_wake_source
        self._topology_wakeup_was_available = monitor.available
        if was_available and not monitor.available:
            self._append_journey_event(
                severity="warning", code="observation.poll_fallback",
                component="connection", stage="observer_degraded", create_timeline=False,
            )

    async def _start_docked_igpu_lifecycle(self) -> None:
        if self._unloading or self._docked_igpu_task is not None:
            return
        self._docked_igpu_task = asyncio.create_task(
            self._docked_igpu_supervisor_loop()
        )

    async def _docked_igpu_supervisor_loop(self) -> None:
        while not self._unloading:
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
                "Re-Gear sleep guard: presence=%s active=%s error=%s elapsed_ms=%s",
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
        while not self._unloading:
            try:
                await self._reconcile_sleep_guard()
            except Exception:
                decky.logger.exception("Re-Gear sleep guard reconciliation failed")
                self._events.append(
                    severity="error",
                    code="sleep_guard.reconcile_failed",
                    component="sleep_guard",
                    stage="reconcile",
                )
            await asyncio.sleep(1)

    def _retain_until_done(self, task: asyncio.Task, collection: set) -> None:
        collection.add(task)

        def completed(done):
            collection.discard(done)
            if not done.cancelled():
                done.exception()  # Consume late errors without exporting private text.

        task.add_done_callback(completed)

    async def _run_background_operation(self, operation, *args, **kwargs):
        """Retain ownership of an already-started mutation when its observer exits."""
        if self._unloading:
            raise asyncio.CancelledError
        task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
        self._retain_until_done(task, self._background_operations)
        # Cancellation of the observer cannot stop a running worker thread.
        # Let the existing transaction finish; never silently label it stopped.
        return await asyncio.shield(task)

    async def _unload(self) -> None:
        self._unloading = True
        self._tdp_closing.set()
        started_ns = self._journey_now_ns()
        self._record_shutdown_checkpoint("unload_started", started_ns)
        tdp_close_failed = False
        if self._tdp_runtime is not None:
            try:
                self._tdp_runtime.close()
            except Exception:
                tdp_close_failed = True
                self._record_shutdown_checkpoint("tdp_stop_failed", started_ns)
        try:
            self._events.append(
                severity="info", code="plugin.unloading",
                component="lifecycle", stage="shutdown",
            )
        except Exception:
            pass
        # Wake the listener and request cancellation of every producer before
        # waiting for any one of them. A cancelled read can still hold a lock
        # in a worker thread needed by that observer's finally/close path.
        incomplete = tdp_close_failed
        if self._topology_wakeup is not None:
            try:
                self._topology_wakeup.close()
            except Exception:
                incomplete = True
                self._record_shutdown_checkpoint("observer_stop_failed", started_ns)
            self._topology_wakeup = None
        tasks = {}
        for attribute in (
            "_automatic_dock_task", "_native_recovery_task",
            "_docked_igpu_task", "_sleep_guard_task",
        ):
            task = getattr(self, attribute)
            setattr(self, attribute, None)
            if task is None:
                continue
            owner = attribute.removeprefix("_").removesuffix("_task")
            self._record_shutdown_checkpoint(owner + "_stop_requested", started_ns)
            tasks[task] = owner
            self._retain_until_done(task, self._retiring_tasks)
            task.cancel()
        operations = set(self._background_operations)
        pending = set()
        if tasks or operations:
            _, pending = await asyncio.wait(
                set(tasks) | operations, timeout=UNLOAD_OBSERVER_TIMEOUT_SECONDS
            )
        for task, owner in tasks.items():
            if task in pending:
                incomplete = True
                self._record_shutdown_checkpoint(owner + "_stop_timed_out", started_ns)
            elif not task.cancelled() and task.exception() is not None:
                self._record_shutdown_checkpoint("observer_stop_failed", started_ns)
        if operations & pending:
            incomplete = True
            self._record_shutdown_checkpoint("background_operation_pending", started_ns)
        self._docked_igpu_scheduler = None
        if not incomplete:
            self._record_shutdown_checkpoint("observers_stopped", started_ns)
        self._record_shutdown_checkpoint("sleep_guard_release_started", started_ns)
        release = asyncio.create_task(asyncio.to_thread(self._sleep_guard.close))
        self._retain_until_done(release, self._retiring_tasks)
        _, pending_release = await asyncio.wait({release}, timeout=UNLOAD_GUARD_TIMEOUT_SECONDS)
        if pending_release:
            self._record_shutdown_checkpoint("sleep_guard_release_timed_out", started_ns)
            self._record_shutdown_checkpoint("unload_incomplete", started_ns)
            return
        try:
            status = release.result()
        except Exception:
            self._record_shutdown_checkpoint("sleep_guard_release_failed", started_ns)
            return
        if status.active or status.error:
            self._record_shutdown_checkpoint("sleep_guard_release_failed", started_ns)
            return
        self._record_shutdown_checkpoint("sleep_guard_released", started_ns)
        self._record_shutdown_checkpoint(
            "unload_incomplete" if incomplete else "unload_complete", started_ns
        )
        # Do not drain asyncio's shared executor here. Cancellation stops the
        # coroutine that requested work, but cannot cancel work already running
        # in a worker thread (including a durable presentation transaction).
        # Waiting without a deadline can hold
        # Decky's unload hook past its five-second deadline and cause a forced
        # stop. Decky owns backend-process retirement after this hook returns;
        # Re-Gear only owns and stops the tasks and resources it created.

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
            "regear": "0.3.79",
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

    def _steam_trial_integration(self):
        from regear.delivery.steam_trial_activation import SteamTrialIntegrationStore
        resolution = resolve_gamescope_user(GamescopeDiscovery().scan())
        if not resolution.ok or resolution.context is None:
            raise ValueError('Gamescope user unavailable')
        return SteamTrialIntegrationStore(plugin_root=PLUGIN_ROOT, user=resolution.context,
                                          commands=UserServiceCommandRunner())

    def _steam_trial_preparation_service(self):
        integration = self._steam_trial_integration()
        return PresentationActivationService(
            observations=SnapshotTransitionObservationAdapter(self._discovery),
            integration=integration, commands=UserServiceCommandRunner(),
            resolve_user=lambda: resolve_gamescope_user(GamescopeDiscovery().scan()),
            approvals=self._steam_trial_approvals,
            verify_prepared=integration.verify_effective,
        )

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
        from regear.delivery.portable_trial_store import PortableTrialStore
        from regear.delivery.portable_trial_launch import mesa_layer_available
        from regear.delivery.steam_trial_wait import wait_for_steam_trial
        steam_integration = self._steam_trial_integration()

        def active_operation():
            current = journal.load_current()
            if current is None or not current.entries:
                return ""
            if dict(current.entries[0].details).get('launch_policy') != 'portable_vulkan_trial':
                return ""
            return current.operation_id

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
            trial_store=PortableTrialStore(presentation_state_root),
            trial_steam_waiter=lambda operation: wait_for_steam_trial(
                PortableTrialStore(presentation_state_root), operation),
            trial_layer_ready=lambda: mesa_layer_available() and steam_integration.verify_effective(),
            active_operation=active_operation,
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
            portable_trial_runner=mechanism.run_portable_trial,
        )

    def _audio_handoff_service(self) -> G1AudioHandoff:
        return G1AudioHandoff(
            commands=PipeWireCommandRunner(),
            state=PortableAudioStateStore(RootOwnedRuntimeState().ensure()),
            resolve_g1_audio_bdf=self._verified_g1_audio_bdf,
            report_result=self._record_audio_handoff_result,
            readiness_attempts=40,
        )

    def _audio_readiness_service(self) -> G1AudioReadiness:
        return G1AudioReadiness(
            commands=PipeWireCommandRunner(),
            state=PortableAudioStateStore(RootOwnedRuntimeState().ensure()),
            resolve_g1_audio_bdf=self._verified_g1_audio_bdf,
        )

    def _record_audio_handoff_result(self, target, result) -> None:
        self._append_journey_event(
            severity="info" if result.succeeded else "warning",
            code=result.code,
            component="audio",
            stage="restore_portable" if target is PlacementState.PORTABLE else "select_tv",
            details={"target": target.value, "succeeded": result.succeeded},
        )

    def _link_recovery_service(self) -> LinkRecoveryService:
        """The one instance, built once. See the note in `__init__`.

        The PCI reading is taken live rather than from the loop's cache: this
        is the callable polled *while the recovery is running*, when the whole
        question is whether the slot has seen the card since the bounce.
        """
        if self._link_recovery is None:
            self._link_recovery = LinkRecoveryService(
                UserServiceCommandRunner(),
                lambda: bool(self._connection_topology.observe().pci_complete),
                now=time.monotonic,
                sleep=time.sleep,
            )
        return self._link_recovery

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

    def _saved_tv_search(self) -> SavedTvSearch:
        """One bounded search per plugin lifetime, over the root-owned record.

        Constructed lazily against the same state root the other stores use, so
        a host that cannot own that directory fails here rather than writing a
        display identity somewhere the player cannot see or clear it.
        """
        if self._saved_tv is None:
            self._saved_tv = SavedTvSearch(
                SavedTvStore(RootOwnedRuntimeState().ensure())
            )
        return self._saved_tv

    async def _update_saved_tv(self, current, connection) -> None:
        """Carry the saved TV through one dock: re-arm it, record it, wait for it.

        Reporting only. Nothing here authorizes a display change: when the saved
        TV does appear, HDMI readiness reaches the existing automatic dock the
        way it always has, and the one transition engine does the rest.
        """
        try:
            search = self._saved_tv_search()
        except Exception:
            # No root-owned state root means no search is running, and claiming
            # one is waiting would be inventing it.
            self._saved_tv_decision = None
            return
        if verified_egpu_absent(current.snapshot):
            # The dock ended. The budget bounds one search for the TV, not the
            # lifetime of the plugin, so the next dock asks again from zero --
            # including a fresh read of the record.
            if self._saved_tv_armed:
                search.rearm()
                self._saved_tv_armed = False
                self._saved_tv_pending_dock = False
                self._saved_tv_decision = None
                self._saved_tv_attempts = 0
            return
        self._saved_tv_armed = True
        if self._saved_tv_pending_dock:
            display = _docked_tv_display(current.snapshot)
            if display is not None:
                # An explicitly successful transition, now observed presenting
                # on that exact display. Only both facts together earn a record.
                try:
                    await asyncio.to_thread(
                        lambda: search.remember(
                            display=display, transition_succeeded=True
                        )
                    )
                except (ValueError, OSError):
                    # An identity the record refuses, or a write that failed.
                    # Remembering nothing is the safe outcome; retrying it on
                    # every observation would turn one refusal into a loop.
                    self._append_journey_event(
                        severity="warning",
                        code="saved_tv.record_unwritable",
                        component="connection",
                        stage="saved_tv",
                        create_timeline=False,
                    )
                self._saved_tv_pending_dock = False
                self._saved_tv_decision = None
                self._saved_tv_attempts = 0
                return
        if connection.stage not in {
            ConnectionReadinessStage.WAITING_FOR_HDMI,
            ConnectionReadinessStage.READY_DISPLAY_PENDING,
        }:
            # Only a stage that means "the eGPU is up and the TV is not there"
            # is a real look for a saved TV. Counting any other stage would
            # spend the budget on readings taken before it could have appeared.
            # READY_DISPLAY_PENDING is the same fact with the eGPU side already
            # settled, and it is the stage that case now reports, so omitting it
            # silently stopped the search running in its primary case.
            self._saved_tv_decision = None
            return
        decision = await asyncio.to_thread(
            lambda: search.observe(
                displays=current.snapshot.displays,
                scan_complete=_display_scan_complete(current.snapshot),
            )
        )
        self._saved_tv_decision = decision
        self._saved_tv_attempts = search.attempts
        if decision.code != self._last_saved_tv_code:
            self._last_saved_tv_code = decision.code
            self._append_journey_event(
                severity="info",
                code=decision.code,
                component="connection",
                stage="saved_tv",
                details={
                    "state": decision.state.value,
                    "attempts": search.attempts,
                },
                create_timeline=False,
            )

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
