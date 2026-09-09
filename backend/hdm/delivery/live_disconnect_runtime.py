"""Compose the live disconnect for the plugin backend, and serialize it.

`hdm.egpu_disconnect` composes the same pieces for an operator at a terminal.
This composes them for a caller that is not a person: it performs the approved
restarts itself through `SessionUnitRestart`, it runs one attempt at a time,
and it reports state a player-facing surface can render without inferring
anything.

What the caller is owed, and what it must not do for itself:

- **Whether the capability is available at all**, which is not the same as the
  eGPU being connected.
- **Whether a disconnect would proceed now**, and when it would not, a stable
  code naming the fact that blocks it. A caller must not infer permission from
  a connection, an empty holder list, or a display mode.
- **Whether a run is in flight.** Attempts are serialized here rather than in
  the caller, because two disconnects racing over one device is not a state
  any of the sequence's guards were written for.
- **Whether releasing the external display would be needed**, which is a
  separate approval from the disconnect: turning an output off is visible to
  whoever is in front of it.
- **Whether a previous attempt left the device needing recovery**, which
  outranks everything else because the device is then in a state it has never
  been in.

`status` observes and never mutates: no filter is armed, no master taken, no
display touched. It is safe to poll.

Nothing here decides whether a device is safe to unplug. This removes a device
in software while the cable stays attached, and safety invariant 10 is
untouched.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable

from ..adapters.steamos.cgroup_identity import observe_user_manager_cgroup
from ..adapters.steamos.device_filter import CgroupDeviceFilter
from ..adapters.steamos.device_removal import SysfsDeviceRemoval
from ..adapters.steamos.discovery import SteamOsDiscovery
from ..adapters.steamos.drm_crtc import DrmCrtcProbe
from ..adapters.steamos.drm_display_release import DrmDisplayRelease
from ..adapters.steamos.egpu_clients import EgpuClientDiscovery
from ..adapters.steamos.egpu_device_nodes import SteamOsEgpuDeviceNodeDiscovery
from ..adapters.game_session import (
    GameScopeSessionObservationAdapter,
    UserBoundGameScopeScanAdapter,
)
from ..adapters.steamos.commands import UserServiceCommandRunner
from ..adapters.steamos.game_scopes import SystemdGameScopeDiscovery
from ..domain.filter_arm_sequence import classify_holder_units
from ..domain.game_compatibility import EgpuHandoffStatus, GameSaveCapability
from ..domain.models import GameState
from ..adapters.steamos.egpu_holders import (
    egpu_functions,
    node_paths,
    scan_holders,
)
from ..adapters.steamos.owner_identity import observe_owner_identity, read_boot_hash
from ..adapters.steamos.peripherals import SteamOsPeripheralObservationAdapter
from ..adapters.steamos.session_restart import SessionUnitRestart
from ..application.filter_arm import FilterArmCoordinator, HolderObservation
from ..application.live_disconnect import (
    FreshRemovalObservation,
    LiveDisconnectResult,
    LiveDisconnectService,
    LiveDisconnectStage,
)
from ..application.safe_undock_evidence import build_safe_undock_evidence
from ..application.snapshot import SnapshotService
from ..domain.display_release import DisplayReleaseEvidence
from ..domain.egpu_device_policy import DevicePolicyState, compose_egpu_device_policy
from ..domain.device_removal import RemovalFunction, RemovalFunctionKind
from ..domain.filter_authorization import authorize_parent_scope
from ..domain.removal_safety import (
    RemovalSafety,
    RemovalSafetyState,
    assess_removal_safety,
)
from ..domain.removal_transaction import RecoveryState, reconcile
from ..ports.removal_transaction import RemovalTransactionStore
from .device_filter_program import compile_device_filter
from .compatibility_catalog_store import FileCompatibilityCatalogStore
from .removal_transaction_store import FileRemovalTransactionStore


def removal_functions(gpu_bdf: str, audio_bdf: str) -> tuple[RemovalFunction, ...]:
    """Name both functions a removal must detach.

    The planner orders them and refuses a plan covering only one, so the
    refusal keeps a single home; this only states which exist.
    """
    return (
        RemovalFunction(RemovalFunctionKind.GPU, gpu_bdf),
        RemovalFunction(RemovalFunctionKind.AUDIO, audio_bdf),
    )


#: Where the durable removal record lives. Root-owned, outside any user's home.
STORE_ROOT = Path("/var/lib/regear/egpu")
#: Where the reviewed compatibility catalog lives. The store appends its own
#: filename, so this is the directory rather than the file.
CATALOG_ROOT = Path("/var/lib/regear")
PCI_DEVICE_ROOT = Path("/sys/bus/pci/devices")
INTERNAL_CARD = "/dev/dri/card0"
EXTERNAL_CARD = "/dev/dri/card1"


class DisconnectAvailability(StrEnum):
    #: No eGPU to disconnect, or the observation could not establish one.
    UNAVAILABLE = "unavailable"
    #: A previous attempt left the device half attached. Nothing else may run.
    RECOVERY_REQUIRED = "recovery_required"
    #: An attempt is in flight.
    BUSY = "busy"
    #: Something names why a disconnect would not proceed, and the sequence
    #: cannot change it. A game running, an unapproved holder, evidence that
    #: never completed.
    BLOCKED = "blocked"
    #: Not ready yet, and the blocker is one the disconnect exists to clear.
    #: Worth attempting; not a promise that it will succeed.
    ATTEMPTABLE = "attemptable"
    #: Removal safety says ready as things stand.
    READY = "ready"


@dataclass(frozen=True, slots=True)
class GameContext:
    """The game currently rendering on the eGPU, and what is known about it.

    A disconnect cannot happen while a game is using the eGPU: the device it
    renders on is going away, and no live graphics context survives that. So
    the game has to end first, and a caller has to be able to say which game
    and what closing it will cost.

    `save_capability` is the fact that decides the tone of that sentence.
    `UNTESTED` is the common case and means Re-Gear does not know whether the
    game saves on exit -- which a caller must say plainly rather than round to
    reassurance.
    """

    app_id: str
    #: From the reviewed catalog when it holds this game, otherwise empty. A
    #: caller resolves a display name itself rather than being handed a guess.
    title: str
    save_capability: GameSaveCapability
    egpu_handoff: EgpuHandoffStatus

    @property
    def save_known(self) -> bool:
        """Whether the catalog says how this game handles being closed."""
        return self.save_capability is not GameSaveCapability.UNTESTED


@dataclass(frozen=True, slots=True)
class DisconnectStatus:
    """Everything a caller needs to render, and nothing it has to infer."""

    availability: DisconnectAvailability
    code: str
    holders: tuple[str, ...] = ()
    scan_complete: bool = False
    external_display_committed: bool | None = None
    #: Whether a disconnect would need to turn the external display off. A
    #: separate approval, because it is visible to whoever is watching it.
    display_release_required: bool = False
    #: The game holding the eGPU, when one is. None means no game is running,
    #: or that its identity could not be established -- which are different
    #: things, and the readiness code says which.
    game: GameContext | None = None
    last: LiveDisconnectResult | None = None

    @property
    def ready(self) -> bool:
        return self.availability is DisconnectAvailability.READY

    @property
    def attemptable(self) -> bool:
        """Whether a player may press the button.

        True for `ready` and for `attemptable`. The difference matters to what
        a caller *says*, not to whether it offers the action: one is "this will
        proceed", the other is "this will try, and here is what it will do".
        """
        return self.availability in (
            DisconnectAvailability.READY,
            DisconnectAvailability.ATTEMPTABLE,
        )

    @property
    def busy(self) -> bool:
        return self.availability is DisconnectAvailability.BUSY


@dataclass(frozen=True, slots=True)
class DisconnectObservation:
    """One reading, taken once and shared by everything that needs it.

    The removal verdict travels whole rather than as a bare state, because the
    grant that authorizes the filter has to be bound to the same observation
    that judged the device, and a caller holding only a verdict cannot do that.
    """

    removal: FreshRemovalObservation
    display: DisplayReleaseEvidence
    present: tuple[str, ...]
    game: GameContext | None = None

    @property
    def readiness(self) -> RemovalSafety:
        return self.removal.readiness

    @property
    def attachment_binding(self) -> str:
        return self.removal.attachment_binding


#: A refusal that is about this runtime rather than about the device.
BUSY_CODE = "live_disconnect.busy"
UNAVAILABLE_CODE = "live_disconnect.egpu_unavailable"


class LiveDisconnectRuntime:
    """One disconnect at a time, with a status a caller can render."""

    def __init__(
        self,
        *,
        service: LiveDisconnectService,
        store: RemovalTransactionStore,
        observe: Callable[[], DisconnectObservation],
        authorize: Callable[[DisconnectObservation], object],
        program: Callable[[], bytes],
        boot_hash: Callable[[], str],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._service = service
        self._store = store
        self._observe = observe
        self._authorize = authorize
        self._program = program
        self._boot_hash = boot_hash
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._busy = False
        self._last: LiveDisconnectResult | None = None

    # -- observation ------------------------------------------------------

    def status(self) -> DisconnectStatus:
        """Report what a disconnect would do now. Observes; changes nothing."""
        if self._busy:
            # Reported without taking the lock: a caller polling status must
            # not block behind the attempt it is polling about.
            return DisconnectStatus(
                DisconnectAvailability.BUSY, BUSY_CODE, last=self._last
            )
        try:
            observation = self._observe()
        except Exception:
            return DisconnectStatus(
                DisconnectAvailability.UNAVAILABLE, UNAVAILABLE_CODE, last=self._last
            )

        recovery = self._recovery_state(observation.present)
        if recovery is not None:
            return DisconnectStatus(
                DisconnectAvailability.RECOVERY_REQUIRED,
                recovery,
                holders=observation.display.client_holders,
                scan_complete=observation.display.client_scan_complete,
                last=self._last,
            )

        if not observation.attachment_binding:
            return DisconnectStatus(
                DisconnectAvailability.UNAVAILABLE,
                UNAVAILABLE_CODE,
                last=self._last,
            )

        committed = bool(observation.display.external_committed)
        ready = (
            observation.readiness.state
            is RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL
        )
        if ready:
            availability = DisconnectAvailability.READY
        elif _sequence_would_clear(observation.readiness, observation.display):
            availability = DisconnectAvailability.ATTEMPTABLE
        else:
            availability = DisconnectAvailability.BLOCKED

        return DisconnectStatus(
            availability,
            observation.readiness.code,
            holders=observation.display.client_holders,
            scan_complete=observation.display.client_scan_complete,
            external_display_committed=observation.display.external_complete
            and committed,
            display_release_required=committed,
            game=observation.game,
            last=self._last,
        )

    def _recovery_state(self, present: tuple[str, ...]) -> str | None:
        """The code for a prior transaction that still needs settling, if any."""
        try:
            record = self._store.load()
        except Exception:
            # An unreadable record may describe a half-detached device, and
            # saying nothing about it would be worse than saying this.
            return "live_disconnect.record_unreadable"
        if record is None:
            return None
        recovery = reconcile(record, present_addresses=present)
        if recovery.state is RecoveryState.NOT_STARTED:
            return None
        return recovery.code

    # -- the attempt ------------------------------------------------------

    def execute(self, *, release_display: bool) -> LiveDisconnectResult:
        """Run one disconnect, or refuse because another is already running.

        Refuses rather than queues. A caller that asked twice wants to know
        that the second ask did nothing, not to have it happen later against
        a device it has stopped looking at.
        """
        if not self._lock.acquire(blocking=False):
            return LiveDisconnectResult(LiveDisconnectStage.INVALID, BUSY_CODE)
        self._busy = True
        try:
            result = self._run(release_display=release_display)
        finally:
            self._busy = False
            self._lock.release()
        self._last = result
        return result

    def _run(self, *, release_display: bool) -> LiveDisconnectResult:
        try:
            observation = self._observe()
        except Exception:
            return LiveDisconnectResult(
                LiveDisconnectStage.INVALID, UNAVAILABLE_CODE
            )
        if not observation.attachment_binding:
            return LiveDisconnectResult(
                LiveDisconnectStage.INVALID, UNAVAILABLE_CODE
            )
        authorization = self._authorize(observation)
        if authorization is None:
            return LiveDisconnectResult(
                LiveDisconnectStage.INVALID, "live_disconnect.not_authorized"
            )
        try:
            program = self._program()
            boot_hash = self._boot_hash()
        except Exception:
            return LiveDisconnectResult(
                LiveDisconnectStage.INVALID, "live_disconnect.filter_unavailable"
            )
        return self._service.disconnect(
            authorization,
            program,
            boot_hash=boot_hash,
            release_display=release_display,
        )


def _sequence_would_clear(
    readiness: RemovalSafety, display: DisplayReleaseEvidence
) -> bool:
    """Whether the reported blocker is one the disconnect exists to clear.

    Removal safety is assessed before any release, and before one it always
    declines: the holders are still there and the eGPU is still driving a
    display. `hdm.domain.disconnect_sequence` says why -- the verdict is being
    asked too early, and releasing is what changes the facts it reads. A status
    that repeated the verdict verbatim would tell a player their eGPU can never
    be disconnected, which is exactly the reading that module exists to prevent.

    Two blockers qualify, and only two.

    A **standing external display**: the disconnect turns it off itself, given
    approval. This one is safe to trust because it is the last fact removal
    safety checks, so nothing is hidden behind it.

    **Holders that are all approved for restart**, over a scan that finished.
    The restart plan is what clears them. This is deliberately narrower than it
    looks: an unapproved holder disqualifies the whole set, because the plan
    refuses rather than restarting something it was never allowed to touch, and
    an unfinished scan disqualifies it because an empty or partial holder list
    is not evidence about anything.

    `attemptable` is not a promise. Facts after `clients_clear` -- portable
    display and render -- are not evaluated once it fails, so an attempt can
    still refuse on one of them after the holders let go. That is a refusal
    with a clear reason and nothing removed, which is the right outcome; it is
    not a claim this function got wrong.
    """
    if readiness.code == "removal_safety.external_display_still_active":
        return True
    if readiness.code == "removal_safety.clients_active_or_protected":
        if not display.client_scan_complete or not display.client_holders:
            return False
        return not classify_holder_units(display.client_holders).unapproved
    return False


def disconnect_snapshot_service() -> SnapshotService:
    """The observation path, with this process excluded from the client scan.

    The disconnect holds the eGPU's card node open while it keeps DRM master
    to turn the external display off, so a scan taken inside that window sees
    this process holding the device and reports `clients_active_or_protected`
    -- the disconnect blocking itself. Observed on hardware: the client
    appeared only once the release was held, and only this process could have
    opened the node, because the filter was armed and enforced on the session's
    cgroup at the time and this tool runs outside it.

    Excluding only this pid is the narrow claim: this process will not be
    surprised by the device going away, because it is the thing removing it.
    Every other holder is still reported, and the exclusion is passed here at
    the composition root rather than defaulted anywhere.
    """
    return SnapshotService(
        SteamOsDiscovery(egpu_clients=EgpuClientDiscovery(exclude_pids=(os.getpid(),))),
        peripheral_observation=SteamOsPeripheralObservationAdapter(),
    )


def observe_removal(service: SnapshotService) -> FreshRemovalObservation:
    """Classify one fresh observation, carrying the identity it was taken over.

    The identity travels with the verdict because the transaction refuses a
    release and an assessment that describe different devices.
    """
    composed = build_safe_undock_evidence(service.observe())
    evidence = composed.evidence
    if evidence is None:
        return FreshRemovalObservation(
            RemovalSafety(RemovalSafetyState.EVIDENCE_INSUFFICIENT, composed.code),
            "",
            "",
            "",
        )
    return FreshRemovalObservation(
        assess_removal_safety(
            evidence,
            expected_attachment_binding=evidence.attachment_binding,
            expected_generation=evidence.generation,
            expected_sample_id=evidence.sample_id,
        ),
        evidence.attachment_binding,
        evidence.generation,
        evidence.sample_id,
    )


def observe_display(
    nodes: tuple[str, ...],
    *,
    nodes_incomplete: bool,
    external: str = EXTERNAL_CARD,
    internal: str = INTERNAL_CARD,
) -> DisplayReleaseEvidence:
    """Read both displays and who holds the eGPU, as one reading.

    The holder list covers every eGPU node rather than the card alone. That is
    stricter than the decision needs -- a render-node holder cannot be
    presenting to a display -- and being stricter about turning someone's
    display off is the right direction to err in.
    """
    probe = DrmCrtcProbe()
    outside = probe.observe(external)
    inside = probe.observe(internal)
    scan = scan_holders(nodes, nodes_incomplete=nodes_incomplete)
    return DisplayReleaseEvidence(
        external_committed=tuple(record.crtc_id for record in outside.committed),
        external_complete=outside.complete,
        internal_committed=inside.mode_committed,
        client_holders=scan.units,
        client_scan_complete=scan.complete,
    )


def present_addresses(gpu_bdf: str, audio_bdf: str) -> tuple[str, ...]:
    """Which of the eGPU's functions the bus currently enumerates."""
    return tuple(
        address
        for address in (audio_bdf, gpu_bdf)
        if (PCI_DEVICE_ROOT / address).is_dir()
    )


def disconnect_status_to_payload(status) -> dict[str, object]:
    """Project the runtime's status onto what a caller renders.

    Every fact travels separately. A caller must not infer permission from a
    connection, an empty holder list, or a display mode, so `holders` and
    `scan_complete` are both reported and neither is summarised into the
    other.
    """
    last = status.last
    return {
        "schema_version": 1,
        "availability": status.availability.value,
        "code": status.code,
        "ready": status.ready,
        # Whether the button may be pressed. True for ready and for
        # attemptable; the difference changes what a caller says, not
        # whether it offers the action.
        "attemptable": status.attemptable,
        "busy": status.busy,
        "holders": list(status.holders),
        "scan_complete": status.scan_complete,
        "external_display_committed": status.external_display_committed,
        "display_release_required": status.display_release_required,
        # The game holding the eGPU, when one is. Null means no game is
        # running or its identity could not be established; the code says
        # which, and a caller must not read null as "safe to close nothing".
        "game": (
            None
            if status.game is None
            else {
                "app_id": status.game.app_id,
                "title": status.game.title,
                "save_capability": status.game.save_capability.value,
                "egpu_handoff": status.game.egpu_handoff.value,
                "save_known": status.game.save_known,
            }
        ),
        "last": disconnect_result_to_payload(last) if last is not None else None,
    }


def disconnect_result_to_payload(result) -> dict[str, object]:
    """Project one attempt's outcome, including what it left behind."""
    return {
        "schema_version": 1,
        "stage": result.stage.value,
        "code": result.code,
        "ok": result.ok,
        "released": result.released,
        "session_disturbed": result.session_disturbed,
        "removed": list(result.removed),
        "restored": list(result.restored),
        "display_released": list(result.display_released),
        "display_release_code": result.display_release_code,
        "filter_disarmed": result.filter_disarmed,
        # A device left somewhere it has never been. A caller showing this is
        # reporting a system that needs attention, not a failed action.
        "device_disturbed": result.device_disturbed,
    }


def build_live_disconnect_runtime(
    *,
    gpu_bdf: str,
    uid: int,
    username: str,
    store_root: Path = STORE_ROOT,
    restart_timeout_seconds: float = 90.0,
    grant_seconds: float = 600.0,
) -> LiveDisconnectRuntime:
    """Compose the disconnect from the real adapters, for the plugin backend.

    The same pieces `hdm.egpu_disconnect` composes for an operator, with one
    difference that matters: `restart` is `SessionUnitRestart`, which performs
    the approved restarts itself and verifies them, rather than printing a
    command and waiting for a person.

    Building this opens nothing and arms nothing. Every reading happens when
    the runtime is asked for one, so a runtime built while the eGPU is absent
    starts working when it appears rather than having to be rebuilt.
    """
    gpu, audio = egpu_functions(gpu_bdf)
    nodes, nodes_complete = node_paths(gpu, audio)
    device_filter = CgroupDeviceFilter()

    def holder_units() -> tuple[str, ...]:
        return scan_holders(nodes, nodes_incomplete=not nodes_complete).units

    def holder_observation() -> HolderObservation:
        # Completeness is carried across rather than dropped: an empty result
        # from a scan that could not finish is not a clear device.
        scan = scan_holders(nodes, nodes_incomplete=not nodes_complete)
        return HolderObservation(scan.units, scan.complete)

    def program() -> bytes:
        scan = SteamOsEgpuDeviceNodeDiscovery().scan(gpu_bdf=gpu, audio_bdf=audio)
        if not scan.complete:
            raise RuntimeError(scan.error or "device node discovery is incomplete")
        policy = compose_egpu_device_policy(scan.nodes)
        if policy.state is not DevicePolicyState.COMPOSED:
            raise RuntimeError(policy.code)
        return compile_device_filter(policy.devices)

    def observe_game() -> GameContext | None:
        """Identify the game holding the eGPU, and what the catalog knows.

        Every failure is None rather than a guess. A caller reading None asks
        the readiness code what is actually going on; it must never read it as
        "no game is running", because an unidentifiable game is still a game
        whose progress a close would put at risk.
        """
        try:
            observation = GameScopeSessionObservationAdapter(
                UserBoundGameScopeScanAdapter(SystemdGameScopeDiscovery(), uid)
            ).observe()
        except Exception:
            return None
        if observation.state is not GameState.RUNNING or observation.identity is None:
            return None
        app_id = observation.identity.steam_app_id
        try:
            records = FileCompatibilityCatalogStore(CATALOG_ROOT).load_games()
        except Exception:
            records = ()
        for record in records:
            if record.steam_app_id == app_id:
                return GameContext(
                    app_id, record.title, record.save_sleep, record.egpu_handoff
                )
        # Known to be running, absent from the catalog. Untested is the honest
        # answer and is what makes a caller say so.
        return GameContext(
            app_id, "", GameSaveCapability.UNTESTED, EgpuHandoffStatus.UNTESTED
        )

    def observe() -> DisconnectObservation:
        return DisconnectObservation(
            observe_removal(disconnect_snapshot_service()),
            observe_display(nodes, nodes_incomplete=not nodes_complete),
            present_addresses(gpu, audio),
            observe_game(),
        )

    def authorize(observation: DisconnectObservation):
        """Bind a grant to this scope, this owner, this boot and this reading.

        Returns None when any of them cannot be established, which the runtime
        reports as a refusal: a grant that cannot be bound is not a grant.
        """
        cgroup = observe_user_manager_cgroup(uid)
        owner = observe_owner_identity()
        boot_hash = read_boot_hash()
        if cgroup is None or owner is None or not boot_hash:
            return None
        authorization = authorize_parent_scope(
            cgroup=cgroup,
            uid=uid,
            session_uid=uid,
            owner=owner,
            boot_hash=boot_hash,
            attachment_binding=observation.removal.attachment_binding,
            generation=observation.removal.generation,
            sample_id=observation.removal.sample_id,
            deadline=time.monotonic() + grant_seconds,
        )
        return authorization if authorization.granted else None

    store = FileRemovalTransactionStore(store_root)
    service = LiveDisconnectService(
        coordinator=FilterArmCoordinator(
            device_filter=device_filter,
            restart=SessionUnitRestart(
                commands=UserServiceCommandRunner(),
                uid=uid,
                username=username,
                observe_holders=holder_units,
                now=time.monotonic,
                sleep=time.sleep,
                timeout_seconds=restart_timeout_seconds,
            ).restart,
            observe_holders=holder_observation,
            observe_cgroup=lambda: observe_user_manager_cgroup(uid),
            monotonic=time.monotonic,
        ),
        device_filter=device_filter,
        removal=SysfsDeviceRemoval(),
        display_release=DrmDisplayRelease(),
        store=store,
        observe=lambda: observe_removal(disconnect_snapshot_service()),
        observe_display=lambda: observe_display(
            nodes, nodes_incomplete=not nodes_complete
        ),
        display_node=EXTERNAL_CARD,
        present_addresses=lambda: present_addresses(gpu, audio),
        removal_functions=lambda: removal_functions(gpu, audio),
        now_ns=time.time_ns,
        owner_id="regear",
        device_set=gpu,
    )
    return LiveDisconnectRuntime(
        service=service,
        store=store,
        observe=observe,
        authorize=authorize,
        program=program,
        boot_hash=read_boot_hash,
    )
