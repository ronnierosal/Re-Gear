"""Read-only, allowlisted SteamOS version discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SteamOsVersionInfo:
    steamos: str = "unknown"
    kernel: str = "unknown"


def _os_release_value(text: str, key: str) -> str:
    prefix = f"{key}="
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip().strip('"\'')[:80] or "unknown"
    return "unknown"


class SteamOsVersionDiscovery:
    def __init__(
        self,
        os_release: Path = Path("/etc/os-release"),
        kernel_release: Path = Path("/proc/sys/kernel/osrelease"),
    ) -> None:
        self._os_release = os_release
        self._kernel_release = kernel_release

    def scan(self) -> SteamOsVersionInfo:
        try:
            os_release = self._os_release.read_text(encoding="utf-8", errors="replace")
        except OSError:
            os_release = ""
        version_id = _os_release_value(os_release, "VERSION_ID")
        build_id = _os_release_value(os_release, "BUILD_ID")
        steamos = version_id if build_id == "unknown" else f"{version_id} ({build_id})"
        try:
            kernel = self._kernel_release.read_text(
                encoding="utf-8", errors="replace"
            ).strip()[:120]
        except OSError:
            kernel = "unknown"
        return SteamOsVersionInfo(steamos or "unknown", kernel or "unknown")
