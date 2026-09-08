"""Explicit Auto TDP session using the shared transaction engine, without a timer.

Delivery owns scheduling, provider ownership/lease, and restoration after stop.
The revalidator must return None whenever current game/render/thermal/power or
controller eligibility is missing. Its full live reading is compared at dispatch.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, replace
from typing import Callable, Protocol

from ..domain.auto_tdp import AutoTdpObservation, AutoTdpPolicy, AutoTdpState, propose_auto_tdp
from ..domain.models import GameState
from ..domain.telemetry import TelemetryAdmissionKind, TelemetryCollectionContract, TelemetryConsumer, admit_telemetry_collection
from ..ports.tdp import TdpDispatchGuard, TdpReading
from .auto_tdp_dispatch import AutoTdpDispatchContext, AutoTdpDispatchGuard
from .tdp_control import TdpControlResult


class AutoTdpActuator(Protocol):
    def apply(self, watts: int, *, dispatch_guard: TdpDispatchGuard) -> TdpControlResult: ...


@dataclass(frozen=True, slots=True)
class AutoTdpEvidence:
    observation: AutoTdpObservation
    reading: TdpReading


@dataclass(frozen=True, slots=True)
class AutoTdpLiveContext:
    workload_key: str
    reading: TdpReading


@dataclass(frozen=True, slots=True)
class AutoTdpSessionResult:
    code: str
    enabled: bool
    proposed_watts: int | None = None
    transaction: TdpControlResult | None = None


class AutoTdpSession:
    def __init__(self, *, service: AutoTdpActuator,
                 collect: Callable[[], AutoTdpEvidence | None],
                 revalidate: Callable[[], AutoTdpLiveContext | None],
                 game_state: Callable[[], GameState], clock_ms: Callable[[], int],
                 contract: TelemetryCollectionContract,
                 reset_collection: Callable[[], None] | None = None):
        if contract.consumer is not TelemetryConsumer.AUTO_TDP:
            raise ValueError("Auto TDP requires its own collection contract")
        self._service, self._collect, self._revalidate = service, collect, revalidate
        self._game_state, self._clock, self._contract = game_state, clock_ms, contract
        self._activation: str | None = None
        self._policy: AutoTdpPolicy | None = None
        self._state = AutoTdpState()
        self._provider_context: TdpReading | None = None
        self._last_collection_ms: int | None = None
        self._lock = threading.Lock()
        self._control_lock = threading.Lock()
        self._stop_generation = 0
        self._reset_collection = reset_collection
        self._pending_response = None

    @property
    def enabled(self) -> bool:
        return self._activation is not None

    @property
    def collection_interval_ms(self) -> int:
        return self._contract.interval_ms

    def _result(self, code, proposed=None, transaction=None):
        return AutoTdpSessionResult(code, self.enabled, proposed, transaction)

    def start(self, policy: AutoTdpPolicy) -> AutoTdpSessionResult:
        if not isinstance(policy, AutoTdpPolicy):
            raise ValueError("Auto TDP policy is invalid")
        if not self._lock.acquire(blocking=False):
            return self._result("auto_tdp.busy")
        try:
            with self._control_lock:
                stop_generation = self._stop_generation
            admission = admit_telemetry_collection(self._contract, GameState.RUNNING, auto_tdp_enabled=True)
            if admission.kind is not TelemetryAdmissionKind.ADMIT:
                return self._result(admission.reason)
            if self._reset_collection is not None:
                self._reset_collection()
            with self._control_lock:
                if self._stop_generation != stop_generation:
                    return self._result("auto_tdp.activation_changed")
                self._policy, self._state = policy, AutoTdpState()
                self._provider_context = None
                self._pending_response = None
                self._last_collection_ms = None
                self._activation = uuid.uuid4().hex
            return self._result("auto_tdp.started")
        finally:
            self._lock.release()

    def stop(self) -> AutoTdpSessionResult:
        # Immediate invalidation lets an in-flight late dispatch guard refuse.
        # Do not issue an overlapping restore; delivery joins/drains first.
        with self._control_lock:
            self._stop_generation += 1
            self._activation = None
            self._pending_response = None
        return self._result("auto_tdp.stopped")

    def _context(self, activation: str) -> AutoTdpDispatchContext | None:
        if self._activation != activation:
            return None
        live = self._revalidate()
        if self._activation != activation or not isinstance(live, AutoTdpLiveContext):
            return None
        return AutoTdpDispatchContext(activation, live.workload_key, live.reading)

    def tick(self) -> AutoTdpSessionResult:
        if not self._lock.acquire(blocking=False):
            return self._result("auto_tdp.busy")
        try:
            activation, policy = self._activation, self._policy
            if activation is None or policy is None:
                return self._result("auto_tdp.disabled")
            now = self._clock()
            if type(now) is not int or now < 0 or (self._last_collection_ms is not None and now < self._last_collection_ms):
                raise ValueError("Auto TDP clock is invalid")
            if self._last_collection_ms is not None and now - self._last_collection_ms < self._contract.interval_ms:
                return self._result("auto_tdp.waiting_interval")
            self._last_collection_ms = now
            admission = admit_telemetry_collection(self._contract, self._game_state(), auto_tdp_enabled=True)
            if admission.kind is not TelemetryAdmissionKind.ADMIT:
                self._state = AutoTdpState()
                self._pending_response = None
                if self._reset_collection is not None:
                    self._reset_collection()
                return self._result(admission.reason)
            evidence = self._collect()
            if self._activation != activation:
                self._state = AutoTdpState()
                return self._result("auto_tdp.activation_changed")
            if not isinstance(evidence, AutoTdpEvidence):
                self._state = AutoTdpState()
                if self._pending_response is not None:
                    key, expected_reading, _, _, deadline = self._pending_response
                    live = self._revalidate()
                    if (not isinstance(live, AutoTdpLiveContext) or live.workload_key != key
                            or live.reading != expected_reading or self._clock() > deadline):
                        self._pending_response = None
                return self._result("auto_tdp.sample_unavailable")
            sample, reading = evidence.observation, evidence.reading
            if (sample.configured_watts != reading.sustained.current
                    or policy.minimum_watts < reading.sustained.minimum
                    or policy.maximum_watts > reading.sustained.maximum):
                self._state = AutoTdpState()
                return self._result("auto_tdp.readback_invalid")
            reading.target_values(policy.minimum_watts)
            reading.target_values(policy.maximum_watts)
            if self._provider_context is not None and not self._provider_context.same_context(reading):
                self._state = AutoTdpState()
            self._provider_context = reading
            decision = propose_auto_tdp(policy, self._state, sample, now_ms=self._clock())
            self._state = decision.state
            # A verified setting change makes the real collector rewarm. Preserve
            # only the response baseline across that expected gap, never its vote
            # streak or permission to write. Fresh full context must match again.
            if self._pending_response is not None:
                key, expected_reading, baseline_fps, ineffective, deadline = self._pending_response
                if (sample.context_key != key or reading != expected_reading or self._clock() > deadline
                        or not all(value is True for value in (sample.internal_render_verified,
                            sample.controller_owned, sample.thermal_ready, sample.power_source_ready))):
                    self._pending_response = None
                elif decision.code == "auto_tdp.context_settling":
                    self._state = replace(self._state, increase_baseline_fps=baseline_fps,
                                          ineffective_increases=ineffective)
                    self._pending_response = None
                else:
                    self._pending_response = None
            if decision.proposed_watts is None:
                return self._result(decision.code)
            expected = AutoTdpDispatchContext(activation, sample.context_key, reading)
            guard = AutoTdpDispatchGuard(expected, sample.sampled_at_ms, policy.maximum_sample_age_ms,
                                         lambda: self._context(activation), self._clock)
            result = self._service.apply(decision.proposed_watts, dispatch_guard=guard)
            if result.state == "applied" and result.observed_watts == decision.proposed_watts:
                self._state = replace(self._state, configured_watts=result.observed_watts, last_change_ms=self._clock())
                if decision.proposed_watts > sample.configured_watts:
                    target = reading.target_values(decision.proposed_watts)
                    expected_reading = replace(reading,
                        sustained=replace(reading.sustained, current=target[0]),
                        slow=replace(reading.slow, current=target[1]),
                        fast=replace(reading.fast, current=target[2]))
                    self._pending_response = (sample.context_key, expected_reading,
                        self._state.increase_baseline_fps, self._state.ineffective_increases,
                        self._clock() + 30_000)
                else:
                    self._pending_response = None
            else:
                self._state = AutoTdpState()
                self._pending_response = None
            if result.state == "recovery_required":
                self._activation = None
            return self._result(result.code, decision.proposed_watts, result)
        except Exception:
            self._state = AutoTdpState()
            self._activation = None
            return self._result("auto_tdp.session_unavailable")
        finally:
            self._lock.release()
