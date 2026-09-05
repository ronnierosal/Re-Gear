from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.application.controller_shortcut_delivery import (  # noqa: E402
    ControllerShortcutDeliveryAdapter,
)
from hdm.domain.controller_shortcuts import (  # noqa: E402
    ControllerButton,
    ControllerInputEvidence,
)
from hdm.domain.logical_actions import LogicalAction  # noqa: E402


class Sink:
    def __init__(self, result=True, *, fail=False):
        self.result = result
        self.fail = fail
        self.requests = []

    def submit(self, request):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("fixture failure")
        return self.result


def evidence(*, event_id="controller-event-0001", verified=True, held_ms=3_000):
    return ControllerInputEvidence(
        verified,
        frozenset({ControllerButton.VIEW, ControllerButton.Y}),
        held_ms,
        "2026-08-31T12:00:00Z",
        "generation-1",
        event_id,
    )


class ControllerShortcutDeliveryTests(unittest.TestCase):
    def test_matched_chord_reaches_the_one_logical_action_sink(self):
        sink = Sink()
        result = ControllerShortcutDeliveryAdapter(sink).deliver(evidence())

        self.assertTrue(result.routed)
        self.assertEqual(result.reason, "controller_shortcut.routed")
        self.assertEqual(len(sink.requests), 1)
        self.assertEqual(sink.requests[0].action, LogicalAction.SAFE_UNDOCK)
        self.assertEqual(sink.requests[0].expected_generation, "generation-1")

    def test_event_replay_never_dispatches_a_second_transition_request(self):
        sink = Sink()
        adapter = ControllerShortcutDeliveryAdapter(sink)
        self.assertTrue(adapter.deliver(evidence()).routed)

        replay = adapter.deliver(evidence())

        self.assertFalse(replay.routed)
        self.assertEqual(replay.reason, "controller_shortcut.event_replayed")
        self.assertEqual(len(sink.requests), 1)

    def test_unverified_or_short_input_never_consumes_or_calls_the_sink(self):
        sink = Sink()
        adapter = ControllerShortcutDeliveryAdapter(sink)
        for value, code in (
            (evidence(verified=False), "controller_shortcut.input_unverified"),
            (evidence(held_ms=2_999), "controller_shortcut.hold_incomplete"),
        ):
            with self.subTest(code=code):
                result = adapter.deliver(value)
                self.assertFalse(result.routed)
                self.assertEqual(result.reason, code)
        self.assertEqual(sink.requests, [])

    def test_sink_failure_consumes_the_event_and_never_retries_it(self):
        sink = Sink(fail=True)
        adapter = ControllerShortcutDeliveryAdapter(sink)

        failed = adapter.deliver(evidence())
        replay = adapter.deliver(evidence())

        self.assertFalse(failed.routed)
        self.assertEqual(failed.reason, "controller_shortcut.canonical_sink_unavailable")
        self.assertEqual(replay.reason, "controller_shortcut.event_replayed")
        self.assertEqual(len(sink.requests), 1)

    def test_event_memory_is_bounded(self):
        sink = Sink()
        adapter = ControllerShortcutDeliveryAdapter(sink, max_seen_events=1)
        adapter.deliver(evidence(event_id="controller-event-0001"))
        adapter.deliver(evidence(event_id="controller-event-0002"))
        replay_after_eviction = adapter.deliver(evidence(event_id="controller-event-0001"))

        self.assertTrue(replay_after_eviction.routed)
        self.assertEqual(len(sink.requests), 3)


if __name__ == "__main__":
    unittest.main()
