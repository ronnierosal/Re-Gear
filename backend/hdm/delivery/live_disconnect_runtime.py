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
from ..adapters.steamos.commands import UserServiceCommandRunner
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
    #: Present, and something names why a disconnect would not proceed.
    BLOCKED = "blocked"
    #: A disconnect would proceed if asked.
    READY = "ready"


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
    last: LiveDisconnectResult | None = None

    @property
    def ready(self) -> bool:
        return self.availability is DisconnectAvailability.READY

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
        # A standing external display is the one blocker a disconnect can clear
        # by itself, so it does not make the capability unavailable -- it makes
        # the display approval required.
        if not ready and committed and _blocked_only_by_display(observation.readiness):
            ready = True

        return DisconnectStatus(
            DisconnectAvailability.READY if ready else DisconnectAvailability.BLOCKED,
            observation.readiness.code,
            holders=observation.display.client_holders,
            scan_complete=observation.display.client_scan_complete,
            external_display_committed=observation.display.external_complete
            and committed,
            display_release_required=committed,
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


def _blocked_only_by_display(readiness: RemovalSafety) -> bool:
    """Whether the external display is the single fact holding removal back.

    The disconnect can clear that one itself, so a caller is told it is ready
    and asked for the display approval, rather than told it is blocked by
    something it cannot act on.
    """
    return readiness.code == "removal_safety.external_display_still_active"


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

    def observe() -> DisconnectObservation:
        return DisconnectObservation(
            observe_removal(disconnect_snapshot_service()),
            observe_display(nodes, nodes_incomplete=not nodes_complete),
            present_addresses(gpu, audio),
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
