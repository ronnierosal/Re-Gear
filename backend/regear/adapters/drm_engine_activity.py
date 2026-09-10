"""Read-only DRM fdinfo counters for exact private game process instances."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

from ..domain.game_render_activity import (
    MAX_ENGINE_CLIENTS,
    DrmEngineClientCounters,
    DrmEngineCounterSample,
    DrmRenderBinding,
)
from ..domain.game_runtime import GameProcessInstance


MAX_PROCESS_DESCRIPTORS = 4096
MAX_STAT_BYTES = 8192
MAX_FDINFO_BYTES = 65536
COUNTER_RE = re.compile(r"^(?P<value>[0-9]+) ns$")


class ProcfsDrmEngineCounterAdapter:
    def __init__(
        self,
        *,
        proc_root: Path = Path("/proc"),
        descriptor_reader: Callable[[Path], tuple[Path, ...]] | None = None,
        fd_target_reader: Callable[[Path], str] = os.readlink,
    ) -> None:
        self._proc_root = proc_root
        self._descriptor_reader = descriptor_reader or (
            lambda directory: tuple(directory.iterdir())
        )
        self._fd_target_reader = fd_target_reader

    def sample(
        self,
        processes: tuple[GameProcessInstance, ...],
        binding: DrmRenderBinding,
    ) -> DrmEngineCounterSample:
        try:
            return self._sample(processes, binding)
        except _CounterEvidenceError as error:
            return DrmEngineCounterSample((), False, error.code)
        except Exception:
            return DrmEngineCounterSample(
                (), False, "render_activity.observation_failed"
            )

    def _sample(
        self,
        processes: tuple[GameProcessInstance, ...],
        binding: DrmRenderBinding,
    ) -> DrmEngineCounterSample:
        clients: dict[tuple[int, int, int], DrmEngineClientCounters] = {}
        for process in processes:
            directory = self._proc_root / str(process.pid)
            before = self._start_time(directory / "stat", process.pid)
            if before != process.start_time_ticks:
                raise _CounterEvidenceError(
                    "render_activity.process_identity_changed"
                )
            try:
                descriptors = self._descriptor_reader(directory / "fd")
            except OSError as error:
                raise _CounterEvidenceError(
                    "render_activity.descriptors_unavailable"
                ) from error
            if len(descriptors) > MAX_PROCESS_DESCRIPTORS:
                raise _CounterEvidenceError(
                    "render_activity.descriptor_limit"
                )
            for descriptor in descriptors:
                if not descriptor.name.isascii() or not descriptor.name.isdecimal():
                    continue
                try:
                    target = self._normalize_target(
                        self._fd_target_reader(descriptor)
                    )
                except OSError as error:
                    raise _CounterEvidenceError(
                        "render_activity.descriptor_changed"
                    ) from error
                if target != binding.render_node:
                    continue
                client = self._fdinfo(
                    directory / "fdinfo" / descriptor.name,
                    process,
                    binding,
                )
                existing = clients.get(client.identity)
                if existing is not None and existing != client:
                    raise _CounterEvidenceError(
                        "render_activity.client_identity_ambiguous"
                    )
                clients[client.identity] = client
                if len(clients) > MAX_ENGINE_CLIENTS:
                    raise _CounterEvidenceError("render_activity.client_limit")
            after = self._start_time(directory / "stat", process.pid)
            if after != before:
                raise _CounterEvidenceError(
                    "render_activity.process_identity_changed"
                )
        return DrmEngineCounterSample(
            tuple(sorted(clients.values(), key=lambda value: value.identity)),
            True,
        )

    def _fdinfo(
        self,
        path: Path,
        process: GameProcessInstance,
        binding: DrmRenderBinding,
    ) -> DrmEngineClientCounters:
        try:
            value = self._read_limited(path, MAX_FDINFO_BYTES)
        except (OSError, UnicodeError) as error:
            raise _CounterEvidenceError(
                "render_activity.fdinfo_unavailable"
            ) from error
        fields: dict[str, str] = {}
        engines: dict[str, int] = {}
        for line in value.splitlines():
            key, separator, raw = line.partition(":")
            if not separator:
                continue
            key = key.strip()
            raw = raw.strip()
            if key.startswith("drm-engine-"):
                name = key.removeprefix("drm-engine-")
                match = COUNTER_RE.fullmatch(raw)
                if match is None or name in engines:
                    raise _CounterEvidenceError(
                        "render_activity.engine_counter_invalid"
                    )
                engines[name] = int(match.group("value"))
            elif key in {"drm-driver", "drm-pdev", "drm-client-id"}:
                if key in fields:
                    raise _CounterEvidenceError(
                        "render_activity.fdinfo_ambiguous"
                    )
                fields[key] = raw
        if fields.get("drm-driver") != "amdgpu":
            raise _CounterEvidenceError("render_activity.driver_unverified")
        if fields.get("drm-pdev", "").casefold() != binding.pci_bdf:
            raise _CounterEvidenceError("render_activity.pci_identity_changed")
        client_id = fields.get("drm-client-id", "")
        if not client_id.isascii() or not client_id.isdecimal() or not engines:
            raise _CounterEvidenceError("render_activity.fdinfo_incomplete")
        try:
            return DrmEngineClientCounters(
                process.pid,
                process.start_time_ticks,
                int(client_id),
                tuple(sorted(engines.items())),
            )
        except ValueError as error:
            raise _CounterEvidenceError(
                "render_activity.fdinfo_invalid"
            ) from error

    def _start_time(self, path: Path, expected_pid: int) -> int:
        try:
            value = self._read_limited(path, MAX_STAT_BYTES)
        except (OSError, UnicodeError) as error:
            raise _CounterEvidenceError(
                "render_activity.process_unavailable"
            ) from error
        closing = value.rfind(")")
        opening = value.find("(")
        try:
            pid = int(value[:opening].strip())
            fields = value[closing + 1 :].strip().split()
            start_time = int(fields[19])
        except (IndexError, ValueError) as error:
            raise _CounterEvidenceError("render_activity.stat_invalid") from error
        if opening <= 0 or closing <= opening or pid != expected_pid or start_time <= 0:
            raise _CounterEvidenceError("render_activity.stat_invalid")
        return start_time

    @staticmethod
    def _read_limited(path: Path, limit: int) -> str:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise _CounterEvidenceError("render_activity.evidence_unbounded")
        return raw.decode("utf-8", errors="strict")

    @staticmethod
    def _normalize_target(value: str) -> str:
        return "/".join(value.split("\\"))


class _CounterEvidenceError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
