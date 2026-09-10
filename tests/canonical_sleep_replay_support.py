"""Deterministic, mechanism-free integration harness for canonical sleep tests."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from regear.application.canonical_sleep import CanonicalSleepWorkflowService
from regear.application.canonical_sleep_process_release import (
    CanonicalSleepProcessReleaseCoordinator,
)
from regear.application.guarded_game_close import (
    GameCloseApprovalStore,
    GuardedGameCloseService,
)
from regear.application.guarded_process_release import GuardedProcessReleaseService
from regear.application.process_release import (
    GracefulReleaseReceiptStore,
    ProcessReleaseApprovalStore,
)
from regear.application.process_release_replay import (
    ProcessReleaseJournalRecovery,
    ProcessReleaseRunner,
)
from regear.domain.control_plane import (
    CapabilitySupport,
    EgpuCapabilities,
    HostCapabilities,
    PlacementState,
    RemovalBehavior,
    RequestIntent,
    RequestSource,
    SleepBehavior,
    TransitionRequest,
    WorkflowState,
    compose_capabilities,
)
from regear.domain.event_policy import TopologyEvent, decide_topology_event
from regear.domain.game_compatibility import GameSaveCapability
from regear.domain.game_session import ActiveGameIdentity, GameSessionObservation
from regear.domain.models import (
    EgpuClientKind,
    EgpuClientObservation,
    EgpuPresence,
    EgpuResourceKind,
    GameState,
)
from regear.domain.process_release import ReleasePhase
from regear.domain.serialization import snapshot_from_dict
from regear.domain.sleep_workflow import SleepFlowEvent, SleepWorkflowContext
from regear.domain.transition_journal import JournalEventKind, TransitionJournal
from regear.ports.game_close import GameCloseMechanismResult
from regear.ports.process_signal import ProcessSignalResult
from regear.ports.sleep_workflow import SleepWorkflowObservation
from regear.ports.transition import VersionedObservation


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
OCCURRED_AT = "2026-08-31T12:00:00Z"
REQUEST_ID = "sleep-request-replay-0001"
OPERATION_ID = "sleep-operation-replay-0001"
EGPU_ID = "replay-egpu"
GAME_IDENTITY = ActiveGameIdentity(
    "1234", ("app-steam-app1234-replay.scope",)
)


class MemoryJournalStore:
    def __init__(self) -> None:
        self.current: TransitionJournal | None = None
        self.saved: list[TransitionJournal] = []
        self.fail_on_kind: JournalEventKind | None = None

    def load_current(self) -> TransitionJournal | None:
        return self.current

    def save(self, journal: TransitionJournal) -> None:
        if self.fail_on_kind is not None and journal.entries[-1].kind is self.fail_on_kind:
            raise OSError("injected journal persistence failure")
        if self.current is not None and self.current.operation_id != journal.operation_id:
            raise ValueError("operation identity changed")
        self.current = journal
        self.saved.append(journal)

    def clear_terminal(self, operation_id: str) -> None:
        if (
            self.current is None
            or not self.current.terminal
            or self.current.operation_id != operation_id
        ):
            raise ValueError("terminal operation mismatch")
        self.current = None


class FakeClock:
    def __init__(self) -> None:
        self.value = 0

    def now_ms(self) -> int:
        return self.value

    def advance(self, milliseconds: int) -> None:
        self.value += milliseconds


class MutableSleepObservations:
    def __init__(self, context: SleepWorkflowContext) -> None:
        self.context = context
        self.generation = "sleep-semantic-1"
        self.sample = 0
        self.available = True

    def observe(self) -> SleepWorkflowObservation:
        if not self.available:
            raise OSError("injected observation failure")
        self.sample += 1
        return SleepWorkflowObservation(
            self.generation,
            f"sleep-sample-{self.sample}",
            self.context,
            EGPU_ID if self.context.egpu_presence is EgpuPresence.PRESENT else "",
        )

class SequenceObservations:
    def __init__(self, values: list[object]) -> None:
        self.values = list(values)

    def observe(self):
        if not self.values:
            return None
        return self.values.pop(0)


class FakeWaiter:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.calls: list[int] = []

    def wait_ms(self, milliseconds: int) -> None:
        self.calls.append(milliseconds)
        self.clock.advance(milliseconds)


class FakeGameCloseMechanism:
    def __init__(self, store: MemoryJournalStore) -> None:
        self.store = store
        self.calls: list[ActiveGameIdentity] = []
        self.preceded_by_durable_substep = False

    def request_close(self, identity: ActiveGameIdentity) -> GameCloseMechanismResult:
        self.calls.append(identity)
        self.preceded_by_durable_substep = bool(
            self.store.current
            and self.store.current.entries[-1].kind is JournalEventKind.SUBSTEP_STARTED
        )
        return GameCloseMechanismResult(True, "game.close_requested")


class FakeSignals:
    def __init__(self) -> None:
        self.actions: list[tuple[str, object]] = []

    def capability_code(self) -> str:
        return ""

    def signal(self, target, action) -> ProcessSignalResult:
        self.actions.append((target.instance_id, action))
        return ProcessSignalResult(True, "signal.accepted")


def replay_fixture() -> dict[str, object]:
    return json.loads(
        (FIXTURES / "replay" / "canonical-sleep.json").read_text(encoding="utf-8")
    )


def _capabilities():
    return compose_capabilities(
        HostCapabilities(
            "replay-host",
            egpu_support=CapabilitySupport.VERIFIED,
            display_handoff=CapabilitySupport.VERIFIED,
            power_button_interception=CapabilitySupport.VERIFIED,
        ),
        EgpuCapabilities(
            "replay-egpu-profile",
            display_output=CapabilitySupport.VERIFIED,
            sleep_behavior=SleepBehavior.SLEEP_UNRELIABLE,
            removal_behavior=RemovalBehavior.LIVE_REMOVAL_VERIFIED,
        ),
    )


def _client() -> EgpuClientObservation:
    return EgpuClientObservation(
        instance_id="replay-client-instance",
        pid=100,
        name="replay-client",
        kind=EgpuClientKind.USER,
        resources=(EgpuResourceKind.DRM_RENDER,),
        close_eligible=True,
        reason="deterministic replay fixture",
        process_start_time="1000",
    )


def _snapshot(*, with_client: bool):
    raw = json.loads((FIXTURES / "tv-docked.json").read_text(encoding="utf-8"))
    snapshot = snapshot_from_dict(raw)
    clients = (_client(),) if with_client else ()
    return dataclasses.replace(
        snapshot,
        disconnect_readiness=dataclasses.replace(
            snapshot.disconnect_readiness,
            applicable=True,
            scan_complete=True,
            ready=not clients,
            egpu_stable_id=EGPU_ID,
            clients=clients,
            storage_devices=0,
            storage_in_use=False,
        ),
    )


def _context(*, game_state: GameState, with_client: bool) -> SleepWorkflowContext:
    snapshot = _snapshot(with_client=with_client)
    return SleepWorkflowContext(
        egpu_presence=EgpuPresence.PRESENT,
        exact_egpu_identity_verified=True,
        capabilities=_capabilities(),
        game_state=game_state,
        save_capability=GameSaveCapability.UNTESTED,
        disconnect_readiness=snapshot.disconnect_readiness,
        placement=PlacementState.DOCKED_EGPU,
        removal_readiness_verified=True,
    )


class CanonicalSleepReplayHarness:
    """Compose existing guarded services around one in-memory sleep journal."""

    def __init__(
        self,
        *,
        game_state: GameState = GameState.IDLE,
        with_client: bool = False,
        request_ttl_ms: int = 15 * 60 * 1000,
    ) -> None:
        self.store = MemoryJournalStore()
        self.clock = FakeClock()
        self.sleep_observations = MutableSleepObservations(
            _context(game_state=game_state, with_client=with_client)
        )
        self.sleep = self._new_sleep_service(request_ttl_ms=request_ttl_ms)
        self.signals = FakeSignals()

    def _new_sleep_service(
        self, *, request_ttl_ms: int = 15 * 60 * 1000
    ) -> CanonicalSleepWorkflowService:
        return CanonicalSleepWorkflowService(
            observations=self.sleep_observations,
            clock=self.clock,
            journal_store=self.store,
            occurred_at=lambda: OCCURRED_AT,
            operation_id_factory=lambda: OPERATION_ID,
            request_ttl_ms=request_ttl_ms,
        )

    def start(self):
        return self.sleep.start(
            TransitionRequest(
                REQUEST_ID,
                RequestIntent.SLEEP,
                RequestSource.STEAM_MENU,
                OCCURRED_AT,
                self.sleep_observations.generation,
            )
        )

    def advance(self, event: SleepFlowEvent):
        return self.sleep.advance(REQUEST_ID, event)

    def grant_game_consent(self):
        return self.advance(SleepFlowEvent.GAME_CONSENT_GRANTED)

    def guarded_game_close(self, *, outcome: str = "idle", stale: bool = False):
        running = GameSessionObservation(
            GameState.RUNNING, "game-semantic-1", "game-sample-1", GAME_IDENTITY
        )
        confirmation = dataclasses.replace(running, sample_id="game-sample-2")
        revalidation = dataclasses.replace(
            running,
            sample_id="game-sample-2" if stale else "game-sample-3",
        )
        values = [running, confirmation, revalidation]
        if outcome == "idle":
            values.append(
                GameSessionObservation(
                    GameState.IDLE, "game-semantic-idle", "game-sample-4"
                )
            )
            self.sleep_observations.context = dataclasses.replace(
                self.sleep_observations.context,
                game_state=GameState.IDLE,
            )
        elif outcome == "timeout":
            values.extend(
                dataclasses.replace(running, sample_id=f"game-sample-{index}")
                for index in range(4, 8)
            )
        else:
            raise ValueError("unsupported game-close replay outcome")
        observations = SequenceObservations(values)
        waiter = FakeWaiter(self.clock)
        mechanism = FakeGameCloseMechanism(self.store)
        service = GuardedGameCloseService(
            sleep=self.sleep,
            observations=observations,
            mechanism=mechanism,
            approvals=GameCloseApprovalStore(
                monotonic=lambda: self.clock.value / 1000,
                token_factory=lambda: "game-close-approval-replay-0001",
            ),
            journal_store=self.store,
            clock=self.clock,
            waiter=waiter,
            occurred_at=lambda: OCCURRED_AT,
            close_deadline_ms=300,
            poll_interval_ms=100,
        )
        service.preview(REQUEST_ID, user_confirmed=False)
        approved = service.preview(REQUEST_ID, user_confirmed=True)
        result = service.execute(REQUEST_ID, approved.approval_token)
        return result, mechanism, waiter

    def guarded_process_release(self, *, stale: bool = False):
        with_client = _snapshot(with_client=True)
        cleared = _snapshot(with_client=False)
        first = VersionedObservation("process-semantic-1", with_client, "process-sample-1")
        second = VersionedObservation(
            "process-semantic-1",
            with_client,
            "process-sample-1" if stale else "process-sample-2",
        )
        observations = SequenceObservations(
            [
                first,
                second,
                VersionedObservation(
                    "process-semantic-2", cleared, "process-sample-3"
                ),
            ]
        )
        runner = ProcessReleaseRunner(
            observations,
            self.signals,
            self.clock,
            journal_store=self.store,
            occurred_at=lambda: OCCURRED_AT,
        )
        approvals = ProcessReleaseApprovalStore(
            ttl_seconds=30,
            monotonic=lambda: self.clock.value / 1000,
            token_factory=lambda: "process-approval-replay-0001",
            operation_id_factory=lambda: "process-operation-replay-0001",
        )
        process = GuardedProcessReleaseService(
            observations=observations,
            approvals=approvals,
            receipts=GracefulReleaseReceiptStore(
                ttl_seconds=30,
                monotonic=lambda: self.clock.value / 1000,
                token_factory=lambda: "force-receipt-replay-0001",
            ),
            runner=runner,
            journal_store=self.store,
            recovery=ProcessReleaseJournalRecovery(
                self.store, occurred_at=lambda: OCCURRED_AT
            ),
        )
        coordinator = CanonicalSleepProcessReleaseCoordinator(self.sleep, process)
        approved = coordinator.preview(
            REQUEST_ID, ReleasePhase.GRACEFUL, user_confirmed=True
        )
        if not stale:
            self.sleep_observations.context = dataclasses.replace(
                self.sleep_observations.context,
                disconnect_readiness=cleared.disconnect_readiness,
            )
        result = coordinator.execute(REQUEST_ID, approved.details.token)
        return result

    def mark_egpu_removed(self, *, portable: bool) -> None:
        self.sleep_observations.context = dataclasses.replace(
            self.sleep_observations.context,
            egpu_presence=EgpuPresence.ABSENT,
            exact_egpu_identity_verified=True,
            placement=(
                PlacementState.PORTABLE if portable else PlacementState.DOCKED_EGPU
            ),
        )

    def topology(
        self,
        event: TopologyEvent,
        *,
        builtin_controller_available: bool | None = None,
    ):
        return decide_topology_event(
            event=event,
            placement=self.sleep_observations.context.placement,
            workflow=WorkflowState.SLEEP_PENDING_DISCONNECT,
            builtin_controller_available=builtin_controller_available,
        )

    def restart(self, *, observation_available: bool = True):
        self.sleep_observations.available = observation_available
        restarted = self._new_sleep_service()
        return restarted.recover_interrupted()
