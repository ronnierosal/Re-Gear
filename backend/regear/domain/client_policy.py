"""Pure policy for classifying processes that hold certified eGPU resources."""

from __future__ import annotations

from dataclasses import dataclass

from .models import EgpuClientKind


PROTECTED_PROCESS_NAMES = frozenset(
    {
        "gamescope",
        "kwin_wayland",
        "pluginloader",
        "pipewire",
        "sddm",
        "steam",
        "steamwebhelper",
        "wireplumber",
        "xorg",
        "xwayland",
    }
)


@dataclass(frozen=True, slots=True)
class ClientClassification:
    kind: EgpuClientKind
    close_eligible: bool
    reason: str


def classify_egpu_client(
    *,
    pid: int,
    name: str,
    uid: int | None,
    session_uid: int | None,
    gamescope_pid: int | None,
    in_game_scope: bool,
) -> ClientClassification:
    """Classify from bounded facts; future mutation must revalidate all facts."""
    normalized_name = name.casefold()
    if gamescope_pid is not None and pid == gamescope_pid:
        return ClientClassification(
            EgpuClientKind.PROTECTED, False, "Steam session compositor"
        )
    if in_game_scope:
        return ClientClassification(EgpuClientKind.GAME, False, "Steam game scope")
    if uid == 0:
        return ClientClassification(EgpuClientKind.SYSTEM, False, "Root-owned process")
    if normalized_name in PROTECTED_PROCESS_NAMES:
        return ClientClassification(
            EgpuClientKind.PROTECTED, False, "Protected SteamOS session process"
        )
    if uid is None or session_uid is None:
        return ClientClassification(
            EgpuClientKind.UNKNOWN, False, "Process ownership is unverified"
        )
    if uid != session_uid:
        return ClientClassification(
            EgpuClientKind.SYSTEM, False, "Process belongs to another user"
        )
    return ClientClassification(
        EgpuClientKind.USER, True, "User process outside a Steam game scope"
    )
