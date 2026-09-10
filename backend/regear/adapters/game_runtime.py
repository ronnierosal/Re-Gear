"""Read-only cgroup and procfs evidence for one exact Steam game session."""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable
from pathlib import Path

from ..domain.game_runtime import (
    MAX_GAME_PROCESSES,
    ActiveGameRuntimeObservation,
    GameProcessInstance,
    GameRuntimeKind,
)
from ..domain.game_session import ActiveGameIdentity


MAX_CGROUP_DIRECTORIES = 4096
MAX_STAT_BYTES = 8192
MAX_ENVIRON_BYTES = 65536
PROTON_ENV_KEYS = frozenset(
    {"STEAM_COMPAT_DATA_PATH", "WINEPREFIX", "PROTON_LOG_DIR"}
)
APP_ID_ENV_KEYS = frozenset({"SteamAppId", "SteamGameId"})


class CgroupProcGameRuntimeAdapter:
    """Collect exact private process instances without executing commands."""

    def __init__(
        self,
        *,
        cgroup_root: Path = Path("/sys/fs/cgroup"),
        proc_root: Path = Path("/proc"),
        readlink: Callable[[Path], str] = os.readlink,
    ) -> None:
        self._cgroup_root = cgroup_root
        self._proc_root = proc_root
        self._readlink = readlink
        self._counter = 0
        self._lock = threading.Lock()

    def observe(
        self, identity: ActiveGameIdentity, *, user_uid: int
    ) -> ActiveGameRuntimeObservation:
        if user_uid <= 0 or user_uid > 2_147_483_647:
            return self._unknown(identity, "game_runtime.user_invalid")
        try:
            pids = self._scope_pids(identity.scopes, user_uid)
        except _RuntimeEvidenceError as error:
            return self._unknown(identity, error.code)
        except Exception:
            return self._unknown(identity, "game_runtime.observation_failed")
        processes: list[GameProcessInstance] = []
        for pid in pids:
            try:
                processes.append(self._process(pid, identity.steam_app_id))
            except _RuntimeEvidenceError as error:
                return self._unknown(identity, error.code)
            except Exception:
                return self._unknown(identity, "game_runtime.observation_failed")
        processes.sort(key=lambda process: (process.pid, process.start_time_ticks))
        runtime_kind = (
            GameRuntimeKind.PROTON
            if any(process.proton_marker for process in processes)
            else GameRuntimeKind.NATIVE
        )
        return self._result(
            identity,
            tuple(processes),
            runtime_kind,
            complete=True,
            error_code="",
        )

    def _scope_pids(self, scopes: tuple[str, ...], user_uid: int) -> tuple[int, ...]:
        root = (
            self._cgroup_root
            / "user.slice"
            / f"user-{user_uid}.slice"
            / f"user@{user_uid}.service"
        )
        if not root.is_dir() or root.is_symlink():
            raise _RuntimeEvidenceError("game_runtime.cgroup_unavailable")
        wanted = set(scopes)
        found: dict[str, Path] = {}
        visited = 0

        def walk_error(_error: OSError) -> None:
            raise _RuntimeEvidenceError("game_runtime.cgroup_unavailable")

        try:
            for current, directories, _files in os.walk(
                root, topdown=True, onerror=walk_error, followlinks=False
            ):
                visited += 1
                if visited > MAX_CGROUP_DIRECTORIES:
                    raise _RuntimeEvidenceError("game_runtime.cgroup_scan_unbounded")
                for name in tuple(directories):
                    if name not in wanted:
                        continue
                    candidate = Path(current) / name
                    if candidate.is_symlink() or name in found:
                        raise _RuntimeEvidenceError(
                            "game_runtime.scope_identity_ambiguous"
                        )
                    found[name] = candidate
        except _RuntimeEvidenceError:
            raise
        except OSError as error:
            raise _RuntimeEvidenceError("game_runtime.cgroup_unavailable") from error
        if set(found) != wanted:
            raise _RuntimeEvidenceError("game_runtime.scope_missing")

        pids: set[int] = set()
        for scope in scopes:
            path = found[scope] / "cgroup.procs"
            try:
                lines = self._read_limited_text(path, MAX_STAT_BYTES).splitlines()
            except (OSError, UnicodeError) as error:
                raise _RuntimeEvidenceError(
                    "game_runtime.cgroup_unavailable"
                ) from error
            for line in lines:
                value = line.strip()
                if not value.isascii() or not value.isdecimal():
                    raise _RuntimeEvidenceError("game_runtime.pid_invalid")
                pid = int(value)
                if pid <= 0:
                    raise _RuntimeEvidenceError("game_runtime.pid_invalid")
                pids.add(pid)
                if len(pids) > MAX_GAME_PROCESSES:
                    raise _RuntimeEvidenceError("game_runtime.process_limit")
        if not pids:
            raise _RuntimeEvidenceError("game_runtime.processes_missing")
        return tuple(sorted(pids))

    def _process(self, pid: int, steam_app_id: str) -> GameProcessInstance:
        directory = self._proc_root / str(pid)
        try:
            before = self._parse_stat(
                self._read_limited_text(directory / "stat", MAX_STAT_BYTES), pid
            )
            executable = self._readlink(directory / "exe")
            environment = self._read_environment(directory / "environ")
            after = self._parse_stat(
                self._read_limited_text(directory / "stat", MAX_STAT_BYTES), pid
            )
        except _RuntimeEvidenceError:
            raise
        except (OSError, UnicodeError) as error:
            raise _RuntimeEvidenceError("game_runtime.process_unavailable") from error
        if before != after:
            raise _RuntimeEvidenceError("game_runtime.process_identity_changed")
        parent_pid, start_time_ticks = before
        for key in APP_ID_ENV_KEYS:
            observed = environment.get(key)
            if observed is not None and observed != steam_app_id:
                raise _RuntimeEvidenceError("game_runtime.app_identity_changed")
        name = Path(executable.removesuffix(" (deleted)")).name
        try:
            return GameProcessInstance(
                pid=pid,
                start_time_ticks=start_time_ticks,
                parent_pid=parent_pid,
                executable_name=name,
                proton_marker=any(key in environment for key in PROTON_ENV_KEYS),
            )
        except ValueError as error:
            raise _RuntimeEvidenceError("game_runtime.process_invalid") from error

    @staticmethod
    def _parse_stat(value: str, expected_pid: int) -> tuple[int, int]:
        closing = value.rfind(")")
        if closing <= 1:
            raise _RuntimeEvidenceError("game_runtime.stat_invalid")
        prefix = value[:closing]
        opening = prefix.find("(")
        if opening <= 0:
            raise _RuntimeEvidenceError("game_runtime.stat_invalid")
        try:
            pid = int(prefix[:opening].strip())
            fields = value[closing + 1 :].strip().split()
            parent_pid = int(fields[1])
            start_time_ticks = int(fields[19])
        except (IndexError, ValueError) as error:
            raise _RuntimeEvidenceError("game_runtime.stat_invalid") from error
        if pid != expected_pid or parent_pid < 0 or start_time_ticks <= 0:
            raise _RuntimeEvidenceError("game_runtime.stat_invalid")
        return parent_pid, start_time_ticks

    @staticmethod
    def _read_limited_text(path: Path, limit: int) -> str:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise _RuntimeEvidenceError("game_runtime.evidence_unbounded")
        return raw.decode("utf-8", errors="strict")

    @staticmethod
    def _read_environment(path: Path) -> dict[str, str]:
        with path.open("rb") as stream:
            raw = stream.read(MAX_ENVIRON_BYTES + 1)
        if len(raw) > MAX_ENVIRON_BYTES:
            raise _RuntimeEvidenceError("game_runtime.environment_unbounded")
        result: dict[str, str] = {}
        for item in raw.split(b"\0"):
            key, separator, value = item.partition(b"=")
            if not separator:
                continue
            try:
                decoded_key = key.decode("ascii")
            except UnicodeDecodeError:
                continue
            if decoded_key not in PROTON_ENV_KEYS | APP_ID_ENV_KEYS:
                continue
            try:
                result[decoded_key] = value.decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise _RuntimeEvidenceError(
                    "game_runtime.environment_invalid"
                ) from error
        return result

    def _unknown(
        self, identity: ActiveGameIdentity, error_code: str
    ) -> ActiveGameRuntimeObservation:
        return self._result(
            identity,
            (),
            GameRuntimeKind.UNKNOWN,
            complete=False,
            error_code=error_code,
        )

    def _result(
        self,
        identity: ActiveGameIdentity,
        processes: tuple[GameProcessInstance, ...],
        runtime_kind: GameRuntimeKind,
        *,
        complete: bool,
        error_code: str,
    ) -> ActiveGameRuntimeObservation:
        semantic = "|".join(
            (
                identity.steam_app_id,
                *identity.scopes,
                runtime_kind.value,
                "complete" if complete else error_code,
                *(
                    f"{process.pid}:{process.start_time_ticks}:"
                    f"{process.parent_pid}:{process.executable_name}:"
                    f"{int(process.proton_marker)}"
                    for process in processes
                ),
            )
        ).encode("utf-8")
        generation = hashlib.sha256(semantic).hexdigest()
        with self._lock:
            self._counter += 1
            counter = self._counter
        sample_id = hashlib.sha256(
            semantic + f"|sample:{counter}".encode("ascii")
        ).hexdigest()
        return ActiveGameRuntimeObservation(
            steam_app_id=identity.steam_app_id,
            scopes=identity.scopes,
            processes=processes,
            runtime_kind=runtime_kind,
            generation=generation,
            sample_id=sample_id,
            complete=complete,
            error_code=error_code,
        )


class _RuntimeEvidenceError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
