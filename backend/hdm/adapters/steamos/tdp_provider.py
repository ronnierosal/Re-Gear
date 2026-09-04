"""ASUS firmware-backed SteamOS Manager TDP provider with explicit ownership."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path

from ...ports.presentation_activation import GamescopeUserContext
from ...ports.tdp import TdpObservation, TdpReading, TdpRegister, TdpWriteOutcome
from ...profiles.ally_x import PROFILE_ID, matches_ally_x
from .commands import SteamOsTdpCommandRunner
from .host import HostDiscovery
from .tdp_inventory import AsusTdpInventory


def _register(output: str) -> TdpRegister:
    if len(output) > 128:
        raise ValueError("TDP output too large")
    lines = output.splitlines()
    if len(lines) != 3 or any(re.fullmatch(r"u [0-9]{1,10}", line) is None for line in lines):
        raise ValueError("TDP output malformed")
    return TdpRegister(*(int(line[2:]) for line in lines))


def _owner(output: str) -> str:
    match = re.fullmatch(r's "(:[0-9]+\.[0-9]+)"\n?', output)
    if len(output) > 128 or match is None:
        raise ValueError("TDP owner malformed")
    return match[1]


class SteamOsManagerTdpProvider:
    """Observe one exact firmware backend; setting commands never prove readback.

    Ownership must come from the caller's separate coordination mechanism.
    The D-Bus and sysfs observations are sequential, not an atomic snapshot.
    """

    def __init__(
        self,
        *,
        user_resolver: Callable[[], GamescopeUserContext | None],
        host: HostDiscovery | None = None,
        inventory: AsusTdpInventory | None = None,
        commands: SteamOsTdpCommandRunner | None = None,
        ownership_ready: Callable[[], bool] = lambda: False,
        boot_id_path: Path = Path("/proc/sys/kernel/random/boot_id"),
    ) -> None:
        self._user_resolver = user_resolver
        self._host = host or HostDiscovery()
        self._inventory = inventory or AsusTdpInventory()
        self._commands = commands or SteamOsTdpCommandRunner()
        self._ownership_ready = ownership_ready
        self._boot_id_path = boot_id_path

    def observe(self) -> TdpObservation:
        return self._observe()[0]

    def _observe(self) -> tuple[TdpObservation, GamescopeUserContext | None, str | None]:
        def unavailable(code: str):
            return TdpObservation(code), None, None

        try:
            if not matches_ally_x(self._host.scan()):
                return unavailable("tdp.host_unverified")
            user = self._user_resolver()
            if not isinstance(user, GamescopeUserContext) or type(user.uid) is not int or not 0 < user.uid < 0xFFFFFFFF:
                return unavailable("tdp.user_unverified")
            with self._boot_id_path.open("rb") as stream:
                boot = stream.read(65)
            if re.fullmatch(rb"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\n?", boot) is None:
                return unavailable("tdp.boot_unverified")
            before = self._commands.owner(user)
            if not before.ok:
                return unavailable("tdp.owner_unavailable")
            owner = _owner(before.stdout)
            result = self._commands.read(user)
            if not result.ok:
                return unavailable("tdp.read_unavailable")
            dbus = _register(result.stdout)
            sources = self._inventory.scan().sources
            firmware = [s for s in sources if s.source == "asus_firmware_attributes"]
            if any(s.attribute == "ppt_fppt" and s.status != "absent" for s in firmware):
                return unavailable("tdp.source_ambiguous")
            registers = []
            for attribute in ("ppt_pl1_spl", "ppt_pl2_sppt", "ppt_pl3_fppt"):
                rows = [s for s in firmware if s.attribute == attribute]
                if len(rows) != 1 or rows[0].status != "observed" or rows[0].ordering != "consistent":
                    return unavailable("tdp.firmware_unverified")
                fields = rows[0].fields[:3]
                if len(fields) != 3 or any(f.status != "observed" for f in fields):
                    return unavailable("tdp.firmware_unverified")
                registers.append(TdpRegister(*(field.value for field in fields)))
            if registers[0] != dbus:
                return unavailable("tdp.source_disagreement")
            after = self._commands.owner(user)
            if not after.ok or _owner(after.stdout) != owner:
                return unavailable("tdp.owner_changed")
            binding = hashlib.sha256(b"\0".join((boot.strip(), str(user.uid).encode(), owner.encode(), PROFILE_ID.encode()))).hexdigest()
            reading = TdpReading(binding, *registers)
            code = "tdp.ready" if self._ownership_ready() is True else "tdp.ownership_unverified"
            return TdpObservation(code, reading), user, owner
        except Exception:
            return unavailable("tdp.observation_invalid")

    def set_limit(self, expected: TdpReading, watts: int) -> TdpWriteOutcome:
        observation, user, owner = self._observe()
        if observation.code != "tdp.ready" or observation.reading is None or user is None or owner is None:
            return TdpWriteOutcome(False, False, observation.code)
        if observation.reading != expected:
            return TdpWriteOutcome(False, False, "tdp.context_changed")
        try:
            observation.reading.target_values(watts)
        except ValueError:
            return TdpWriteOutcome(False, False, "tdp.limit_invalid")
        # Reuse this observation's resolved identity. Do not resolve a different
        # session between validation and dispatch, or retain mutable cached users.
        try:
            result = self._commands.set_limit(user, watts, owner=owner)
        except Exception:
            return TdpWriteOutcome(True, False, "tdp.write_unverified")
        return TdpWriteOutcome(
            True, result.ok,
            "tdp.write_accepted" if result.ok else "tdp.write_unverified",
        )
