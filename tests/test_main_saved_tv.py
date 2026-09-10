"""The call sites that make a saved TV reach the runtime.

The decision, the record and the bounded search already exist and are covered
on their own. What is tested here is the wiring: that a dock which actually
succeeded is the only thing that writes a profile, that waiting for a TV that
is not there reports *waiting* rather than a failure, that the budget is spent
only on real looks and re-armed by the next dock, and that the identity the
record keeps never reaches the plugin payload.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from tests.test_automatic_dock import current  # noqa: E402
from tests.test_main_process_delivery import load_main_module  # noqa: E402
from hdm.application.connection_readiness import (  # noqa: E402
    ConnectionReadinessStage,
    ConnectionReadinessStatus,
)
from hdm.application.presentation_completion import PresentationCompletion  # noqa: E402
from hdm.application.saved_tv_search import SavedTvSearch  # noqa: E402
from hdm.domain.control_plane import PlacementState, TransitionOutcomeKind  # noqa: E402
from hdm.domain.models import Blocker  # noqa: E402
from hdm.domain.saved_tv import (  # noqa: E402
    DEFAULT_MAX_ATTEMPTS,
    SavedTvProfile,
    SavedTvState,
)


SAVED = SavedTvProfile(
    display_stable_id="external-tv",
    edid_identified=True,
    label="Living room TV",
)


class FakeStore:
    """The record without a filesystem, so a call site can be tested alone."""

    def __init__(self, profile=None):
        self.profile = profile
        self.load_error = None
        self.record_error = None
        self.loads = 0
        self.records = []

    def load(self):
        self.loads += 1
        if self.load_error is not None:
            raise self.load_error
        return self.profile

    def record(self, profile):
        if self.record_error is not None:
            raise self.record_error
        self.records.append(profile)
        self.profile = profile

    def forget(self):
        self.profile = None


class Monitor:
    def __init__(self):
        self.available = True
        self.last_wake_source = "kernel_event"

    def invalidate(self):
        pass

    def close(self):
        pass

    async def wait(self, _delay):
        return True


def readiness(stage, code="connection.test"):
    return ConnectionReadinessStatus(stage, code, 1000)


def tv_unplugged(observation):
    """The saved TV's connector reporting nothing plugged into it."""
    snapshot = observation.snapshot
    return replace(
        observation,
        snapshot=replace(
            snapshot,
            displays=tuple(
                replace(display, connected=False, active=False)
                if display.stable_id == SAVED.display_stable_id
                else display
                for display in snapshot.displays
            ),
        ),
    )


def tv_absent(observation):
    """The saved TV's connector not enumerated at all."""
    snapshot = observation.snapshot
    return replace(
        observation,
        snapshot=replace(
            snapshot,
            displays=tuple(
                display
                for display in snapshot.displays
                if display.stable_id != SAVED.display_stable_id
            ),
        ),
    )


class MainSavedTvHelperTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module()

    def test_an_unread_inventory_is_not_an_absent_tv(self):
        snapshot = current("connected-internal.json").snapshot
        self.assertTrue(self.module._display_scan_complete(snapshot))
        # No connectors at all, and the blocker that says why, are both an
        # unfinished look rather than evidence that the TV is not there.
        self.assertFalse(
            self.module._display_scan_complete(replace(snapshot, displays=()))
        )
        self.assertFalse(
            self.module._display_scan_complete(
                replace(
                    snapshot,
                    blockers=(Blocker("drm_inventory_unavailable", "none observed"),),
                )
            )
        )

    def test_only_the_display_a_dock_is_presenting_on_is_offered(self):
        docked = self.module._docked_tv_display(current("tv-docked.json").snapshot)
        self.assertIsNotNone(docked)
        self.assertEqual(docked.stable_id, "external-tv")
        # A TV that is merely plugged in, and a handheld with no TV at all,
        # are not displays any dock landed on.
        self.assertIsNone(
            self.module._docked_tv_display(current("connected-internal.json").snapshot)
        )
        self.assertIsNone(
            self.module._docked_tv_display(current("portable.json").snapshot)
        )


class MainSavedTvCallSiteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_main_module()
        self.events = []

    def plugin(self, profile=None):
        plugin = self.module.Plugin()
        store = FakeStore(profile)
        plugin._saved_tv = SavedTvSearch(store)
        plugin._append_journey_event = lambda **event: self.events.append(event)
        return plugin, store

    async def test_a_successful_dock_records_the_display_it_landed_on(self):
        plugin, store = self.plugin()
        plugin._saved_tv_pending_dock = True
        await plugin._update_saved_tv(
            current("tv-docked.json"),
            readiness(ConnectionReadinessStage.READY_IDLE),
        )
        self.assertEqual(
            [profile.display_stable_id for profile in store.records], ["external-tv"]
        )
        self.assertTrue(store.records[0].edid_identified)
        self.assertFalse(plugin._saved_tv_pending_dock)

    async def test_a_dock_nobody_completed_records_nothing(self):
        plugin, store = self.plugin()
        # The same observation, without a transition having succeeded. Placement
        # alone is not intent: it would remember a TV the player never asked for.
        await plugin._update_saved_tv(
            current("tv-docked.json"),
            readiness(ConnectionReadinessStage.READY_IDLE),
        )
        self.assertEqual(store.records, [])

    async def test_a_dock_that_has_not_reached_the_tv_waits_to_record(self):
        plugin, store = self.plugin()
        plugin._saved_tv_pending_dock = True
        await plugin._update_saved_tv(
            current("connected-internal.json"),
            readiness(ConnectionReadinessStage.WAITING_FOR_HDMI),
        )
        self.assertEqual(store.records, [])
        self.assertTrue(plugin._saved_tv_pending_dock)

    async def test_a_refused_record_is_reported_once_and_not_retried_forever(self):
        plugin, store = self.plugin()
        store.record_error = ValueError("saved TV display identity is invalid")
        plugin._saved_tv_pending_dock = True
        await plugin._update_saved_tv(
            current("tv-docked.json"),
            readiness(ConnectionReadinessStage.READY_IDLE),
        )
        self.assertEqual(store.records, [])
        self.assertFalse(plugin._saved_tv_pending_dock)
        self.assertIn(
            "saved_tv.record_unwritable", [event["code"] for event in self.events]
        )

    async def test_waiting_for_the_saved_tv_reads_as_waiting_not_as_a_failure(self):
        plugin, _store = self.plugin(SAVED)
        for observation in (
            tv_unplugged(current("connected-internal.json")),
            tv_absent(current("connected-internal.json")),
        ):
            await plugin._update_saved_tv(
                observation, readiness(ConnectionReadinessStage.WAITING_FOR_HDMI)
            )
            status = plugin._saved_tv_status()
            self.assertTrue(status["searching"])
            self.assertEqual(status["state"], SavedTvState.WAITING.value)
            self.assertEqual(status["code"], "saved_tv.awaiting_display")
        self.assertEqual(plugin._saved_tv_status()["attempts"], 2)

    async def test_the_saved_tv_appearing_reports_ready(self):
        plugin, _store = self.plugin(SAVED)
        await plugin._update_saved_tv(
            current("connected-internal.json"),
            readiness(ConnectionReadinessStage.WAITING_FOR_HDMI),
        )
        status = plugin._saved_tv_status()
        self.assertEqual(status["state"], SavedTvState.READY.value)
        self.assertEqual(status["code"], "saved_tv.ready")
        # Finding it is not a finished look that failed.
        self.assertEqual(status["attempts"], 0)

    async def test_the_search_settles_instead_of_saying_connecting_forever(self):
        plugin, _store = self.plugin(SAVED)
        observation = tv_unplugged(current("connected-internal.json"))
        for _ in range(DEFAULT_MAX_ATTEMPTS + 5):
            await plugin._update_saved_tv(
                observation, readiness(ConnectionReadinessStage.WAITING_FOR_HDMI)
            )
        status = plugin._saved_tv_status()
        self.assertEqual(status["state"], SavedTvState.SETTLED.value)
        self.assertEqual(status["code"], "saved_tv.not_found")
        self.assertEqual(status["attempts"], DEFAULT_MAX_ATTEMPTS)
        self.assertEqual(status["max_attempts"], DEFAULT_MAX_ATTEMPTS)

    async def test_only_the_stage_that_is_waiting_for_hdmi_spends_the_budget(self):
        plugin, _store = self.plugin(SAVED)
        observation = tv_unplugged(current("connected-internal.json"))
        for stage in (
            ConnectionReadinessStage.WAITING_FOR_DRIVER,
            ConnectionReadinessStage.WAITING_FOR_LINK,
            ConnectionReadinessStage.STABILIZING,
            ConnectionReadinessStage.GAME_RUNNING,
            ConnectionReadinessStage.READY_IDLE,
        ):
            await plugin._update_saved_tv(observation, readiness(stage))
            # No search is running in these stages, so nothing claims one is.
            self.assertFalse(plugin._saved_tv_status()["searching"])
        self.assertEqual(plugin._saved_tv_status()["attempts"], 0)

    async def test_an_unreadable_record_is_cannot_tell_never_no_saved_tv(self):
        plugin, store = self.plugin(SAVED)
        store.load_error = ValueError("saved TV record cannot be a symlink")
        await plugin._update_saved_tv(
            tv_unplugged(current("connected-internal.json")),
            readiness(ConnectionReadinessStage.WAITING_FOR_HDMI),
        )
        status = plugin._saved_tv_status()
        self.assertEqual(status["state"], SavedTvState.UNOBSERVABLE.value)
        self.assertEqual(status["code"], "saved_tv.record_unreadable")
        self.assertEqual(status["attempts"], 0)

    async def test_a_new_dock_re_arms_the_budget_and_re_reads_the_record(self):
        plugin, store = self.plugin(SAVED)
        observation = tv_unplugged(current("connected-internal.json"))
        for _ in range(3):
            await plugin._update_saved_tv(
                observation, readiness(ConnectionReadinessStage.WAITING_FOR_HDMI)
            )
        self.assertEqual(plugin._saved_tv_status()["attempts"], 3)
        loads_while_docked = store.loads

        await plugin._update_saved_tv(
            current("portable.json"),
            readiness(ConnectionReadinessStage.DISCONNECTED),
        )
        self.assertEqual(plugin._saved_tv_status()["attempts"], 0)
        self.assertFalse(plugin._saved_tv_status()["searching"])

        await plugin._update_saved_tv(
            observation, readiness(ConnectionReadinessStage.WAITING_FOR_HDMI)
        )
        self.assertEqual(plugin._saved_tv_status()["attempts"], 1)
        self.assertGreater(store.loads, loads_while_docked)

    async def test_no_state_root_leaves_the_status_neutral_rather_than_raising(self):
        plugin = self.module.Plugin()
        plugin._append_journey_event = lambda **event: self.events.append(event)
        with patch.object(
            self.module,
            "RootOwnedRuntimeState",
            side_effect=ValueError("runtime state root requires a POSIX root process"),
        ):
            await plugin._update_saved_tv(
                tv_unplugged(current("connected-internal.json")),
                readiness(ConnectionReadinessStage.WAITING_FOR_HDMI),
            )
        status = plugin._saved_tv_status()
        self.assertFalse(status["searching"])
        self.assertEqual(status["state"], "")
        self.assertEqual(status["code"], "")

    async def test_the_payload_never_carries_the_identity_or_the_label(self):
        plugin, _store = self.plugin(SAVED)
        await plugin._update_saved_tv(
            tv_unplugged(current("connected-internal.json")),
            readiness(ConnectionReadinessStage.WAITING_FOR_HDMI),
        )
        status = plugin._saved_tv_status()
        self.assertEqual(
            set(status),
            {
                "schema_version",
                "searching",
                "state",
                "code",
                "attempts",
                "max_attempts",
            },
        )
        serialised = json.dumps(status)
        self.assertNotIn(SAVED.display_stable_id, serialised)
        self.assertNotIn(SAVED.label, serialised)
        # Also true of the diagnostics the search writes for an operator.
        for event in self.events:
            rendered = json.dumps(event, default=str)
            self.assertNotIn(SAVED.display_stable_id, rendered)
            self.assertNotIn(SAVED.label, rendered)

    async def test_a_player_switch_to_the_tv_is_intent_too(self):
        plugin, _store = self.plugin()
        plugin._presentation_transition_service = lambda: types.SimpleNamespace(
            execute=lambda _token: types.SimpleNamespace(
                accepted=True,
                code="transition.succeeded",
                operation_id="",
                durable=False,
                outcome=types.SimpleNamespace(
                    kind=TransitionOutcomeKind.SUCCEEDED,
                    placement=PlacementState.DOCKED_EGPU,
                ),
            )
        )
        await plugin._execute_supervised_switch("token", PlacementState.DOCKED_EGPU)
        self.assertTrue(plugin._saved_tv_pending_dock)

    async def test_a_player_return_to_the_handheld_is_not(self):
        plugin, _store = self.plugin()
        plugin._presentation_transition_service = lambda: types.SimpleNamespace(
            execute=lambda _token: types.SimpleNamespace(
                accepted=True,
                code="transition.succeeded",
                operation_id="",
                durable=False,
                outcome=types.SimpleNamespace(
                    kind=TransitionOutcomeKind.SUCCEEDED,
                    placement=PlacementState.PORTABLE,
                ),
            )
        )
        await plugin._execute_supervised_switch("token", PlacementState.PORTABLE)
        self.assertFalse(plugin._saved_tv_pending_dock)


class MainSavedTvLoopTests(unittest.IsolatedAsyncioTestCase):
    """The loop really reaches the search, in the stage the player is in."""

    def setUp(self):
        self.module = load_main_module()

    async def run_loop(self, plugin, observations, stages, *, enabled=True):
        plugin._topology_wakeup = Monitor()
        plugin._automatic_dock_preferences = lambda: types.SimpleNamespace(
            load=lambda: enabled
        )
        plugin._append_journey_event = lambda **event: None
        plugin._connection_wake_source = "local_change"
        pending = list(observations)
        stage_queue = list(stages)
        calls = []

        def observe():
            return pending.pop(0)

        async def observe_connection(_current):
            return readiness(stage_queue.pop(0))

        def execute_automatic(*_args, **_kwargs):
            calls.append("execute")
            return types.SimpleNamespace(
                outcome=types.SimpleNamespace(kind=TransitionOutcomeKind.SUCCEEDED),
                code="transition.succeeded",
                accepted=True,
            )

        plugin._observe_connection_readiness = observe_connection
        plugin._presentation_transition_service = lambda: types.SimpleNamespace(
            reconcile_completion=lambda _: PresentationCompletion("completion.test"),
            execute_automatic=execute_automatic,
        )

        async def wait(_delay):
            if not pending:
                raise asyncio.CancelledError

        plugin._wait_for_topology = wait
        with patch.object(
            self.module,
            "SnapshotTransitionObservationAdapter",
            return_value=types.SimpleNamespace(observe=observe),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await plugin._automatic_dock_loop()
        return calls

    async def test_an_unavailable_tv_keeps_the_handheld_usable_and_says_it_is_waiting(
        self,
    ):
        plugin = self.module.Plugin()
        store = FakeStore(SAVED)
        plugin._saved_tv = SavedTvSearch(store)
        observation = tv_unplugged(current("connected-internal.json"))
        calls = await self.run_loop(
            plugin,
            [observation, observation],
            [
                ConnectionReadinessStage.WAITING_FOR_HDMI,
                ConnectionReadinessStage.WAITING_FOR_HDMI,
            ],
        )
        # Nothing was switched: the session stays where the player can use it.
        self.assertEqual(calls, [])
        payload = plugin._saved_tv_status()
        self.assertTrue(payload["searching"])
        self.assertEqual(payload["state"], SavedTvState.WAITING.value)
        self.assertEqual(payload["code"], "saved_tv.awaiting_display")
        self.assertEqual(payload["attempts"], 2)

    async def test_a_completed_automatic_dock_reaches_the_record(self):
        plugin = self.module.Plugin()
        store = FakeStore()
        plugin._saved_tv = SavedTvSearch(store)
        calls = await self.run_loop(
            plugin,
            [current("connected-internal.json"), current("tv-docked.json")],
            [
                ConnectionReadinessStage.READY_IDLE,
                ConnectionReadinessStage.READY_IDLE,
            ],
        )
        self.assertEqual(calls, ["execute"])
        self.assertEqual(
            [profile.display_stable_id for profile in store.records], ["external-tv"]
        )

    async def test_the_search_runs_even_with_automatic_docking_switched_off(self):
        plugin = self.module.Plugin()
        store = FakeStore(SAVED)
        plugin._saved_tv = SavedTvSearch(store)
        observation = tv_unplugged(current("connected-internal.json"))
        calls = await self.run_loop(
            plugin,
            [observation],
            [ConnectionReadinessStage.WAITING_FOR_HDMI],
            enabled=False,
        )
        self.assertEqual(calls, [])
        self.assertEqual(plugin._saved_tv_status()["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
