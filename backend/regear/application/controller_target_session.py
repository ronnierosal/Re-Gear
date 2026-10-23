"""Unconstructed session prototype. All evidence, clock and writers are injected."""

from contextlib import contextmanager
from threading import Lock
from typing import Callable

from ..domain.controller_target_session import (
    Frame, Phase, Request, TargetType, admitted, catalogue, replacement, timestamp,
)
from ..ports.controller_targets import Dispatch, TargetReader, TargetWriter


class TargetSession:
    def __init__(self, reader: TargetReader, writer: TargetWriter,
                 clock: Callable[[], float], reviewed: tuple[TargetType, ...]):
        catalogue(reviewed)
        self._reader, self._writer, self._clock = reader, writer, clock
        self._reviewed = reviewed
        self._lock = Lock()
        self._selection = None
        self._pending = None
        self._issued = None
        self._original = None
        self._phase = Phase.STAGED
        self._ambiguous = False

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def rollback_retained(self) -> bool:
        return self._original is not None

    @contextmanager
    def _exclusive(self):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("session busy")
        try:
            yield
        finally:
            self._lock.release()

    def _now(self):
        return timestamp(self._clock())

    def stage(self, composite: str, target: str) -> None:
        """Local selection only; neither selection nor provider access grants authority."""
        with self._exclusive():
            if self._phase is not Phase.STAGED or self._original is not None:
                raise ValueError("session already submitted or closed")
            if type(composite) is not str or not composite or type(target) is not str:
                raise ValueError("explicit selection required")
            self._selection = composite, target
            self._pending = None

    def _read(self, start: float, deadline: float) -> Frame:
        frame = self._reader.read(deadline)
        now = self._now()
        if not start <= now < deadline:
            raise ValueError("expired or reversed operation clock")
        admitted(frame, now, self._reviewed)
        return frame

    def prepare_apply(self) -> Request:
        with self._exclusive():
            if self._phase is not Phase.STAGED or self._selection is None:
                raise ValueError("stage before applying")
            start = self._now()
            frame = self._read(start, start + 10)
            composite, target = self._selection
            if frame.composite != composite or target not in admitted(frame, self._now(), self._reviewed):
                raise ValueError("selection is not verified and supported")
            kinds = catalogue(frame.supported)
            original_gamepad = next(t for t in frame.targets if kinds[t])
            if original_gamepad not in admitted(frame, self._now(), self._reviewed):
                raise ValueError("original gamepad is not a reviewed restorable choice")
            desired = replacement(frame, target)
            if desired == frame.targets:
                raise ValueError("selected target already observed")
            self._pending = Request(frame, frame.targets, desired, start, start + 10)
            return self._pending

    def _prepare_restore(self) -> Request:
        if (self._phase not in (Phase.REQUESTED, Phase.EFFECTIVE)
                or self._original is None or self._issued is None or self._ambiguous):
            raise ValueError("no unambiguous restorable transaction")
        start = self._now()
        frame = self._read(start, start + 10)
        if (frame.binding != self._issued.frame.binding or frame.targets != self._issued.desired
                or frame.supported != self._issued.frame.supported
                or frame.compatible != self._issued.frame.compatible):
            raise ValueError("identity, authority or issued state changed")
        # Restoration may use only the captured original, never newly inferred IDs.
        self._pending = Request(frame, self._original, self._original, start, start + 10, True)
        return self._pending

    def prepare_restore(self) -> Request:
        with self._exclusive():
            try:
                return self._prepare_restore()
            except Exception:
                if self._original is not None:
                    self._phase = Phase.RECOVERY_REQUIRED
                raise

    def _dispatch(self, request: Request) -> Phase:
        if request is not self._pending or request is None:
            raise ValueError("stale, foreign or consumed request")
        self._pending = None  # consume before callbacks, even if the fresh check fails
        try:
            frame = self._read(request.started, request.deadline)
            if (frame.binding != request.frame.binding or frame.targets != request.frame.targets
                    or frame.supported != request.frame.supported
                    or frame.compatible != request.frame.compatible):
                raise ValueError("request evidence changed")
            if not request.restoring:
                target = self._selection[1]
                if (target not in admitted(frame, self._now(), self._reviewed)
                        or replacement(frame, target) != request.desired):
                    raise ValueError("selected target is no longer admissible")
            elif self._ambiguous or self._issued is None or frame.targets != self._issued.desired:
                raise ValueError("restoration state changed")
        except Exception:
            if self._original is not None:
                self._phase = Phase.RECOVERY_REQUIRED
            raise
        self._original = request.original
        self._issued = request
        # Record rollback before crossing the injected submission boundary.
        try:
            result = self._writer.set_targets(request)
            now = self._now()
            if not request.started <= now < request.deadline or type(result) is not Dispatch:
                raise ValueError("ambiguous or late writer completion")
        except Exception:
            self._ambiguous = True
            self._phase = Phase.RECOVERY_REQUIRED
            return self._phase
        if result is Dispatch.REFUSED:
            if request.restoring:
                self._phase = Phase.RECOVERY_REQUIRED
            else:
                self._original = self._issued = None
                self._phase = Phase.STAGED
        else:
            self._phase = Phase.RESTORE_REQUESTED if request.restoring else Phase.REQUESTED
        return self._phase

    def dispatch(self, request: Request) -> Phase:
        with self._exclusive():
            return self._dispatch(request)

    def verify(self) -> Phase:
        """A separate fresh read, never the setter result, proves effective state."""
        with self._exclusive():
            if self._phase not in (Phase.REQUESTED, Phase.RESTORE_REQUESTED):
                raise ValueError("no submitted request awaiting readback")
            try:
                start = self._now()
                frame = self._read(start, start + 10)
                if (frame.binding != self._issued.frame.binding or frame.targets != self._issued.desired
                        or frame.supported != self._issued.frame.supported
                        or frame.compatible != self._issued.frame.compatible):
                    raise ValueError("readback mismatch")
            except Exception:
                self._phase = Phase.RECOVERY_REQUIRED
                return self._phase
            if self._issued.restoring:
                self._phase = Phase.RESTORED
                self._original = self._issued = None
            else:
                self._phase = Phase.EFFECTIVE
            return self._phase

    def close(self) -> Phase:
        """B/close/unload fixture hook: one guarded attempt, no retry or persistence."""
        with self._exclusive():
            self._pending = None
            if self._original is None:
                self._phase = Phase.CLOSED
                return self._phase
            try:
                return self._dispatch(self._prepare_restore())
            except Exception:
                self._phase = Phase.RECOVERY_REQUIRED
                return self._phase
