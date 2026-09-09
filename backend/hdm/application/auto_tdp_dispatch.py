"""Immutable request-scoped Auto TDP identity and sample-expiry admission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..ports.tdp import TdpReading


@dataclass(frozen=True, slots=True)
class AutoTdpDispatchContext:
    # Activation key changes on every enable/reconfigure; None from the resolver
    # means disabled, closing, or ineligible. Workload key includes game/session.
    activation_key: str
    workload_key: str
    reading: TdpReading

    def __post_init__(self):
        if not isinstance(self.reading, TdpReading):
            raise ValueError("Auto TDP dispatch reading is invalid")
        if any(not isinstance(key, str) or not key for key in (self.activation_key, self.workload_key)):
            raise ValueError("Auto TDP dispatch context is invalid")


@dataclass(frozen=True, slots=True)
class AutoTdpDispatchGuard:
    expected: AutoTdpDispatchContext
    sampled_at_ms: int
    maximum_age_ms: int
    observe_context: Callable[[], AutoTdpDispatchContext | None]
    clock_ms: Callable[[], int]

    def __post_init__(self):
        if not isinstance(self.expected, AutoTdpDispatchContext) or not callable(self.observe_context) or not callable(self.clock_ms):
            raise ValueError("Auto TDP dispatch evidence is invalid")
        if type(self.sampled_at_ms) is not int or self.sampled_at_ms < 0 or type(self.maximum_age_ms) is not int or self.maximum_age_ms <= 0:
            raise ValueError("Auto TDP dispatch sample timing is invalid")

    def _fresh(self) -> bool:
        now = self.clock_ms()
        return type(now) is int and 0 <= now - self.sampled_at_ms <= self.maximum_age_ms

    def __call__(self) -> bool:
        # Expensive identity/readiness resolution must not refresh the sample's
        # timestamp. Recheck age after that work and immediately before dispatch.
        if not self._fresh():
            return False
        observed = self.observe_context()
        return isinstance(observed, AutoTdpDispatchContext) and observed == self.expected and self._fresh()
