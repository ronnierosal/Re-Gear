from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.event_policy import TopologyEvent  # noqa: E402
from regear.domain.models import GameState  # noqa: E402
from regear.domain.sleep_workflow import SleepFlowEvent, SleepFlowStage  # noqa: E402
from regear.domain.transition_journal import (  # noqa: E402
    JournalEventKind,
    journal_to_dict,
)

from tests.canonical_sleep_replay_support import (  # noqa: E402
    CanonicalSleepReplayHarness,
    replay_fixture,
)


class CanonicalSleepReplayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        value = replay_fixture()
        if value.get("schema_version") != 1:
            raise AssertionError("canonical sleep replay fixture schema changed")
        cls.scenarios = value["scenarios"]

    def test_full_guarded_flow_replays_one_private_append_only_journal(self):
        expected = self.scenarios["full_guarded_flow"]
        replay = CanonicalSleepReplayHarness(
            game_state=GameState.RUNNING, with_client=True
        )
        codes = [replay.start().code, replay.grant_game_consent().code]

        game, mechanism, _ = replay.guarded_game_close()
        codes.append(game.code)
        self.assertTrue(game.game_exit_verified)
        self.assertTrue(mechanism.preceded_by_durable_substep)

        process = replay.guarded_process_release()
        codes.extend((process.process.code, process.sleep.code))
        self.assertTrue(process.process.result.software_blockers_cleared)
        self.assertEqual(len(replay.signals.actions), 1)

        replay.mark_egpu_removed(portable=False)
        codes.append(replay.advance(SleepFlowEvent.EGPU_REMOVAL_VERIFIED).code)
        replay.mark_egpu_removed(portable=True)
        codes.append(replay.advance(SleepFlowEvent.PORTABLE_RECOVERY_VERIFIED).code)
        final = replay.advance(SleepFlowEvent.ORIGINAL_SLEEP_CONTINUED)
        codes.append(final.code)

        self.assertEqual(codes, expected["expected_codes"])
        self.assertEqual(final.flow.stage.value, expected["final_stage"])
        self.assertEqual(
            replay.store.current.entries[-1].kind.value,
            expected["terminal_kind"],
        )
        kinds = tuple(entry.kind for entry in replay.store.current.entries)
        self.assertIn(JournalEventKind.SUBSTEP_STARTED, kinds)
        self.assertIn(JournalEventKind.SUBSTEP_VERIFIED, kinds)

        serialized = json.dumps(journal_to_dict(replay.store.current))
        for private_value in (
            "1234",
            "app-steam",
            "replay-client",
            "replay-client-instance",
            "1000",
        ):
            self.assertNotIn(private_value, serialized)

    def test_unexpected_unplug_policy_cannot_skip_canonical_partial_order(self):
        expected = self.scenarios["unexpected_unplug_partial_order"]
        replay = CanonicalSleepReplayHarness()
        started = replay.start()
        self.assertEqual(started.flow.stage, SleepFlowStage.AWAITING_DISCONNECT)

        decision = replay.topology(TopologyEvent.EGPU_REMOVED)
        self.assertEqual(decision.reason_code, expected["topology_reason"])
        self.assertEqual(
            [directive.value for directive in decision.directives],
            expected["topology_directives"],
        )
        self.assertNotIn("continue", decision.reason_code)

        replay.mark_egpu_removed(portable=True)
        invalid = replay.advance(
            SleepFlowEvent(expected["attempted_event"])
        )
        self.assertEqual(invalid.code, expected["final_code"])
        self.assertEqual(
            replay.store.current.entries[-1].kind.value,
            expected["terminal_kind"],
        )
        self.assertNotIn(
            JournalEventKind.COMMITTED,
            tuple(entry.kind for entry in replay.store.current.entries),
        )

    def test_controller_and_display_loss_remain_recovery_only_side_events(self):
        expected = self.scenarios["peripheral_loss"]
        replay = CanonicalSleepReplayHarness()
        started = replay.start()
        entry_count = len(replay.store.current.entries)

        for case in expected["events"]:
            with self.subTest(event=case["event"]):
                decision = replay.topology(
                    TopologyEvent(case["event"]),
                    builtin_controller_available=case.get(
                        "builtin_controller_available"
                    ),
                )
                self.assertEqual(decision.reason_code, case["reason"])
                self.assertEqual(
                    [directive.value for directive in decision.directives],
                    case["directives"],
                )

        status = replay.sleep.status()
        self.assertEqual(status.stage.value, expected["sleep_stage_remains"])
        self.assertEqual(started.operation_id, status.operation_id)
        self.assertEqual(len(replay.store.current.entries), entry_count)
        self.assertFalse(replay.store.current.terminal)

    def test_game_close_and_request_deadlines_fail_closed(self):
        close_expected = self.scenarios["game_close_timeout"]
        replay = CanonicalSleepReplayHarness(game_state=GameState.RUNNING)
        replay.start()
        replay.grant_game_consent()
        result, mechanism, waiter = replay.guarded_game_close(outcome="timeout")
        self.assertEqual(result.code, close_expected["final_code"])
        self.assertEqual(waiter.calls, close_expected["waits_ms"])
        self.assertEqual(len(mechanism.calls), 1)
        self.assertEqual(
            replay.store.current.entries[-1].kind.value,
            close_expected["terminal_kind"],
        )

        request_expected = self.scenarios["request_timeout"]
        replay = CanonicalSleepReplayHarness(request_ttl_ms=1000)
        replay.start()
        replay.clock.advance(request_expected["advance_ms"])
        replay.mark_egpu_removed(portable=False)
        expired = replay.advance(SleepFlowEvent.EGPU_REMOVAL_VERIFIED)
        self.assertEqual(expired.code, request_expected["final_code"])
        self.assertEqual(expired.flow.stage.value, request_expected["final_stage"])
        self.assertNotIn(
            JournalEventKind.COMMITTED,
            tuple(entry.kind for entry in replay.store.current.entries),
        )

    def test_stale_child_observations_never_reach_a_mechanism(self):
        expected = self.scenarios["stale_children"]

        game_replay = CanonicalSleepReplayHarness(game_state=GameState.RUNNING)
        game_replay.start()
        game_replay.grant_game_consent()
        game, mechanism, _ = game_replay.guarded_game_close(stale=True)
        self.assertEqual(game.code, expected["game_close_code"])
        self.assertEqual(mechanism.calls, [])

        process_replay = CanonicalSleepReplayHarness(with_client=True)
        started = process_replay.start()
        self.assertEqual(started.flow.stage, SleepFlowStage.RELEASING_CLIENTS)
        process = process_replay.guarded_process_release(stale=True)
        self.assertEqual(
            process.process.code, expected["process_release_code"]
        )
        self.assertEqual(len(process_replay.signals.actions), expected["signals"])
        self.assertEqual(
            process_replay.store.current.entries[-1].kind.value,
            expected["terminal_kind"],
        )
        self.assertIsNone(process.sleep)

    def test_restart_recovery_observation_and_persistence_failures_are_bounded(self):
        expected = self.scenarios["restart_recovery_failures"]

        unavailable = CanonicalSleepReplayHarness()
        unavailable.start()
        result = unavailable.restart(observation_available=False)
        self.assertEqual(result.code, expected["observation_unavailable"])
        self.assertTrue(result.action_required)
        self.assertFalse(unavailable.store.current.terminal)

        persist = CanonicalSleepReplayHarness()
        persist.start()
        persist.mark_egpu_removed(portable=True)
        persist.store.fail_on_kind = JournalEventKind.RECOVERY_VERIFIED
        result = persist.restart()
        self.assertEqual(result.code, expected["persistence_failure"])
        self.assertTrue(result.action_required)
        self.assertFalse(result.durable)
        self.assertFalse(persist.store.current.terminal)


if __name__ == "__main__":
    unittest.main()
