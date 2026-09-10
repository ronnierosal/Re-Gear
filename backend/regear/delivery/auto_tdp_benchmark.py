"""Explicit bounded measurement of collection plus late revalidation; no writer.

Use a separate, idle collector from the session factory. Results describe this
run only, not a certified profile, persistent permission or automatic activation.
Wall time includes I/O waiting; it is not a CPU utilization measurement.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable, Protocol

from ..application.auto_tdp_session import AutoTdpEvidence, AutoTdpLiveContext


class BenchmarkEvidence(Protocol):
    def reset(self) -> None: ...
    def collect(self) -> AutoTdpEvidence | None: ...
    def revalidate(self) -> AutoTdpLiveContext | None: ...


@dataclass(frozen=True, slots=True)
class AutoTdpBenchmarkResult:
    code: str
    attempts: int
    usable_samples: int
    consecutive_samples: int
    maximum_collection_and_revalidation_ms: int | None
    elapsed_ms: int
    interval_ms: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def benchmark_auto_tdp(evidence: BenchmarkEvidence, *,
                       cancel: threading.Event,
                       interval_ms: int = 1000, attempts: int = 12,
                       maximum_sample_age_ms: int = 2000,
                       clock: Callable[[], float] = time.monotonic,
                       wait: Callable[[float], bool] | None = None) -> AutoTdpBenchmarkResult:
    """Measure at most 30 iterations/60 seconds, checking cancellation between reads.

An already-running bounded reader completes before cancellation takes effect.
At least five consecutive usable estimates in one context must finish the run.
Cadence waits follow completion, matching the real worker. Worst cost includes
warm-up and unavailable samples, so slow failures cannot improve the result.
"""
    if type(interval_ms) is not int or not 1000 <= interval_ms <= 2000:
        raise ValueError("Benchmark interval must be between one and two seconds")
    if type(attempts) is not int or not 10 <= attempts <= 30:
        raise ValueError("Benchmark requires 10 to 30 attempts")
    if type(maximum_sample_age_ms) is not int or maximum_sample_age_ms <= 0:
        raise ValueError("Benchmark sample freshness must be explicit and positive")
    waiting = wait or cancel.wait
    completed = usable = consecutive = 0
    maximum = None
    context = None
    sample_watermark = -1
    started = None
    last = None

    def now():
        nonlocal last
        value = clock()
        if (type(value) not in (int, float) or not math.isfinite(value)
                or value < 0 or (last is not None and value < last)):
            raise ValueError("Invalid benchmark clock")
        last = value
        return value

    def result(code):
        elapsed = 0 if started is None or last is None else math.ceil((last - started) * 1000)
        return AutoTdpBenchmarkResult(code, completed, usable, consecutive, maximum, elapsed, interval_ms)

    try:
        started = now()
        if cancel.is_set():
            return result("auto_tdp.benchmark_cancelled")
        evidence.reset()
        for index in range(attempts):
            if cancel.is_set():
                return result("auto_tdp.benchmark_cancelled")
            before = now()
            if before - started >= 60:
                return result("auto_tdp.benchmark_time_limit")
            sample = evidence.collect()
            if cancel.is_set():
                now()
                return result("auto_tdp.benchmark_cancelled")
            live = evidence.revalidate()
            after = now()
            completed += 1
            cost = max(1, math.ceil((after - before) * 1000))
            maximum = max(maximum or 0, cost)
            if cancel.is_set():
                return result("auto_tdp.benchmark_cancelled")
            if after - started >= 60:
                return result("auto_tdp.benchmark_time_limit")
            if not isinstance(live, AutoTdpLiveContext):
                return result("auto_tdp.benchmark_context_unavailable")
            if context is not None and live != context:
                return result("auto_tdp.benchmark_context_changed")
            context = live
            if (isinstance(sample, AutoTdpEvidence)
                    and sample.observation.context_key == live.workload_key
                    and sample.reading == live.reading
                    and type(sample.observation.sampled_at_ms) is int
                    and sample.observation.sampled_at_ms > sample_watermark
                    and 0 <= int(after * 1000) - sample.observation.sampled_at_ms <= maximum_sample_age_ms):
                usable += 1
                consecutive += 1
                sample_watermark = sample.observation.sampled_at_ms
            else:
                consecutive = 0
            if index + 1 < attempts and waiting(interval_ms / 1000):
                now()
                return result("auto_tdp.benchmark_cancelled")
        if consecutive < 5:
            return result("auto_tdp.benchmark_samples_insufficient")
        return result("auto_tdp.benchmark_within_budget" if maximum * 100 <= interval_ms
                      else "auto_tdp.benchmark_budget_exceeded")
    except Exception:
        return result("auto_tdp.benchmark_unavailable")
