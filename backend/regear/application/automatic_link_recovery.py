"""Bounded attach recovery scheduling; events wake observation, never commands."""
from __future__ import annotations

import math


class AutomaticLinkRecovery:
    """Ten-second settling and cooldown, two attempts, no replay after reload."""

    def __init__(self) -> None:
        self.armed = False
        self.identity = ""
        self.attempts = 0
        self.in_flight = False
        self.completed = False
        self.due: float | None = None
        self.idle_since: float | None = None

    def observe(self, *, now: float, absent: bool, present: bool, identity: str,
                pci_complete: bool, enabled: bool, idle: bool) -> bool:
        if not math.isfinite(now) or self.in_flight:
            return False
        if absent and not present:
            self.__init__()
            self.armed = True
            return False
        if not self.armed:
            return False
        if pci_complete:
            self.completed = True
        if not present or not identity.startswith("transport:") or identity == "transport:unresolved":
            self.idle_since = None
            return False
        if not self.identity:
            self.identity = identity
            self.due = now + 10
        if identity != self.identity:
            self.armed = False  # identity changes do not prove physical removal
            return False
        if not enabled or not idle:
            self.idle_since = None
            return False
        if self.idle_since is None:
            self.idle_since = now
        return (not self.completed and self.attempts < 2 and self.due is not None
                and now >= self.due and now - self.idle_since >= 10)

    def begin(self) -> None:
        if self.in_flight or self.attempts >= 2:
            raise RuntimeError("automatic recovery budget unavailable")
        self.attempts += 1
        self.in_flight = True

    def finish(self, now: float) -> None:
        self.in_flight = False
        self.due = now + 10
        self.idle_since = None
