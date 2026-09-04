"""Single TDP transaction owner with optional explicitly configured Auto worker."""

from __future__ import annotations

import threading
from dataclasses import asdict
from typing import Callable, Protocol

from ..application.tdp_control import TdpControlResult, TdpControlService
from ..application.auto_tdp_session import AutoTdpActuator, AutoTdpSession
from ..domain.auto_tdp import AutoTdpPolicy
from ..ports.tdp import TdpDispatchGuard, TdpJournal, TdpProvider
from .auto_tdp_worker import AutoTdpWorker, AutoTdpWorkerStatus


class _AutoActuator:
    def __init__(self, runtime: TdpRuntime):
        self._runtime = runtime

    def apply(self, watts: int, *, dispatch_guard: TdpDispatchGuard) -> TdpControlResult:
        return self._runtime._apply_auto(watts, dispatch_guard)


class WriterLease(Protocol):
    held: bool
    def acquire(self) -> bool: ...
    def close(self) -> None: ...


def unavailable_status(code: str = "tdp.runtime_unavailable") -> dict[str, object]:
    return {
        "schema_version": 1, "enabled": False, "can_enable": False,
        "ready": False, "code": code, "current_watts": None,
        "minimum_watts": None, "maximum_watts": None,
        "restore_available": False, "recovery_required": False,
        "auto_tdp_available": False, "last_result": None,
    }


class TdpRuntime:
    def __init__(
        self, *, provider_factory: Callable[[Callable[[], bool]], TdpProvider],
        journal: TdpJournal, lease: WriterLease, preflight: Callable[[], str],
        service_factory: Callable[..., TdpControlService] = TdpControlService,
        auto_session_factory: Callable[[AutoTdpActuator, TdpProvider], AutoTdpSession] | None = None,
    ) -> None:
        self._journal = journal
        self._lease = lease
        self._preflight = preflight
        self._enabled = False
        self._closing = threading.Event()
        self._lock = threading.Lock()
        self._last_result: TdpControlResult | None = None
        self._provider = provider_factory(self._may_write)
        self._service = service_factory(self._provider, self._journal)
        self._auto_factory = auto_session_factory
        self._auto_worker: AutoTdpWorker | None = None
        self._disable_requested = threading.Event()
        self._auto_cancel = threading.Event()
        self._auto_control_lock = threading.Lock()
        self._auto_generation = 0

    def _may_write(self) -> bool:
        return (
            not self._closing.is_set() and self._enabled and self._lease.held
            and self._preflight() == "tdp.ready"
        )

    def _run(self, action: Callable[[], dict[str, object]]) -> dict[str, object]:
        if self._closing.is_set():
            return unavailable_status("tdp.closing")
        if not self._lock.acquire(blocking=False):
            return unavailable_status("tdp.busy")
        try:
            if self._closing.is_set():
                return unavailable_status("tdp.closing")
            return action()
        except Exception:
            result = unavailable_status()
            result["enabled"] = self._enabled
            result["last_result"] = asdict(self._last_result) if self._last_result else None
            return result
        finally:
            self._release_operation()

    def _release_operation(self) -> None:
        try:
            self._finish_operation()
        finally:
            self._lock.release()
        # A close/disable can arrive after cleanup checked flags but before
        # unlock. Once unlocked, either we drain it or the new lock owner does.
        while (self._disable_requested.is_set() or
               (self._closing.is_set() and (self._enabled or self._lease.held))):
            if not self._lock.acquire(blocking=False):
                return
            try:
                self._finish_operation()
            finally:
                self._lock.release()

    def _finish_operation(self) -> None:
        # Caller holds the one transaction lock, including automatic apply.
        if self._closing.is_set():
            self._enabled = False
            self._lease.close()
            self._disable_requested.clear()
        elif self._disable_requested.is_set():
            self._disable()

    def _disable(self) -> None:
        try:
            if self._journal.load() is not None:
                if not self._lease.acquire():
                    self._last_result = TdpControlResult("blocked", "tdp.writer_busy")
                    return
                self._enabled = True
                self._last_result = self._service.restore()
        except Exception:
            self._last_result = TdpControlResult("recovery_required", "tdp.journal_unavailable")
        finally:
            self._enabled = False
            self._lease.close()
            self._disable_requested.clear()

    def start_auto(self, policy: AutoTdpPolicy) -> AutoTdpWorkerStatus | None:
        with self._auto_control_lock:
            generation = self._auto_generation
        if self._closing.is_set() or not self._lock.acquire(blocking=False):
            return None
        try:
            if self._closing.is_set() or self._disable_requested.is_set() or self._auto_factory is None:
                return None
            with self._auto_control_lock:
                if generation != self._auto_generation:
                    return None
                self._auto_cancel.clear()
            if not self._status()["ready"]:
                return None
            if self._auto_worker is None:
                session = self._auto_factory(_AutoActuator(self), self._provider)
                self._auto_worker = AutoTdpWorker(session, interval_ms=session.collection_interval_ms)
            if self._closing.is_set() or self._disable_requested.is_set() or self._auto_cancel.is_set():
                self.stop_auto()
                return None
            status = self._auto_worker.start(policy)
            if self._closing.is_set() or self._disable_requested.is_set() or self._auto_cancel.is_set():
                return self._auto_worker.stop()
            return status
        except Exception:
            self.stop_auto()
            return None
        finally:
            self._release_operation()

    def stop_auto(self) -> AutoTdpWorkerStatus | None:
        with self._auto_control_lock:
            self._auto_generation += 1
            self._auto_cancel.set()
        worker = self._auto_worker
        return worker.stop() if worker is not None else None

    def auto_status(self) -> AutoTdpWorkerStatus | None:
        worker = self._auto_worker
        return worker.status() if worker is not None else None

    def _apply_auto(self, watts: int, guard: TdpDispatchGuard) -> TdpControlResult:
        if self._closing.is_set():
            return TdpControlResult("blocked", "tdp.closing", watts)
        if not self._lock.acquire(blocking=False):
            return TdpControlResult("blocked", "tdp.busy", watts)
        try:
            if self._closing.is_set() or self._disable_requested.is_set() or self._auto_cancel.is_set() or not self._enabled:
                return TdpControlResult("blocked", "tdp.enable_required", watts)
            if not callable(guard):
                return TdpControlResult("blocked", "tdp.request_invalid", watts)
            self._last_result = self._service.apply(watts, dispatch_guard=guard)
            return self._last_result
        finally:
            self._release_operation()

    def status(self) -> dict[str, object]:
        return self._run(self._status)

    def _status(self) -> dict[str, object]:
        output = unavailable_status()
        output["enabled"] = self._enabled
        output["last_result"] = asdict(self._last_result) if self._last_result else None
        guard = self._preflight()
        observation = self._provider.observe()
        reading = observation.reading
        if reading is not None:
            output.update(current_watts=reading.sustained.current,
                          minimum_watts=reading.sustained.minimum,
                          maximum_watts=reading.sustained.maximum)
        try:
            record = self._journal.load()
        except Exception:
            output.update(code="tdp.journal_unavailable", recovery_required=True)
            return output
        if record and record.phase != "active":
            output.update(code="tdp.previous_write_uncertain", recovery_required=True)
            return output
        if record and reading != record.applied:
            output.update(code="tdp.external_change", recovery_required=True)
            return output
        if guard != "tdp.ready":
            output["code"] = guard
            return output
        if reading is None or observation.code not in ("tdp.ready", "tdp.ownership_unverified"):
            output["code"] = observation.code
            return output
        if self._enabled and observation.code != "tdp.ready":
            output["code"] = observation.code
            return output
        baseline = record.baseline if record else reading
        try:
            restorable = baseline.target_values(baseline.sustained.current) == baseline.values
        except ValueError:
            restorable = False
        if not restorable:
            output["code"] = "tdp.baseline_not_restorable"
            return output
        output.update(can_enable=True, ready=self._enabled and self._lease.held,
                      code="tdp.ready" if self._enabled and self._lease.held else "tdp.disabled",
                      restore_available=record is not None)
        return output

    def set_enabled(self, enabled: bool) -> dict[str, object]:
        if type(enabled) is not bool:
            return unavailable_status("tdp.request_invalid")
        if not enabled:
            self._disable_requested.set()
            self.stop_auto()
        def action():
            if enabled:
                if self._disable_requested.is_set():
                    return unavailable_status("tdp.busy")
                before = self._status()
                if not before["can_enable"]:
                    return before
                if not self._lease.acquire():
                    before.update(ready=False, can_enable=False, code="tdp.writer_busy")
                    return before
                self._enabled = True
            else:
                self._disable()
            return self._status()
        return self._run(action)

    def apply(self, watts: int) -> dict[str, object]:
        self.stop_auto()
        def action():
            if not self._enabled:
                output = self._status()
                output.update(ready=False, code="tdp.enable_required")
                return output
            self._last_result = self._service.apply(watts)
            return self._status()
        return self._run(action)

    def restore(self) -> dict[str, object]:
        self.stop_auto()
        def action():
            before = self._status()
            if not before["restore_available"]:
                return before
            if not self._lease.acquire():
                return unavailable_status("tdp.writer_busy")
            was_enabled = self._enabled
            try:
                self._enabled = True
                self._last_result = self._service.restore()
            finally:
                self._enabled = was_enabled
                if not was_enabled:
                    self._lease.close()
            return self._status()
        return self._run(action)

    def close(self) -> None:
        """Stop admissions immediately; retain recovery state without unload writes.

        Do not wait for a slow D-Bus operation inside Decky's unload deadline.
        An in-flight request retains the process lease until it returns or exits.
        The next loaded panel can explicitly restore a verified active record.
        """
        self._closing.set()
        self.stop_auto()
        if self._lock.acquire(blocking=False):
            self._release_operation()
