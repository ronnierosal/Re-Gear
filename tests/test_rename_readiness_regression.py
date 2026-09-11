"""Keep attachment observations distinct from complete connection readiness."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.application.attach_readiness import (
    AttachReadinessStage,
    AttachReadinessStatus,
)
from regear.application.connection_readiness import (
    ConnectionReadinessLifecycle,
    ConnectionReadinessObservation,
    ConnectionReadinessStage,
)
from regear.domain.models import GameState
from test_main_process_delivery import load_main_module


class RenameReadinessRegressionTests(unittest.TestCase):
    def test_stale_session_never_reports_full_connection_ready(self):
        now = [0.0]
        lifecycle = ConnectionReadinessLifecycle(lambda: now[0])

        def observe(index, enumerated):
            return lifecycle.update(ConnectionReadinessObservation(
                sample_id=str(index), transport_identity="transport-a",
                transport_present=True, g1_identity="gpu-a" if enumerated else "",
                pci_complete=enumerated, driver_ready=enumerated,
                link_up=enumerated, hdmi_ready=enumerated, audio_ready=enumerated,
                session_ready=False, game_state=GameState.IDLE,
            ))

        observe(0, False)
        now[0] = 120.4
        self.assertEqual(observe(1, False).stage, ConnectionReadinessStage.TIMED_OUT)
        now[0] = 148.0
        self.assertEqual(observe(2, True).stage, ConnectionReadinessStage.STABILIZING)
        for index in range(3, 8):
            now[0] += 1
            self.assertEqual(observe(index, True).stage,
                             ConnectionReadinessStage.WAITING_FOR_SESSION)
        now[0] = 268.0
        self.assertEqual(observe(8, True).stage, ConnectionReadinessStage.TIMED_OUT)

    def test_attach_ready_event_is_not_full_connection_ready_event(self):
        module = load_main_module()
        events = []
        recorder = SimpleNamespace(_append_journey_event=lambda **event: events.append(event))
        module.Plugin._record_attach_readiness_status(recorder, AttachReadinessStatus(
            AttachReadinessStage.READY_IDLE, "attach.ready_idle", 1000,
        ))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["code"], "attach.ready_idle")
        self.assertNotEqual(events[0]["component"], "connection")


if __name__ == "__main__":
    unittest.main()
