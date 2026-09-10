"""Read-only Gamescope process and startup-state discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GamescopeProcessRecord:
    pid: int
    argv: tuple[str, ...]
    output_order: tuple[str, ...] = field(default_factory=tuple)
    prefer_vk_device: str = ""
    mesa_vk_device_select: str = ""
    environment_readable: bool = False
    uid: int | None = None
    start_time_ticks: int = 0


@dataclass(frozen=True, slots=True)
class GamescopeScan:
    process: GamescopeProcessRecord | None
    candidate_count: int
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.process is not None and self.candidate_count == 1 and not self.error


def _option(argv: tuple[str, ...], short: str, long: str) -> str:
    value = ""
    index = 0
    while index < len(argv):
        item = argv[index]
        if item in (short, long):
            if index + 1 < len(argv):
                value = argv[index + 1]
            index += 2
            continue
        long_prefix = long + "="
        if item.startswith(long_prefix):
            value = item[len(long_prefix) :]
        index += 1
    return value.strip()


def parse_gamescope_process(
    pid: int,
    argv: tuple[str, ...],
    environment: dict[str, str] | None = None,
    environment_readable: bool = False,
    uid: int | None = None,
    start_time_ticks: int = 0,
) -> GamescopeProcessRecord:
    output = _option(argv, "-O", "--prefer-output")
    output_order = tuple(part.strip() for part in output.split(",") if part.strip())
    return GamescopeProcessRecord(
        pid=pid,
        argv=argv,
        output_order=output_order,
        prefer_vk_device=_option(argv, "", "--prefer-vk-device").lower(),
        mesa_vk_device_select=str((environment or {}).get("MESA_VK_DEVICE_SELECT", "")).lower(),
        environment_readable=environment_readable,
        uid=uid,
        start_time_ticks=start_time_ticks,
    )


def parse_process_start_time(value: str, expected_pid: int) -> int:
    """Return Linux /proc stat field 22 without trusting the process name."""

    closing = value.rfind(")")
    if closing <= 1:
        return 0
    opening = value[:closing].find("(")
    if opening <= 0:
        return 0
    try:
        pid = int(value[:opening].strip())
        fields = value[closing + 1 :].strip().split()
        start_time_ticks = int(fields[19])
    except (IndexError, ValueError):
        return 0
    if pid != expected_pid or start_time_ticks <= 0:
        return 0
    return start_time_ticks


class GamescopeDiscovery:
    def __init__(self, proc_root: Path = Path("/proc")) -> None:
        self._proc_root = proc_root

    def scan(self) -> GamescopeScan:
        try:
            entries = tuple(self._proc_root.iterdir())
        except OSError:
            return GamescopeScan(None, 0, "Process filesystem is unavailable")
        candidates: list[GamescopeProcessRecord] = []
        for process_path in entries:
            if not process_path.name.isdigit():
                continue
            try:
                raw = (process_path / "cmdline").read_bytes()
            except OSError:
                continue
            argv = tuple(
                part.decode("utf-8", errors="replace")
                for part in raw.split(b"\0")
                if part
            )
            if (
                not argv
                or Path(argv[0]).name != "gamescope"
                or ("-e" not in argv and "--steam" not in argv)
            ):
                continue
            try:
                environment_raw = (process_path / "environ").read_bytes()
                environment_readable = True
            except OSError:
                environment_raw = b""
                environment_readable = False
            try:
                uid = process_path.stat().st_uid
            except (AttributeError, OSError):
                uid = None
            try:
                start_time_ticks = parse_process_start_time(
                    (process_path / "stat").read_text(encoding="utf-8"),
                    int(process_path.name),
                )
            except (OSError, UnicodeError):
                start_time_ticks = 0
            environment: dict[str, str] = {}
            for part in environment_raw.split(b"\0"):
                if not part.startswith(b"MESA_VK_DEVICE_SELECT="):
                    continue
                key, _, value = part.partition(b"=")
                environment[key.decode("utf-8", errors="replace")] = value.decode(
                    "utf-8", errors="replace"
                )
            candidates.append(
                parse_gamescope_process(
                    int(process_path.name),
                    argv,
                    environment,
                    environment_readable,
                    uid,
                    start_time_ticks,
                )
            )
        if len(candidates) == 1:
            return GamescopeScan(candidates[0], 1)
        if not candidates:
            return GamescopeScan(None, 0, "Gamescope process was not found")
        return GamescopeScan(None, len(candidates), "Multiple Gamescope processes were found")
