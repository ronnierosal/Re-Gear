"""Bounded attach recovery scheduling; events wake observation, never commands."""
from __future__ import annotations

import math


class AutomaticLinkRecovery:
    """Ten-second attach settling and cooldown, two attempts, no replay after reload."""

    def __init__(self) -> None:
        self.armed = False
        self.identity = ""
        self.attempts = 0
        self.in_flight = False
        self.completed = False
        self.due: float | None = None
        self.decision_code = "automatic_recovery.not_observed"

    def _decision(self, reason: str, ready: bool = False) -> bool:
        self.decision_code = "automatic_recovery." + reason
        return ready

    def observe(self, *, now: float, absent: bool, present: bool, identity: str,
                pci_complete: bool, enabled: bool, idle: bool) -> bool:
        if not math.isfinite(now):
            return self._decision("clock_unavailable")
        if self.in_flight:
            return self._decision("in_flight")
        if absent and not present:
            self.__init__()
            self.armed = True
            return self._decision("waiting_for_transport")
        if not self.armed:
            return self._decision("waiting_for_detach")
        if pci_complete:
            self.completed = True
        if not present or not identity.startswith("transport:") or identity == "transport:unresolved":
            return self._decision("waiting_for_transport" if not present else "transport_unresolved")
        if not self.identity:
            self.identity = identity
            self.due = now + 10
        if identity != self.identity:
            self.armed = False  # identity changes do not prove physical removal
            return self._decision("transport_changed")
        if not enabled or not idle:
            return self._decision("disabled" if not enabled else "waiting_for_idle")
        if self.completed:
            return self._decision("completed")
        if self.attempts >= 2:
            return self._decision("attempts_exhausted")
        # The attachment/cooldown timer is the settle window. A transient
        # non-idle sample must still block the current observation, but it must
        # not silently start a second ten-second delay after the original due
        # time. The caller and reserved dispatch preflight both re-read the
        # current game/session/identity evidence before any command runs.
        ready = self.due is not None and now >= self.due
        return self._decision("ready" if ready else "settling", ready)

    def begin(self) -> None:
        if self.in_flight or self.attempts >= 2:
            raise RuntimeError("automatic recovery budget unavailable")
        self.attempts += 1
        self.in_flight = True

    def finish(self, now: float) -> None:
        self.in_flight = False
        self.due = now + 10
