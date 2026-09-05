"""Aggregate independent SteamOS observations into one HDM snapshot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from time import perf_counter_ns
from typing import TypeVar

from ...domain.models import (
    Blocker,
    Confidence,
    DisconnectReadinessObservation,
    DisplayKind,
    DisplayObservation,
    Evidence,
    EgpuLinkObservation,
    EgpuLinkState,
    GameState,
    GamescopeObservation,
    GpuObservation,
    GpuRole,
    ObservedSnapshot,
    SleepGuardObservation,
    SupportTier,
)
from ...profiles.ally_x import PROFILE_ID as ALLY_X_PROFILE_ID
from ...profiles.ally_x import match_ally_x, matches_ally_x
from ...profiles.gpd_g1 import GpdG1Match, match_gpd_g1
from ...ports.discovery import DiscoveryResult, DiscoveryTiming
from .drm import DrmCardRecord, DrmConnectorRecord, DrmDiscovery
from .egpu_clients import EgpuClientDiscovery, EgpuClientScan
from .game_scopes import GameScopeScan, SystemdGameScopeDiscovery
from .gamescope import GamescopeDiscovery, GamescopeScan
from .host import HostDiscovery, HostRecord
from .link_health import PcieLinkHealthDiscovery
from .pci import PciDeviceRecord, PciUsb4Discovery, Usb4DeviceRecord
from .sleep_inhibitor import InhibitorLeaseStatus


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


T = TypeVar("T")


def _card_stable_id(card: DrmCardRecord, g1: GpdG1Match, index: int) -> str:
    if g1.verified and card.pci_bdf == g1.gpu_bdf:
        return g1.stable_id
    if card.boot_vga is True:
        return "internal-gpu"
    identity = card.vendor_device or "unknown"
    return f"observed-gpu:{identity}:{index}"


def _gpu_role(card: DrmCardRecord, g1: GpdG1Match) -> GpuRole:
    if card.boot_vga is True:
        return GpuRole.INTERNAL
    if g1.verified and card.pci_bdf == g1.gpu_bdf:
        return GpuRole.EXTERNAL
    return GpuRole.UNKNOWN


def _display_stable_id(connector: DrmConnectorRecord) -> str:
    if connector.edid_sha256:
        return f"display:{connector.edid_sha256[:16]}"
    if connector.internal:
        return "internal-panel"
    return f"observed-display:{connector.card}:{connector.name}"


class SteamOsDiscovery:
    """Concrete read-only DiscoveryPort for the current SteamOS host."""

    def __init__(
        self,
        drm: DrmDiscovery | None = None,
        gamescope: GamescopeDiscovery | None = None,
        game_scopes: SystemdGameScopeDiscovery | None = None,
        pci_usb4: PciUsb4Discovery | None = None,
        host: HostDiscovery | None = None,
        egpu_clients: EgpuClientDiscovery | None = None,
        link_health: PcieLinkHealthDiscovery | None = None,
        sleep_guard_status: Callable[[], InhibitorLeaseStatus] | None = None,
        clock: Callable[[], datetime] = _default_clock,
        monotonic_ns: Callable[[], int] = perf_counter_ns,
    ) -> None:
        self._drm = drm or DrmDiscovery()
        self._gamescope = gamescope or GamescopeDiscovery()
        self._game_scopes = game_scopes or SystemdGameScopeDiscovery()
        self._pci_usb4 = pci_usb4 or PciUsb4Discovery()
        self._host = host or HostDiscovery()
        self._egpu_clients = egpu_clients or EgpuClientDiscovery()
        self._link_health = link_health or PcieLinkHealthDiscovery()
        self._sleep_guard_status = sleep_guard_status or (
            lambda: InhibitorLeaseStatus(
                False, "Sleep guard is available only through the Decky lifecycle."
            )
        )
        self._clock = clock
        self._monotonic_ns = monotonic_ns

    def collect_snapshot(self) -> ObservedSnapshot:
        return self.collect_snapshot_with_timings().snapshot

    def collect_snapshot_with_timings(self) -> DiscoveryResult:
        timings: list[DiscoveryTiming] = []
        total_started = self._monotonic_ns()

        def timed(stage: str, operation: Callable[[], T]) -> T:
            started = self._monotonic_ns()
            value = operation()
            duration_ms = (self._monotonic_ns() - started) / 1_000_000
            timings.append(DiscoveryTiming(stage, max(0.0, duration_ms)))
            return value

        cards = timed("drm", self._drm.scan)
        gamescope_scan = timed("gamescope", self._gamescope.scan)
        gamescope_uid = (
            gamescope_scan.process.uid if gamescope_scan.process is not None else None
        )
        game_scan = timed(
            "game_state", lambda: self._game_scopes.scan(user_uid=gamescope_uid)
        )
        pci_devices = timed("pci", self._pci_usb4.scan_pci)
        usb4_devices = timed("usb4", self._pci_usb4.scan_usb4)
        host = timed("host", self._host.scan)
        g1 = timed(
            "egpu_identity",
            lambda: match_gpd_g1(cards, pci_devices, usb4_devices),
        )
        egpu_link = timed(
            "egpu_link",
            lambda: self._link_health.observe(g1.root_bdf)
            if g1.verified
            else EgpuLinkObservation(
                g1.detected, EgpuLinkState.UNKNOWN, Confidence.UNKNOWN,
                error="egpu.link_identity_unverified" if g1.detected else "",
            ),
        )

        if g1.verified and game_scan.state is GameState.IDLE:
            client_scan = timed(
                "disconnect_clients",
                lambda: self._egpu_clients.scan(
                    gpu_bdf=g1.gpu_bdf,
                    audio_bdf=g1.audio_bdf,
                    root_bdf=g1.root_bdf,
                    xhci_bdf=g1.xhci_bdf,
                    egpu_stable_id=g1.stable_id,
                    gamescope_pid=(
                        gamescope_scan.process.pid
                        if gamescope_scan.process is not None
                        else None
                    ),
                    session_uid=gamescope_uid,
                ),
            )
        elif g1.verified:
            client_scan = timed(
                "disconnect_clients",
                lambda: EgpuClientScan(
                    applicable=True,
                    complete=False,
                    error=(
                        "eGPU client scan is deferred while a game is running."
                        if game_scan.state is GameState.RUNNING
                        else "eGPU client scan is deferred until game state is known."
                    ),
                ),
            )
        else:
            client_scan = timed(
                "disconnect_clients",
                lambda: EgpuClientScan(
                    applicable=g1.detected,
                    complete=not g1.detected,
                    error=g1.reason if g1.detected else "",
                ),
            )
        disconnect_readiness = self._disconnect_readiness(g1, client_scan)
        sleep_guard = self._build_sleep_guard(g1, self._sleep_guard_status())

        gpu_rows = self._build_gpus(cards, gamescope_scan, g1)
        display_rows = self._build_displays(cards, gamescope_scan)
        gamescope = self._build_gamescope(gamescope_scan, gpu_rows)
        blockers = self._blockers(
            host,
            cards,
            gamescope_scan,
            game_scan,
            g1,
            gpu_rows,
            display_rows,
            disconnect_readiness,
            sleep_guard,
        )
        host_profile = ALLY_X_PROFILE_ID if matches_ally_x(host) else "unknown"
        support_tier = self._support_tier(host_profile, cards, g1)
        observed_at = self._clock().astimezone(timezone.utc).isoformat()
        snapshot = ObservedSnapshot(
            schema_version=3,
            observed_at=observed_at,
            host_profile=host_profile,
            support_tier=support_tier,
            game_state=game_scan.state,
            gpus=gpu_rows,
            displays=display_rows,
            gamescope=gamescope,
            disconnect_readiness=disconnect_readiness,
            sleep_guard=sleep_guard,
            egpu_link=egpu_link,
            blockers=blockers,
        )
        timings.append(
            DiscoveryTiming(
                "snapshot_total",
                max(0.0, (self._monotonic_ns() - total_started) / 1_000_000),
            )
        )
        return DiscoveryResult(snapshot, tuple(timings))

    @staticmethod
    def _build_sleep_guard(
        g1: GpdG1Match, status: InhibitorLeaseStatus
    ) -> SleepGuardObservation:
        required = g1.detected
        confidence = (
            Confidence.VERIFIED
            if (g1.verified and status.active) or not required
            else Confidence.OBSERVED
        )
        return SleepGuardObservation(
            required=required,
            active=status.active,
            confidence=confidence,
            reason=(
                "Sleep is blocked because the attached eGPU is known to wake this handheld immediately."
                if required
                else ""
            ),
            error=status.error,
        )

    @staticmethod
    def _disconnect_readiness(
        g1: GpdG1Match, scan: EgpuClientScan
    ) -> DisconnectReadinessObservation:
        ready = (
            not scan.applicable
            or (scan.complete and not scan.clients and not scan.storage_in_use)
        )
        return DisconnectReadinessObservation(
            applicable=scan.applicable,
            scan_complete=scan.complete,
            ready=ready,
            egpu_stable_id=g1.stable_id if g1.verified else "",
            clients=scan.clients,
            storage_devices=scan.storage_devices,
            storage_in_use=scan.storage_in_use,
            error=scan.error,
        )

    @staticmethod
    def _support_tier(
        host_profile: str,
        cards: tuple[DrmCardRecord, ...],
        g1: GpdG1Match,
    ) -> SupportTier:
        if host_profile != ALLY_X_PROFILE_ID:
            return SupportTier.UNKNOWN
        non_boot_cards = [card for card in cards if card.boot_vga is not True]
        if not non_boot_cards:
            return SupportTier.CERTIFIED
        if g1.verified and len(non_boot_cards) == 1:
            return SupportTier.CERTIFIED
        return SupportTier.UNSUPPORTED

    @staticmethod
    def _build_gpus(
        cards: tuple[DrmCardRecord, ...],
        gamescope_scan: GamescopeScan,
        g1: GpdG1Match,
    ) -> tuple[GpuObservation, ...]:
        identities = [(_card_stable_id(card, g1, index), card) for index, card in enumerate(cards)]
        selected_id = ""
        process = gamescope_scan.process if gamescope_scan.ok else None
        selectors = {
            selector
            for selector in (
                process.prefer_vk_device if process else "",
                process.mesa_vk_device_select if process else "",
            )
            if selector
        }
        if process and process.environment_readable and len(selectors) == 1:
            selector = next(iter(selectors))
            matches = [
                stable_id
                for stable_id, card in identities
                if card.vendor_device == selector
            ]
            if len(matches) == 1:
                selected_id = matches[0]
        elif process and process.environment_readable and not selectors:
            internal = [stable_id for stable_id, card in identities if card.boot_vga is True]
            if len(internal) == 1:
                selected_id = internal[0]

        rows: list[GpuObservation] = []
        for stable_id, card in identities:
            role = _gpu_role(card, g1)
            confidence = (
                Confidence.VERIFIED
                if role is not GpuRole.UNKNOWN and bool(card.vendor) and bool(card.device)
                else Confidence.OBSERVED
            )
            rows.append(
                GpuObservation(
                    stable_id=stable_id,
                    role=role,
                    vendor_device=card.vendor_device,
                    present=True,
                    selected_for_render=(stable_id == selected_id) if selected_id else None,
                    model_name=card.model_name,
                    confidence=confidence,
                    evidence=(
                        Evidence("drm-sysfs", Confidence.OBSERVED, "GPU is present in DRM"),
                        Evidence(
                            "hardware-profile",
                            confidence,
                            "GPU role was classified without enumeration-order identity",
                        ),
                    ),
                )
            )
        return tuple(rows)

    @staticmethod
    def _build_displays(
        cards: tuple[DrmCardRecord, ...], gamescope_scan: GamescopeScan
    ) -> tuple[DisplayObservation, ...]:
        connectors = tuple(connector for card in cards for connector in card.connectors)
        active_connector: DrmConnectorRecord | None = None
        if gamescope_scan.ok and gamescope_scan.process:
            requested = tuple(
                name for name in gamescope_scan.process.output_order if name != "*"
            )
            matches = [
                connector
                for connector in connectors
                if connector.name in requested and connector.connected is True
            ]
            if len(matches) == 1:
                active_connector = matches[0]

        rows: list[DisplayObservation] = []
        for connector in connectors:
            status_known = connector.connected is not None
            active = (
                connector is active_connector
                if active_connector is not None
                else None
            )
            confidence = Confidence.VERIFIED if status_known else Confidence.UNKNOWN
            rows.append(
                DisplayObservation(
                    stable_id=_display_stable_id(connector),
                    kind=(
                        DisplayKind.INTERNAL if connector.internal else DisplayKind.EXTERNAL
                    ),
                    connector=connector.name,
                    connected=connector.connected,
                    active=active,
                    edid_ready=bool(connector.edid_sha256),
                    confidence=confidence,
                    evidence=(
                        Evidence("drm-sysfs", confidence, "Connector state was observed"),
                        Evidence(
                            "gamescope-process",
                            Confidence.VERIFIED if active is not None else Confidence.UNKNOWN,
                            "Active output is derived from the unique live output preference",
                        ),
                    ),
                )
            )
        return tuple(rows)

    @staticmethod
    def _build_gamescope(
        scan: GamescopeScan, gpus: tuple[GpuObservation, ...]
    ) -> GamescopeObservation:
        if not scan.ok or scan.process is None:
            running = True if scan.candidate_count > 0 else (
                False if scan.error == "Gamescope process was not found" else None
            )
            return GamescopeObservation(
                running=running,
                pid=None,
                confidence=Confidence.UNKNOWN,
                evidence=(Evidence("procfs", Confidence.UNKNOWN, scan.error),),
            )
        selected = [gpu for gpu in gpus if gpu.selected_for_render is True]
        render_id = selected[0].stable_id if len(selected) == 1 else ""
        render_vendor = selected[0].vendor_device if len(selected) == 1 else ""
        verified = (
            len(selected) == 1
            and selected[0].confidence is Confidence.VERIFIED
            and bool(scan.process.output_order)
            and scan.process.environment_readable
        )
        confidence = Confidence.VERIFIED if verified else Confidence.OBSERVED
        return GamescopeObservation(
            running=True,
            pid=scan.process.pid,
            output_order=scan.process.output_order,
            render_gpu_stable_id=render_id,
            render_vendor_device=render_vendor,
            confidence=confidence,
            evidence=(
                Evidence(
                    "procfs",
                    confidence,
                    "Unique Gamescope process and startup arguments were observed",
                ),
            ),
        )

    @staticmethod
    def _blockers(
        host: HostRecord,
        cards: tuple[DrmCardRecord, ...],
        gamescope: GamescopeScan,
        games: GameScopeScan,
        g1: GpdG1Match,
        gpus: tuple[GpuObservation, ...],
        displays: tuple[DisplayObservation, ...],
        disconnect: DisconnectReadinessObservation,
        sleep_guard: SleepGuardObservation,
    ) -> tuple[Blocker, ...]:
        blockers: list[Blocker] = []
        host_match = match_ally_x(host)
        if not host_match.exact:
            blockers.append(
                Blocker("host_profile_unknown", host_match.reason)
            )
        if not cards:
            blockers.append(
                Blocker("drm_inventory_unavailable", "No DRM GPU inventory was observed.")
            )
        if not gamescope.ok:
            blockers.append(Blocker("gamescope_unverified", gamescope.error))
        elif gamescope.process and not gamescope.process.environment_readable:
            blockers.append(
                Blocker(
                    "gamescope_environment_unreadable",
                    "Gamescope GPU-selector environment is not readable at this privilege level.",
                )
            )
        elif gamescope.process:
            selectors = {
                selector
                for selector in (
                    gamescope.process.prefer_vk_device,
                    gamescope.process.mesa_vk_device_select,
                )
                if selector
            }
            if len(selectors) > 1:
                blockers.append(
                    Blocker(
                        "render_selector_conflict",
                        "Gamescope argument and environment GPU selectors conflict.",
                    )
                )
        if games.state is GameState.UNKNOWN:
            blockers.append(Blocker("game_state_unknown", games.error))
        if g1.detected and not g1.verified:
            blockers.append(Blocker("egpu_identity_unverified", g1.reason))
        if disconnect.applicable and not disconnect.scan_complete:
            blockers.append(
                Blocker(
                    "egpu_client_scan_incomplete",
                    disconnect.error or "eGPU resource clients could not be verified.",
                )
            )
        if any(client.kind.value == "game" for client in disconnect.clients):
            blockers.append(
                Blocker(
                    "egpu_game_in_use",
                    "A running Steam game is using the eGPU.",
                )
            )
        non_game_clients = tuple(
            client for client in disconnect.clients if client.kind.value != "game"
        )
        if non_game_clients:
            blockers.append(
                Blocker(
                    "egpu_clients_active",
                    f"{len(non_game_clients)} process(es) are using eGPU resources.",
                )
            )
        if disconnect.storage_in_use:
            blockers.append(
                Blocker(
                    "egpu_storage_in_use",
                    "Storage attached through the eGPU is mounted or used as swap.",
                )
            )
        if sleep_guard.required and not sleep_guard.active:
            blockers.append(
                Blocker(
                    "sleep_guard_inactive",
                    sleep_guard.error
                    or "An eGPU is attached but the sleep inhibitor is not active.",
                )
            )
        if sleep_guard.active and not sleep_guard.required:
            blockers.append(
                Blocker(
                    "sleep_guard_release_pending",
                    "The sleep inhibitor is still active while eGPU absence is reconciled.",
                )
            )
        if len([gpu for gpu in gpus if gpu.selected_for_render is True]) != 1:
            blockers.append(Blocker("render_gpu_unknown", "Active render GPU is not verified."))
        if len([display for display in displays if display.active is True]) != 1:
            blockers.append(Blocker("active_display_unknown", "Active display is not verified."))
        return tuple(blockers)
