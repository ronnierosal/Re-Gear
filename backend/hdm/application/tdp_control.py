"""Serialized TDP apply/readback/restore shared by manual and automatic requests.

The injected production journal must be durable. A timed-out queued write is
uncertain; this service never races it with a speculative restore or retry.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace
from typing import Callable

from ..ports.tdp import TdpJournal, TdpObservation, TdpProvider, TdpReading, TdpSessionRecord


@dataclass(frozen=True, slots=True)
class TdpControlResult:
    state: str
    code: str
    requested_watts: int | None = None
    observed_watts: int | None = None


class TdpControlService:
    def __init__(
        self, provider: TdpProvider, journal: TdpJournal, *,
        wait: Callable[[float], None] = time.sleep, verification_attempts: int = 5,
    ) -> None:
        if type(verification_attempts) is not int or not 1 <= verification_attempts <= 20:
            raise ValueError("TDP verification attempt count is invalid")
        self._provider = provider
        self._journal = journal
        self._wait = wait
        self._attempts = verification_attempts
        self._lock = threading.Lock()

    def apply(self, watts: int) -> TdpControlResult:
        if type(watts) is not int or not 0 < watts <= 0xFFFFFFFF:
            return TdpControlResult("blocked", "tdp.request_invalid")
        return self._run(watts, restoring=False)

    def restore(self) -> TdpControlResult:
        return self._run(None, restoring=True)

    def _observe(self) -> TdpObservation:
        try:
            return self._provider.observe()
        except Exception:
            return TdpObservation("tdp.observation_failed")

    def _save(self, record: TdpSessionRecord | None) -> bool:
        try:
            self._journal.save(record)
            return True
        except Exception:
            return False

    def _run(self, watts: int | None, *, restoring: bool) -> TdpControlResult:
        if not self._lock.acquire(blocking=False):
            return TdpControlResult("blocked", "tdp.busy", watts)
        try:
            return self._execute(watts, restoring=restoring)
        finally:
            self._lock.release()

    def _execute(self, watts: int | None, *, restoring: bool) -> TdpControlResult:
        try:
            record = self._journal.load()
        except Exception:
            return TdpControlResult("blocked", "tdp.journal_unavailable", watts)
        if record is not None and record.phase != "active":
            return TdpControlResult("recovery_required", "tdp.previous_write_uncertain", watts)
        if restoring and record is None:
            return TdpControlResult("unchanged", "tdp.nothing_to_restore")
        observation = self._observe()
        current = observation.reading
        if observation.code != "tdp.ready" or current is None:
            return TdpControlResult("blocked", observation.code, watts)
        if record is not None and current != record.applied:
            # Never overwrite another owner's update or a newly booted session.
            return TdpControlResult("recovery_required", "tdp.external_change", watts, current.sustained.current)
        baseline = record.baseline if record else current
        if restoring:
            watts = baseline.sustained.current
        try:
            target = current.target_values(watts)
            restorable = baseline.target_values(baseline.sustained.current) == baseline.values
        except ValueError:
            return TdpControlResult("blocked", "tdp.request_out_of_range", watts, current.sustained.current)
        if current.values == target:
            if restoring and not self._save(None):
                return TdpControlResult("recovery_required", "tdp.journal_unavailable", watts, current.sustained.current)
            return TdpControlResult("unchanged", "tdp.already_observed", watts, current.sustained.current)
        if not restorable or (restoring and target != baseline.values):
            return TdpControlResult("blocked", "tdp.baseline_not_restorable", watts, current.sustained.current)
        pending = TdpSessionRecord(baseline, current, "pending", watts)
        if not self._save(pending):
            return TdpControlResult("blocked", "tdp.journal_unavailable", watts)
        try:
            outcome = self._provider.set_limit(current, watts)
        except Exception:
            return TdpControlResult("recovery_required", "tdp.write_outcome_unknown", watts)
        if not outcome.attempted:
            if not self._save(record):
                return TdpControlResult("recovery_required", "tdp.journal_unavailable", watts)
            return TdpControlResult("blocked", outcome.code, watts, current.sustained.current)
        if not outcome.accepted:
            # Keep the persisted pending record. A queued operation can still run.
            return TdpControlResult("recovery_required", "tdp.write_outcome_unknown", watts)
        try:
            verified = self._verify(current, target)
        except Exception:
            verified = None
        if verified is None:
            return TdpControlResult("recovery_required", "tdp.readback_unverified", watts)
        saved = self._save(None if restoring else replace(pending, applied=verified, phase="active", pending_watts=None))
        if not saved:
            return TdpControlResult("recovery_required", "tdp.journal_unavailable", watts, verified.sustained.current)
        return TdpControlResult("restored" if restoring else "applied", "tdp.readback_verified", watts, verified.sustained.current)

    def _verify(self, before: TdpReading, target: tuple[int, int, int]) -> TdpReading | None:
        for attempt in range(self._attempts):
            if attempt:
                self._wait(0.1)
            observation = self._observe()
            reading = observation.reading
            if observation.code != "tdp.ready" or reading is None or not before.same_context(reading):
                return None
            if reading.values == target:
                return reading
            if any(value not in (old, wanted) for value, old, wanted in zip(reading.values, before.values, target)):
                return None
        return None
