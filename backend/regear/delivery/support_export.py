"""Fixed-boundary support bundle file export."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..application.support_bundle import SupportBundle
from .user_directory import UserDirectory


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class SupportBundleSaveResult:
    relative_path: str
    size_bytes: int


class SupportBundleFileWriter:
    def __init__(
        self,
        *,
        allowed_home_parent: Path = Path("/home"),
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._allowed_home_parent = allowed_home_parent.absolute()
        self._clock = clock

    def save(self, raw_home: Path, bundle: SupportBundle) -> SupportBundleSaveResult:
        if not raw_home.is_absolute():
            raise ValueError("Decky user home is unavailable")
        home = raw_home
        if home.parent != self._allowed_home_parent or home.name in {"", ".", ".."}:
            raise ValueError("Decky user home is outside the supported SteamOS boundary")

        timestamp = self._clock().astimezone(timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        filename = f"Re-Gear-support-{timestamp}.json"
        with UserDirectory(home) as user_home:
            with UserDirectory(home / "Downloads", user_home.uid, user_home.gid,
                               create_from=home, create=True) as downloads:
                downloads.publish(filename, bundle.json_text.encode("utf-8"), 0o600)
        return SupportBundleSaveResult(
            relative_path=f"Downloads/{filename}",
            size_bytes=bundle.size_bytes,
        )
