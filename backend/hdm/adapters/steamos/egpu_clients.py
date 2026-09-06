"""Read-only discovery of exact certified-eGPU resource holders."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ...domain.client_policy import classify_egpu_client
from ...domain.models import EgpuClientObservation, EgpuResourceKind
from .game_scopes import is_game_scope_path


DRM_NODE_PATTERN = re.compile(r"(?:card|renderD|controlD)[0-9]+")
SOUND_CARD_PATTERN = re.compile(r"card([0-9]+)")


@dataclass(frozen=True, slots=True)
class EgpuClientScan:
    applicable: bool
    complete: bool
    clients: tuple[EgpuClientObservation, ...] = field(default_factory=tuple)
    storage_devices: int = 0
    storage_in_use: bool = False
    error: str = ""


class EgpuClientDiscovery:
    """Inspect procfs descriptors and mappings without retaining raw paths."""

    def __init__(
        self,
        *,
        pci_root: Path = Path("/sys/bus/pci/devices"),
        proc_root: Path = Path("/proc"),
        dri_root: Path = Path("/dev/dri"),
        sound_root: Path = Path("/dev/snd"),
        block_root: Path = Path("/sys/class/block"),
        fd_target_reader: Callable[[Path], str] | None = None,
        uid_reader: Callable[[Path], int] | None = None,
        pci_path_resolver: Callable[[str], Path] | None = None,
        block_device_resolver: Callable[[Path], Path] | None = None,
        descriptor_reader: Callable[[Path], tuple[Path, ...]] | None = None,
    ) -> None:
        self._pci_root = pci_root
        self._proc_root = proc_root
        self._dri_root = dri_root
        self._sound_root = sound_root
        self._block_root = block_root
        self._fd_target_reader = fd_target_reader or (lambda path: os.readlink(path))
        self._uid_reader = uid_reader or (lambda path: path.stat().st_uid)
        self._pci_path_resolver = pci_path_resolver or (
            lambda bdf: self._pci_root / bdf
        )
        self._block_device_resolver = block_device_resolver or (
            lambda entry: entry.resolve(strict=True)
        )
        self._descriptor_reader = descriptor_reader or (
            lambda directory: tuple(directory.iterdir())
        )

    def scan(
        self,
        *,
        gpu_bdf: str,
        audio_bdf: str,
        root_bdf: str,
        xhci_bdf: str,
        egpu_stable_id: str,
        gamescope_pid: int | None,
        session_uid: int | None,
    ) -> EgpuClientScan:
        if not gpu_bdf or not egpu_stable_id:
            return EgpuClientScan(False, True)

        targets, target_error = self._resource_targets(gpu_bdf, audio_bdf)
        if target_error:
            return EgpuClientScan(True, False, error=target_error)

        clients, process_error = self._scan_processes(
            targets,
            egpu_stable_id=egpu_stable_id,
            gamescope_pid=gamescope_pid,
            session_uid=session_uid,
        )
        storage_devices, storage_in_use, storage_error = self._scan_storage(
            root_bdf, xhci_bdf
        )
        errors = tuple(error for error in (process_error, storage_error) if error)
        return EgpuClientScan(
            applicable=True,
            complete=not errors,
            clients=clients,
            storage_devices=storage_devices,
            storage_in_use=storage_in_use,
            error=" ".join(errors),
        )

    def _resource_targets(
        self, gpu_bdf: str, audio_bdf: str
    ) -> tuple[dict[str, EgpuResourceKind], str]:
        drm_directory = self._pci_path_resolver(gpu_bdf) / "drm"
        try:
            drm_names = tuple(
                entry.name
                for entry in drm_directory.iterdir()
                if DRM_NODE_PATTERN.fullmatch(entry.name)
            )
        except OSError:
            return {}, "Certified eGPU DRM resources could not be enumerated."
        card_nodes = [name for name in drm_names if name.startswith("card")]
        render_nodes = [name for name in drm_names if name.startswith("renderD")]
        if not card_nodes or not render_nodes:
            return {}, "Certified eGPU card and render nodes were not both proven."

        targets: dict[str, EgpuResourceKind] = {}
        for name in drm_names:
            kind = (
                EgpuResourceKind.DRM_CARD
                if name.startswith("card")
                else EgpuResourceKind.DRM_RENDER
                if name.startswith("renderD")
                else EgpuResourceKind.DRM_CONTROL
            )
            targets[self._normalize_target(str(self._dri_root / name))] = kind

        sound_directory = (
            self._pci_path_resolver(audio_bdf) / "sound" if audio_bdf else None
        )
        if sound_directory and sound_directory.is_dir():
            try:
                card_indexes = tuple(
                    match.group(1)
                    for entry in sound_directory.iterdir()
                    if (match := SOUND_CARD_PATTERN.fullmatch(entry.name))
                )
                sound_nodes = tuple(self._sound_root.iterdir())
            except OSError:
                return {}, "Certified eGPU audio resources could not be enumerated."
            for node in sound_nodes:
                if not any(self._sound_node_belongs_to(node.name, index) for index in card_indexes):
                    continue
                targets[self._normalize_target(str(node))] = self._sound_resource_kind(node.name)
        return targets, ""

    @staticmethod
    def _sound_node_belongs_to(name: str, card_index: str) -> bool:
        return bool(
            re.fullmatch(rf"(?:controlC{card_index}|hwC{card_index}D[0-9]+|pcmC{card_index}D[0-9]+[cp])", name)
        )

    @staticmethod
    def _sound_resource_kind(name: str) -> EgpuResourceKind:
        if name.startswith("pcm"):
            return EgpuResourceKind.AUDIO_PCM
        if name.startswith("control"):
            return EgpuResourceKind.AUDIO_CONTROL
        return EgpuResourceKind.AUDIO_HARDWARE

    def _scan_processes(
        self,
        targets: dict[str, EgpuResourceKind],
        *,
        egpu_stable_id: str,
        gamescope_pid: int | None,
        session_uid: int | None,
    ) -> tuple[tuple[EgpuClientObservation, ...], str]:
        try:
            process_paths = tuple(
                path for path in self._proc_root.iterdir() if path.name.isdigit()
            )
        except OSError:
            return (), "Process resources could not be enumerated."

        clients: list[EgpuClientObservation] = []
        incomplete = False
        for process_path in process_paths:
            try:
                descriptors = self._descriptor_reader(process_path / "fd")
            except OSError:
                if process_path.exists():
                    incomplete = True
                continue
            resources: set[EgpuResourceKind] = set()
            for descriptor in descriptors:
                try:
                    target = self._fd_target_reader(descriptor)
                except OSError:
                    continue
                kind = targets.get(self._normalize_target(target))
                if kind is not None:
                    resources.add(kind)
            # A mapping can outlive its descriptor. An empty fd directory is
            # therefore not evidence that this process released the device.
            try:
                with (process_path / "maps").open(encoding="utf-8", errors="strict") as source:
                    for index, line in enumerate(iter(lambda: source.readline(8193), "")):
                        if index >= 65536 or len(line) > 8192:
                            raise ValueError("Process mappings exceed inspection bounds")
                        fields = line.split(None, 5)
                        if len(fields) < 5:
                            raise ValueError("Malformed process mapping")
                        if len(fields) == 6:
                            target = fields[5].rstrip("\n").removesuffix(" (deleted)")
                            kind = targets.get(self._normalize_target(target))
                            if kind is not None:
                                resources.add(kind)
            except (OSError, UnicodeError, ValueError):
                if process_path.exists():
                    incomplete = True
            if not resources:
                continue
            try:
                pid = int(process_path.name)
                name = self._bounded_name((process_path / "comm").read_text(encoding="utf-8"))
                uid = self._uid_reader(process_path)
                start_time = self._start_time(
                    (process_path / "stat").read_text(encoding="utf-8")
                )
                cgroup = (process_path / "cgroup").read_text(encoding="utf-8")
            except (OSError, ValueError):
                if process_path.exists():
                    incomplete = True
                continue
            classification = classify_egpu_client(
                pid=pid,
                name=name,
                uid=uid,
                session_uid=session_uid,
                gamescope_pid=gamescope_pid,
                in_game_scope=is_game_scope_path(cgroup),
            )
            instance_material = f"{egpu_stable_id}:{pid}:{start_time}".encode()
            clients.append(
                EgpuClientObservation(
                    instance_id=hashlib.sha256(instance_material).hexdigest()[:16],
                    pid=pid,
                    name=name,
                    kind=classification.kind,
                    resources=tuple(sorted(resources, key=lambda item: item.value)),
                    close_eligible=classification.close_eligible,
                    reason=classification.reason,
                    process_start_time=start_time,
                )
            )
        clients.sort(key=lambda item: (item.kind.value, item.name.casefold(), item.pid))
        error = "Some process resources could not be inspected." if incomplete else ""
        return tuple(clients), error

    def _scan_storage(self, root_bdf: str, xhci_bdf: str) -> tuple[int, bool, str]:
        exact_bdfs = {value.casefold() for value in (root_bdf, xhci_bdf) if value}
        try:
            block_entries = tuple(self._block_root.iterdir())
        except OSError:
            return 0, True, "Storage topology could not be enumerated."

        relevant: dict[str, str] = {}
        incomplete = False
        for entry in block_entries:
            try:
                resolved = self._block_device_resolver(entry)
                components = {part.casefold() for part in resolved.parts}
                if not components.intersection(exact_bdfs):
                    continue
                major_minor = (entry / "dev").read_text(encoding="utf-8").strip()
                if not re.fullmatch(r"[0-9]+:[0-9]+", major_minor):
                    incomplete = True
                    continue
                relevant[entry.name] = major_minor
            except OSError:
                continue
        if not relevant:
            return 0, False, "Storage topology was incomplete." if incomplete else ""

        try:
            mountinfo = (self._proc_root / "self" / "mountinfo").read_text(encoding="utf-8")
            swaps = (self._proc_root / "swaps").read_text(encoding="utf-8")
        except OSError:
            return len(relevant), True, "External storage usage could not be verified."
        mounted = {
            fields[2]
            for line in mountinfo.splitlines()
            if len(fields := line.split()) >= 3
        }
        swap_names = {
            Path(line.split()[0]).name
            for line in swaps.splitlines()[1:]
            if line.split()
        }
        in_use = any(
            major_minor in mounted or name in swap_names
            for name, major_minor in relevant.items()
        )
        return len(relevant), in_use, ""

    @staticmethod
    def _bounded_name(value: str) -> str:
        sanitized = "".join(character for character in value.strip() if character.isprintable())
        return sanitized[:64] or "unknown"

    @staticmethod
    def _normalize_target(value: str) -> str:
        return "/".join(value.split("\\"))

    @staticmethod
    def _start_time(value: str) -> str:
        closing = value.rfind(")")
        if closing < 0:
            raise ValueError("Malformed process stat")
        fields = value[closing + 1 :].split()
        if len(fields) <= 19 or not fields[19].isdigit():
            raise ValueError("Process start time is unavailable")
        return fields[19]
