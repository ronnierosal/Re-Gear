from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.canonical_sleep import (  # noqa: E402
    CanonicalSleepWorkflowService,
)
from regear.application.canonical_sleep_facade import (  # noqa: E402
    CanonicalSleepRequestFacade,
)
from regear.delivery.canonical_sleep import (  # noqa: E402
    result_to_payload,
    status_to_payload,
)
from regear.domain.control_plane import (  # noqa: E402
    PlacementState,
    RequestSource,
)
from regear.domain.game_compatibility import GameSaveCapability  # noqa: E402
from regear.domain.models import EgpuPresence, GameState  # noqa: E402
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.domain.sleep_workflow import (  # noqa: E402
    SleepFlowStage,
    SleepWorkflowContext,
)
from regear.ports.sleep_workflow import SleepWorkflowObservation  # noqa: E402
from regear.profiles.ally_x import CAPABILITIES as ALLY_X  # noqa: E402
from regear.profiles.gpd_g1 import CAPABILITIES as GPD_G1  # noqa: E402
from regear.domain.control_plane import compose_capabilities  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def readiness():
    value = json.loads((FIXTURES / "portable.json").read_text(encoding="utf-8"))
    snapshot = snapshot_from_dict(value)
    return dataclasses.replace(
        snapshot.disconnect_readiness,
        applicable=True,
        scan_complete=True,
        ready=True,
        egpu_stable_id="gpd-g1:0123456789abcdef",
    )


def context(*, game_state=GameState.IDLE):
    return SleepWorkflowContext(
        EgpuPresence.PRESENT,
        True,
        compose_capabilities(ALLY_X, GPD_G1),
        game_state,
        GameSaveCapability.UNTESTED,
        readiness(),
        PlacementState.DOCKED_EGPU,
    )


class Observations:
    def __init__(self, value):
        self.value = value
        self.sample = 0
        self.available = True

    def observe(self):
        if not self.available:
            raise OSError("unavailable")
        self.sample += 1
        return SleepWorkflowObservation(
            "semantic-generation",
            f"sample-{self.sample}",
            self.value,
            "gpd-g1:0123456789abcdef",
        )


class Clock:
    def now_ms(self):
        return 100


class JournalStore:
    def __init__(self):
        self.current = None

    def load_current(self):
        return self.current

    def save(self, journal):
        self.current = journal

    def clear_terminal(self, operation_id):
        if self.current is None or self.current.operation_id != operation_id:
            raise ValueError("operation changed")
        self.current = None


def facade(
    observations,
    *,
    request_id_factory=lambda: "sleep-request-facade-0001",
):
    store = JournalStore()
    sleep = CanonicalSleepWorkflowService(
        observations=observations,
        clock=Clock(),
        journal_store=store,
        occurred_at=lambda: "test",
        operation_id_factory=lambda: "sleep-operation-facade-0001",
    )
    value = CanonicalSleepRequestFacade(
        sleep=sleep,
        observations=observations,
        request_id_factory=request_id_factory,
        requested_at=lambda: "test",
    )
    return value, store


class CanonicalSleepFacadeTests(unittest.TestCase):
    def test_backend_owns_generation_request_and_shutdown_first_result(self):
        value, store = facade(Observations(context()))
        result = value.request(RequestSource.STEAM_MENU)
        self.assertTrue(result.accepted)
        self.assertEqual(result.flow.stage, SleepFlowStage.SHUTDOWN_REQUIRED)
        self.assertTrue(store.current.terminal)
        payload = result_to_payload(result)
        self.assertNotIn("request_id", payload)
        self.assertNotIn("generation", payload)
        self.assertEqual(payload["operation_id"], result.operation_id)
        self.assertIn("shutdown_before_disconnect", payload["directives"])

    def test_exact_operation_controls_game_consent(self):
        observations = Observations(context(game_state=GameState.RUNNING))
        value, store = facade(observations)
        started = value.request(RequestSource.PHYSICAL_BUTTON)
        wrong = value.respond_to_game_consent(
            "sleep-operation-facade-wrong", granted=True
        )
        self.assertEqual(wrong.code, "sleep.operation_changed")
        self.assertFalse(store.current.terminal)

        granted = value.respond_to_game_consent(
            started.operation_id, granted=True
        )
        self.assertTrue(granted.accepted)
        self.assertEqual(granted.flow.stage, SleepFlowStage.CLOSING_GAME)

    def test_consent_denial_and_exact_acknowledgement(self):
        value, store = facade(Observations(context(game_state=GameState.RUNNING)))
        started = value.request(RequestSource.STEAM_MENU)
        denied = value.respond_to_game_consent(
            started.operation_id, granted=False
        )
        self.assertEqual(denied.flow.stage, SleepFlowStage.CANCELLED)
        status = value.status()
        payload = status_to_payload(status)
        self.assertNotIn("request_id", payload)
        self.assertTrue(payload["acknowledgement_required"])
        self.assertFalse(value.acknowledge("sleep-operation-facade-wrong"))
        self.assertTrue(value.acknowledge(started.operation_id))
        self.assertIsNone(store.current)

    def test_unsupported_source_or_missing_observation_creates_no_journal(self):
        observations = Observations(context())
        value, store = facade(observations)
        unsupported = value.request(RequestSource.AUTOMATIC)
        self.assertEqual(unsupported.code, "sleep.source_unsupported")
        self.assertIsNone(store.current)

        observations.available = False
        unavailable = value.request(RequestSource.STEAM_MENU)
        self.assertEqual(unavailable.code, "sleep.observation_unavailable")
        self.assertTrue(unavailable.action_required)
        self.assertIsNone(store.current)

    def test_invalid_backend_request_identity_fails_without_journal(self):
        observations = Observations(context())
        value, store = facade(
            observations, request_id_factory=lambda: "../invalid"
        )
        result = value.request(RequestSource.STEAM_MENU)
        self.assertEqual(result.code, "sleep.request_identity_invalid")
        self.assertIsNone(store.current)


if __name__ == "__main__":
    unittest.main()
