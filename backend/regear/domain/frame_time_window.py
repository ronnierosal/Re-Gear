"""Bounded sampled presented-frame FPS estimates, not a complete frame trace."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FrameTimeSample:
    context_key: str
    received_at_ms: int
    frame_time_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.context_key, str) or not 1 <= len(self.context_key) <= 256:
            raise ValueError("Frame context is invalid")
        if type(self.received_at_ms) is not int or self.received_at_ms < 0:
            raise ValueError("Frame receipt time is invalid")
        if type(self.frame_time_ns) is not int or not 0 < self.frame_time_ns <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("Frame interval is invalid")


@dataclass(frozen=True, slots=True)
class FrameWindowPolicy:
    minimum_samples: int = 5
    maximum_samples: int = 10
    minimum_span_ms: int = 4_000
    window_ms: int = 10_000
    maximum_gap_ms: int = 2_000
    maximum_sample_age_ms: int = 2_000

    def __post_init__(self) -> None:
        values = (self.minimum_samples, self.maximum_samples, self.minimum_span_ms,
                  self.window_ms, self.maximum_gap_ms, self.maximum_sample_age_ms)
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("Frame window bounds are invalid")
        if not 2 <= self.minimum_samples <= self.maximum_samples <= 60:
            raise ValueError("Frame window sample count is invalid")
        if (self.minimum_span_ms > self.window_ms or self.maximum_gap_ms > self.window_ms
                or self.minimum_span_ms > (self.maximum_samples - 1) * self.maximum_gap_ms):
            raise ValueError("Frame window timing is inconsistent")


@dataclass(frozen=True, slots=True)
class FrameWindowState:
    context_key: str = ""
    last_sample_ms: int = -1
    samples: tuple[FrameTimeSample, ...] = ()


@dataclass(frozen=True, slots=True)
class FrameWindowResult:
    state: FrameWindowState
    code: str
    estimated_fps: float | None = None
    newest_received_at_ms: int | None = None


def update_frame_window(policy: FrameWindowPolicy, state: FrameWindowState,
                        sample: FrameTimeSample | None, *, now_ms: int) -> FrameWindowResult:
    """Require independent fresh observations spanning time before an estimate.

    Unavailable input invalidates history. Duplicate timestamps break the window
    while retaining its watermark; one cached sample cannot rebuild a quorum.
    FPS is sample-count / sum(frame durations), not mean instantaneous FPS.
    """
    if sample is None:
        return FrameWindowResult(FrameWindowState(), "frames.unavailable")
    if type(now_ms) is not int or not 0 <= now_ms - sample.received_at_ms <= policy.maximum_sample_age_ms:
        return FrameWindowResult(FrameWindowState(), "frames.stale")
    if state.context_key != sample.context_key:
        samples = (sample,)
    elif sample.received_at_ms <= state.last_sample_ms:
        return FrameWindowResult(FrameWindowState(state.context_key, state.last_sample_ms), "frames.repeated")
    elif sample.received_at_ms - state.last_sample_ms > policy.maximum_gap_ms:
        samples = (sample,)
    else:
        samples = tuple(item for item in state.samples
                        if item.context_key == sample.context_key and
                        now_ms - policy.window_ms <= item.received_at_ms < sample.received_at_ms)
        samples = (samples + (sample,))[-policy.maximum_samples:]
    next_state = FrameWindowState(sample.context_key, sample.received_at_ms, samples)
    if len(samples) < policy.minimum_samples or samples[-1].received_at_ms - samples[0].received_at_ms < policy.minimum_span_ms:
        return FrameWindowResult(next_state, "frames.warming")
    fps = len(samples) * 1_000_000_000 / sum(item.frame_time_ns for item in samples)
    return FrameWindowResult(next_state, "frames.estimated", fps, sample.received_at_ms)
