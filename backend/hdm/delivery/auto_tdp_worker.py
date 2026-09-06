"""One cancellable Auto TDP worker; no startup activation or implicit restore.

The owning delivery runtime must retain its writer lease until running is false.
After stop has drained, it may explicitly restore through the shared service.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ..application.auto_tdp_session import AutoTdpSession, AutoTdpSessionResult
from ..domain.auto_tdp import AutoTdpPolicy


@dataclass(frozen=True, slots=True)
class AutoTdpWorkerStatus:
    running: bool
    stopping: bool
    last_result: AutoTdpSessionResult | None


class AutoTdpWorker:
    def __init__(self, session: AutoTdpSession, *, interval_ms: int):
        if type(interval_ms) is not int or not 1000 <= interval_ms <= 60_000:
            raise ValueError("Auto TDP worker interval is invalid")
        self._session = session
        self._interval = interval_ms / 1000
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: AutoTdpSessionResult | None = None

    def status(self) -> AutoTdpWorkerStatus:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            return AutoTdpWorkerStatus(running, running and self._stop.is_set(), self._last)

    def start(self, policy: AutoTdpPolicy) -> AutoTdpWorkerStatus:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return AutoTdpWorkerStatus(True, self._stop.is_set(), self._last)
            self._last = self._session.start(policy)
            if not self._last.enabled:
                return AutoTdpWorkerStatus(False, False, self._last)
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, name="hdm-auto-tdp", daemon=True)
            try:
                self._thread.start()
            except Exception:
                self._session.stop()
                self._last = AutoTdpSessionResult("auto_tdp.worker_unavailable", False)
                self._thread = None
                return AutoTdpWorkerStatus(False, False, self._last)
            return AutoTdpWorkerStatus(True, False, self._last)

    def stop(self) -> AutoTdpWorkerStatus:
        with self._lock:
            self._session.stop()  # Revoke late dispatch admission immediately.
            self._stop.set()      # Interrupt cadence wait without waiting on I/O.
            running = self._thread is not None and self._thread.is_alive()
            return AutoTdpWorkerStatus(running, running, self._last)

    def wait_stopped(self, timeout_seconds: float = 0) -> bool:
        if type(timeout_seconds) not in (int, float) or not 0 <= timeout_seconds <= 5:
            raise ValueError("Auto TDP drain wait is invalid")
        with self._lock:
            thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        thread.join(timeout_seconds)
        with self._lock:
            # A concurrent explicit restart can replace the completed thread.
            return self._thread is None or not self._thread.is_alive()

    def _run(self):
        try:
            while not self._stop.is_set():
                result = self._session.tick()
                with self._lock:
                    self._last = result
                if not result.enabled:
                    break
                # Delay after completion: no catch-up bursts after slow reads.
                if self._stop.wait(self._interval):
                    break
        except Exception:
            with self._lock:
                self._last = AutoTdpSessionResult("auto_tdp.worker_unavailable", False)
        finally:
            self._session.stop()
