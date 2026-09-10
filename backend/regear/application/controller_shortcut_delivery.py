"""Debounced adapter from verified controller evidence to one logical-action sink.

This is deliberately not an input listener and does not execute a transition.
A future platform adapter owns physical-device recognition and supplies one
opaque event ID only after it has verified the event source. This relay ensures
that a held chord reaches the canonical logical-action entry point at most once.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Protocol

from ..domain.controller_shortcuts import (
    ControllerInputEvidence,
    evaluate_controller_shortcut,
)
from ..domain.logical_actions import LogicalActionRequest


class LogicalActionSinkPort(Protocol):
    """The sole future bridge to Re-Gear's canonical request facade."""

    def submit(self, request: LogicalActionRequest) -> bool: ...


@dataclass(frozen=True, slots=True)
class ControllerShortcutDeliveryResult:
    routed: bool
    reason: str


class ControllerShortcutDeliveryAdapter:
    """Bound exact controller events before sending an existing logical action."""

    def __init__(self, sink: LogicalActionSinkPort, *, max_seen_events: int = 32) -> None:
        if max_seen_events <= 0 or max_seen_events > 128:
            raise ValueError("controller shortcut event bound is invalid")
        self._sink = sink
        self._max_seen_events = max_seen_events
        self._seen: deque[str] = deque()
        self._seen_set: set[str] = set()
        self._lock = threading.Lock()

    def deliver(self, evidence: ControllerInputEvidence) -> ControllerShortcutDeliveryResult:
        """Evaluate once, consume a matched event, then submit only the request.

        A sink exception or rejection never causes a retry. The caller must
        obtain a new verified physical event and fresh Re-Gear generation instead of
        replaying a possibly already-delivered held chord.
        """
        decision = evaluate_controller_shortcut(evidence)
        if not decision.matched:
            return ControllerShortcutDeliveryResult(False, decision.reason)
        assert decision.request is not None
        with self._lock:
            if evidence.event_id in self._seen_set:
                return ControllerShortcutDeliveryResult(
                    False, "controller_shortcut.event_replayed"
                )
            self._remember(evidence.event_id)
            try:
                accepted = self._sink.submit(decision.request) is True
            except Exception:
                accepted = False
            return ControllerShortcutDeliveryResult(
                accepted,
                (
                    "controller_shortcut.routed"
                    if accepted
                    else "controller_shortcut.canonical_sink_unavailable"
                ),
            )

    def _remember(self, event_id: str) -> None:
        self._seen.append(event_id)
        self._seen_set.add(event_id)
        if len(self._seen) > self._max_seen_events:
            self._seen_set.discard(self._seen.popleft())
