from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.whole_dock_lifecycle_status import (  # noqa: E402
    WholeDockLifecycleState,
    classify_whole_dock_lifecycle,
)


class WholeDockLifecycleStatusTests(unittest.TestCase):
    def classify(self, stage, *, readable=True, external=False):
        return classify_whole_dock_lifecycle(
            claim_stage=stage,
            claim_readable=readable,
            external_gpu_present=external,
        )

    def test_missing_claim_is_ordinary_none_state(self):
        status = self.classify(None)
        self.assertEqual(status.state, WholeDockLifecycleState.NONE)
        self.assertEqual(status.code, "whole_dock.no_claim")

    def test_unreadable_claim_fails_closed_without_exposing_details(self):
        status = self.classify("software_down", readable=False)
        self.assertEqual(status.state, WholeDockLifecycleState.UNKNOWN)
        self.assertEqual(
            status.to_payload(),
            {
                "schema_version": 1,
                "state": "unknown",
                "code": "whole_dock.claim_unreadable",
            },
        )

    def test_teardown_stages_are_in_progress(self):
        for stage in (
            "claimed",
            "release_intent",
            "gpu_removed",
            "prepared",
            "usb_remove_intent",
            "usb_removed",
            "tunnel_remove_intent",
        ):
            with self.subTest(stage=stage):
                self.assertEqual(
                    self.classify(stage).state,
                    WholeDockLifecycleState.IN_PROGRESS,
                )

    def test_software_down_without_external_gpu_is_reported(self):
        status = self.classify("software_down")
        self.assertEqual(status.state, WholeDockLifecycleState.SOFTWARE_DOWN)
        self.assertEqual(status.code, "whole_dock.software_down")

    def test_software_down_with_external_gpu_is_conflict(self):
        status = self.classify("software_down", external=True)
        self.assertEqual(status.state, WholeDockLifecycleState.CONFLICT)
        self.assertEqual(status.code, "whole_dock.software_down_gpu_present")

    def test_reconnect_intent_never_reads_as_software_down(self):
        self.assertEqual(
            self.classify("reauthorize_intent").state,
            WholeDockLifecycleState.RECONNECTING,
        )

    def test_reconnected_requires_external_gpu_observation(self):
        self.assertEqual(
            self.classify("software_reconnected", external=True).state,
            WholeDockLifecycleState.RECONNECTED,
        )
        self.assertEqual(
            self.classify("software_reconnected").state,
            WholeDockLifecycleState.CONFLICT,
        )

    def test_unknown_stage_fails_closed(self):
        status = self.classify("future_stage")
        self.assertEqual(status.state, WholeDockLifecycleState.UNKNOWN)
        self.assertEqual(status.code, "whole_dock.claim_stage_unknown")


if __name__ == "__main__":
    unittest.main()
