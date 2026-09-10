from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.transition_runtime import (  # noqa: E402
    BoundedDeadlineWaiter,
    SnapshotTransitionObservationAdapter,
)
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.ports.transition import MechanismResult  # noqa: E402


class Discovery:
    def __init__(self, value):
        self.value = value

    def collect_snapshot(self):
        return self.value


class TransitionRuntimeAdapterTests(unittest.TestCase):
    def test_generation_ignores_timestamp_but_binds_semantic_evidence(self):
        value = json.loads(
            (ROOT / "tests" / "fixtures" / "portable.json").read_text()
        )
        first = snapshot_from_dict(value)
        adapter = SnapshotTransitionObservationAdapter(Discovery(first))
        one = adapter.observe()
        two = adapter.observe()
        self.assertEqual(one.generation, two.generation)
        value["observed_at"] = "2026-08-31T12:00:01Z"
        timestamp_only = SnapshotTransitionObservationAdapter(
            Discovery(snapshot_from_dict(value))
        ).observe()
        self.assertEqual(one.generation, timestamp_only.generation)
        self.assertNotEqual(one.sample_id, timestamp_only.sample_id)
        value["game_state"] = "running"
        changed = SnapshotTransitionObservationAdapter(
            Discovery(snapshot_from_dict(value))
        ).observe()
        self.assertNotEqual(one.generation, changed.generation)
        self.assertEqual(len(one.generation), 64)

    def test_waiter_refuses_unbounded_or_nonpositive_polling(self):
        for value in (0, -1, 251):
            with self.subTest(value=value), self.assertRaises(ValueError):
                BoundedDeadlineWaiter.wait_ms(value)

    def test_mechanism_result_is_categorical(self):
        with self.assertRaisesRegex(ValueError, "categorical"):
            MechanismResult(False, "private detail / path")


if __name__ == "__main__":
    unittest.main()
