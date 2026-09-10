"""Privacy-safe identity binding for the current Gamescope process instance."""

from __future__ import annotations

import hashlib
from typing import Protocol

from ...domain.gamescope_session import GamescopeSessionObservation
from .gamescope import GamescopeScan


class GamescopeScanPort(Protocol):
    def scan(self) -> GamescopeScan: ...


class GamescopeSessionObservationAdapter:
    def __init__(self, discovery: GamescopeScanPort) -> None:
        self._discovery = discovery

    def observe(self) -> GamescopeSessionObservation:
        try:
            scan = self._discovery.scan()
        except Exception:
            scan = None
        if scan is None or not scan.ok or scan.process is None:
            return GamescopeSessionObservation(
                False, "gamescope.session_unavailable"
            )
        process = scan.process
        if process.uid is None or process.uid < 0 or process.start_time_ticks <= 0:
            return GamescopeSessionObservation(
                False, "gamescope.session_identity_unverified"
            )
        private_identity = f"{process.pid}:{process.start_time_ticks}:{process.uid}"
        generation = hashlib.sha256(private_identity.encode("ascii")).hexdigest()
        return GamescopeSessionObservation(
            True, "gamescope.session_observed", generation
        )
