"""On-demand app-bound frame collection and sampled estimates; no timer/writer."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

from ..adapters.steamos.gamescope_performance import GamescopePerformanceReader
from ..adapters.steamos.gamescope_performance_target import PerformanceTargetResolution
from ..domain.frame_time_window import FrameTimeSample, FrameWindowPolicy, FrameWindowState, update_frame_window


@dataclass(frozen=True, slots=True)
class FrameCollection:
    code: str
    context_key: str = ""
    sampled_fps: float | None = None
    newest_received_at_ms: int | None = None
    sample_count: int = 0
    span_ms: int = 0
    collection_cost_ms: int | None = None


class GameFrameCollector:
    def __init__(self, *, resolve: Callable[[], PerformanceTargetResolution],
                 reader: GamescopePerformanceReader | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 policy: FrameWindowPolicy = FrameWindowPolicy()):
        self._resolve = resolve
        self._reader = reader or GamescopePerformanceReader(clock=clock)
        self._clock = clock
        self._policy = policy
        self._state = FrameWindowState()
        self._lock = threading.Lock()

    def _fail(self, code: str) -> FrameCollection:
        self._state = FrameWindowState()
        return FrameCollection(code)

    def reset(self) -> None:
        """Discard samples after a change in the surrounding power context."""
        with self._lock:
            self._state = FrameWindowState()

    def collect(self) -> FrameCollection:
        if not self._lock.acquire(blocking=False):
            return FrameCollection("frames.busy")
        try:
            started = self._clock()
            before = self._resolve()
            if not before.ok:
                return self._fail("frames.target_unavailable")
            reading = self._reader.observe(before.target)
            if reading.code != "performance.observed":
                return self._fail("frames.unavailable")
            after = self._resolve()
            if not after.ok or after.target != before.target or reading.context_key != before.target.context_key:
                return self._fail("frames.context_changed")
            finished = self._clock()
            if not math.isfinite(started) or not math.isfinite(finished) or started < 0 or finished < started:
                return self._fail("frames.clock_invalid")
            sample = FrameTimeSample(reading.context_key, reading.received_at_ms, reading.frame_time_ns)
            window = update_frame_window(self._policy, self._state, sample, now_ms=int(finished * 1000))
            self._state = window.state
            samples = self._state.samples
            span = samples[-1].received_at_ms - samples[0].received_at_ms if samples else 0
            return FrameCollection(window.code, self._state.context_key, window.estimated_fps,
                                   window.newest_received_at_ms, len(samples), span,
                                   math.ceil((finished - started) * 1000))
        except Exception:
            return self._fail("frames.unavailable")
        finally:
            self._lock.release()
