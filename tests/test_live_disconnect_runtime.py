from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.live_disconnect import (  # noqa: E402
    LiveDisconnectResult,
    LiveDisconnectStage,
)
from regear import delivery  # noqa: E402
from regear.adapters.steamos.drm_crtc import CardCrtcState, CrtcRecord  # noqa: E402
from regear.application.live_disconnect import FreshRemovalObservation  # noqa: E402
from regear.delivery import live_disconnect_runtime  # noqa: E402
from regear.delivery.live_disconnect_runtime import (  # noqa: E402
    BUSY_CODE,
    UNAVAILABLE_CODE,
    DisconnectAvailability,
    DisconnectObservation,
    LiveDisconnectRuntime,
    disconnect_result_to_payload,
    disconnect_snapshot_service,
    disconnect_status_to_payload,
    observe_display,
    present_addresses,
)
from regear.egpu_release import HolderScan  # noqa: E402
from regear.delivery.live_disconnect_runtime import GameContext  # noqa: E402
from regear.domain.display_release import DisplayReleaseEvidence  # noqa: E402
from regear.domain.game_close_consent import (  # noqa: E402
    ConsentDecision,
    GameClosePreference,
    InterruptIntent,
)
from regear.domain.game_compatibility import (  # noqa: E402
    EgpuHandoffStatus,
    GameSaveCapability,
)
from regear.domain.removal_safety import RemovalSafety, RemovalSafetyState  # noqa: E402
from regear.domain.removal_transaction import (  # noqa: E402
    FunctionProgress,
    record_progress,
)
from regear.domain.removal_transaction import plan as plan_transaction  # noqa: E402
from regear.domain.safe_undock_readiness import SafeUndockRevalidation  # noqa: E402


GPU = "0000:08:00.0"
AUDIO = "0000:08:00.1"
BINDING = "egpu-stable-id"

READY = RemovalSafety(
    RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL,
    "removal_safety.ready_for_supervised_removal",
    SafeUndockRevalidation("egpu-stable-id", "generation", "sample"),
)
DISPLAY_BLOCKED = RemovalSafety(
    RemovalSafetyState.NOT_READY, "removal_safety.external_display_still_active"
)
CLIENTS_BLOCKED = RemovalSafety(
    RemovalSafetyState.NOT_READY, "removal_safety.clients_active_or_protected"
)

NO_DISPLAY = DisplayReleaseEvidence(
    external_committed=(),
    external_complete=True,
    internal_committed=True,
    client_holders=(),
    client_scan_complete=True,
)
DISPLAY_HELD = replace(NO_DISPLAY, external_committed=(98,))

REMOVED = LiveDisconnectResult(
    LiveDisconnectStage.REMOVED, "live_disconnect.removed", removed=(AUDIO, GPU)
)


class FakeService:
    def __init__(self, result=REMOVED, *, gate=None) -> None:
        self.result = result
        self.calls: list[dict] = []
        self._gate = gate

    def disconnect(self, authorization, program, *, boot_hash, release_display):
        self.calls.append(
            {
                "authorization": authorization,
                "program": program,
                "boot_hash": boot_hash,
                "release_display": release_display,
            }
        )
        if self._gate is not None:
            self._gate.wait(5)
        return self.result


class FakeStore:
    def __init__(self, record=None, *, raises=False) -> None:
        self.record = record
        self._raises = raises

    def load(self):
        if self._raises:
            raise ValueError("unreadable")
        return self.record

    def save(self, record):
        self.record = record

    def clear(self):
        self.record = None


def build(
    *,
    readiness=READY,
    display=NO_DISPLAY,
    present=(AUDIO, GPU),
    binding=BINDING,
    store=None,
    service=None,
    authorize=lambda binding: object(),
    observe_raises=False,
    game=None,
    game_scan_complete=True,
    close_preference=None,
):
    def observe():
        if observe_raises:
            raise OSError("no device")
        return DisconnectObservation(
            FreshRemovalObservation(readiness, binding, "generation", "sample"),
            display,
            present,
            game,
            game_scan_complete,
        )

    runtime = LiveDisconnectRuntime(
        service=service or FakeService(),
        store=store or FakeStore(),
        observe=observe,
        authorize=authorize,
        program=lambda: b"\x00" * 8,
        boot_hash=lambda: "a" * 64,
        close_preference=close_preference,
    )
    runtime.service = runtime._service  # type: ignore[attr-defined]
    return runtime


class StatusTests(unittest.TestCase):
    def test_a_ready_device_reports_ready(self) -> None:
        status = build().status()

        self.assertIs(status.availability, DisconnectAvailability.READY)
        self.assertTrue(status.ready)
        self.assertFalse(status.display_release_required)

    def test_a_standing_display_is_attemptable_with_the_approval_required(
        self,
    ) -> None:
        """The one blocker a disconnect can clear by itself.

        Reporting it as blocked would tell a player nothing can be done, when
        in fact all that is needed is their approval to turn the TV off.
        """
        status = build(readiness=DISPLAY_BLOCKED, display=DISPLAY_HELD).status()

        self.assertIs(status.availability, DisconnectAvailability.ATTEMPTABLE)
        self.assertTrue(status.attemptable)
        self.assertFalse(status.ready)
        self.assertTrue(status.display_release_required)
        self.assertEqual(status.code, "removal_safety.external_display_still_active")

    def test_approved_holders_are_attemptable_because_the_sequence_clears_them(
        self,
    ) -> None:
        """Removal safety is asked before any release, and before one it
        always declines. Repeating that verdict would tell a player their eGPU
        can never be disconnected.
        """
        evidence = replace(NO_DISPLAY, client_holders=("wireplumber.service",))
        status = build(readiness=CLIENTS_BLOCKED, display=evidence).status()

        self.assertIs(status.availability, DisconnectAvailability.ATTEMPTABLE)
        self.assertTrue(status.attemptable)
        self.assertFalse(status.ready)

    def test_an_unapproved_holder_disqualifies_the_whole_set(self) -> None:
        """The plan refuses rather than restarting something it may not touch."""
        evidence = replace(
            NO_DISPLAY, client_holders=("wireplumber.service", "init.scope")
        )
        status = build(readiness=CLIENTS_BLOCKED, display=evidence).status()

        self.assertIs(status.availability, DisconnectAvailability.BLOCKED)
        self.assertFalse(status.attemptable)

    def test_an_unfinished_scan_is_never_attemptable(self) -> None:
        evidence = replace(
            NO_DISPLAY,
            client_holders=("wireplumber.service",),
            client_scan_complete=False,
        )
        status = build(readiness=CLIENTS_BLOCKED, display=evidence).status()

        self.assertIs(status.availability, DisconnectAvailability.BLOCKED)

    def test_a_blocker_the_sequence_cannot_clear_stays_blocked(self) -> None:
        """A running game is not something a disconnect can restart away."""
        game = RemovalSafety(
            RemovalSafetyState.NOT_READY, "removal_safety.game_running"
        )
        status = build(readiness=game, display=DISPLAY_HELD).status()

        self.assertIs(status.availability, DisconnectAvailability.BLOCKED)
        self.assertFalse(status.attemptable)

    def test_a_blocker_keeps_its_own_code_whatever_the_availability(
        self,
    ) -> None:
        status = build(readiness=CLIENTS_BLOCKED, display=DISPLAY_HELD).status()

        self.assertEqual(status.code, "removal_safety.clients_active_or_protected")
        # Still reported, so a caller can say what would have to happen.
        self.assertTrue(status.display_release_required)

    def test_holders_and_scan_completeness_are_reported_not_summarised(
        self,
    ) -> None:
        """A caller must not infer a clear device from an empty holder list."""
        evidence = replace(
            NO_DISPLAY, client_holders=("steam.service",), client_scan_complete=False
        )
        status = build(readiness=CLIENTS_BLOCKED, display=evidence).status()

        self.assertEqual(status.holders, ("steam.service",))
        self.assertFalse(status.scan_complete)

    def test_no_egpu_is_unavailable_rather_than_blocked(self) -> None:
        for runtime in (build(binding=""), build(observe_raises=True)):
            with self.subTest(runtime=runtime):
                status = runtime.status()
                self.assertIs(status.availability, DisconnectAvailability.UNAVAILABLE)
                self.assertEqual(status.code, UNAVAILABLE_CODE)

    def test_status_never_runs_a_disconnect(self) -> None:
        service = FakeService()
        runtime = build(service=service)

        runtime.status()
        runtime.status()

        self.assertEqual(service.calls, [])


class RecoveryTests(unittest.TestCase):
    """A half-detached device outranks everything else a status could say."""

    def test_a_partially_detached_prior_removal_demands_recovery(self) -> None:
        record = record_progress(
            plan_transaction(
                owner_id="regear", device_set=BINDING, addresses=(AUDIO, GPU), now_ns=1
            ),
            AUDIO,
            FunctionProgress.REMOVED,
        )
        status = build(store=FakeStore(record), present=(GPU,)).status()

        self.assertIs(status.availability, DisconnectAvailability.RECOVERY_REQUIRED)
        self.assertEqual(status.code, "removal_transaction.partially_detached")

    def test_a_record_whose_removal_never_started_does_not_block(self) -> None:
        record = plan_transaction(
            owner_id="regear", device_set=BINDING, addresses=(AUDIO, GPU), now_ns=1
        )
        status = build(store=FakeStore(record), present=(AUDIO, GPU)).status()

        self.assertIs(status.availability, DisconnectAvailability.READY)

    def test_an_unreadable_record_is_reported_rather_than_ignored(self) -> None:
        status = build(store=FakeStore(raises=True)).status()

        self.assertIs(status.availability, DisconnectAvailability.RECOVERY_REQUIRED)
        self.assertEqual(status.code, "live_disconnect.record_unreadable")


class ExecuteTests(unittest.TestCase):
    def test_the_display_approval_is_passed_through_untouched(self) -> None:
        for approved in (True, False):
            with self.subTest(approved=approved):
                service = FakeService()
                build(service=service).execute(release_display=approved)
                self.assertIs(service.calls[0]["release_display"], approved)

    def test_the_outcome_is_remembered_and_visible_in_status(self) -> None:
        runtime = build()

        result = runtime.execute(release_display=False)

        self.assertIs(result.stage, LiveDisconnectStage.REMOVED)
        self.assertIs(runtime.status().last, result)

    def test_a_device_that_cannot_be_observed_is_refused_before_arming(self) -> None:
        service = FakeService()
        result = build(service=service, observe_raises=True).execute(
            release_display=False
        )

        self.assertEqual(result.code, UNAVAILABLE_CODE)
        self.assertEqual(service.calls, [])

    def test_an_unauthorised_scope_is_refused_before_arming(self) -> None:
        service = FakeService()
        result = build(service=service, authorize=lambda binding: None).execute(
            release_display=False
        )

        self.assertEqual(result.code, "live_disconnect.not_authorized")
        self.assertEqual(service.calls, [])


class SerializationTests(unittest.TestCase):
    """Two disconnects racing over one device is not a state the guards cover."""

    def setUp(self) -> None:
        self.gate = threading.Event()
        self.service = FakeService(gate=self.gate)
        self.runtime = build(service=self.service)
        self.thread = threading.Thread(
            target=lambda: self.runtime.execute(release_display=False)
        )

    def _start_and_wait(self) -> None:
        self.thread.start()
        for _ in range(500):
            if self.service.calls:
                return
            threading.Event().wait(0.01)
        self.fail("the first attempt never started")

    def tearDown(self) -> None:
        self.gate.set()
        if self.thread.is_alive():
            self.thread.join(5)

    def test_a_second_attempt_is_refused_rather_than_queued(self) -> None:
        """Refused, because a caller that asked twice wants to know."""
        self._start_and_wait()

        result = self.runtime.execute(release_display=False)

        self.assertEqual(result.code, BUSY_CODE)
        self.assertEqual(len(self.service.calls), 1)

    def test_status_reports_busy_without_blocking_on_the_attempt(self) -> None:
        self._start_and_wait()

        status = self.runtime.status()

        self.assertIs(status.availability, DisconnectAvailability.BUSY)
        self.assertTrue(status.busy)
        self.assertEqual(status.code, BUSY_CODE)

    def test_the_runtime_accepts_work_again_once_the_attempt_finishes(self) -> None:
        self._start_and_wait()
        self.gate.set()
        self.thread.join(5)

        self.assertIs(self.runtime.status().availability, DisconnectAvailability.READY)
        self.assertIs(
            self.runtime.execute(release_display=False).stage,
            LiveDisconnectStage.REMOVED,
        )


NODES = ("/dev/dri/card1", "/dev/dri/renderD129")


class FakeProbe:
    def __init__(self, states) -> None:
        self._states = states

    def observe(self, node):
        return self._states[node]


def crtc_state(node, *, committed=True, complete=True):
    records = (CrtcRecord(98, 133 if committed else 0, committed, 3840, 2160),)
    return CardCrtcState(node, "fake", records if complete else (), complete)


class ObserveDisplayTests(unittest.TestCase):
    def _observe(self, *, external, internal, scan):
        probe = FakeProbe({"/dev/dri/card1": external, "/dev/dri/card0": internal})
        with patch.object(
            live_disconnect_runtime, "DrmCrtcProbe", lambda: probe
        ), patch.object(
            live_disconnect_runtime, "scan_holders", lambda *a, **k: scan
        ):
            return observe_display(NODES, nodes_incomplete=False)

    def test_the_reading_carries_both_displays_and_the_holders(self) -> None:
        evidence = self._observe(
            external=crtc_state("/dev/dri/card1"),
            internal=crtc_state("/dev/dri/card0"),
            scan=HolderScan(()),
        )

        self.assertEqual(evidence.external_committed, (98,))
        self.assertTrue(evidence.external_complete)
        self.assertIs(evidence.internal_committed, True)
        self.assertTrue(evidence.client_scan_complete)

    def test_an_incomplete_holder_scan_travels_into_the_evidence(self) -> None:
        """An empty holder list from a scan that could not finish is not clear."""
        evidence = self._observe(
            external=crtc_state("/dev/dri/card1"),
            internal=crtc_state("/dev/dri/card0"),
            scan=HolderScan((), unreadable_processes=2),
        )

        self.assertEqual(evidence.client_holders, ())
        self.assertFalse(evidence.client_scan_complete)

    def test_an_unreadable_internal_panel_is_unknown_rather_than_absent(self) -> None:
        evidence = self._observe(
            external=crtc_state("/dev/dri/card1"),
            internal=crtc_state("/dev/dri/card0", complete=False),
            scan=HolderScan(()),
        )

        self.assertIsNone(evidence.internal_committed)


class FakeEntry:
    def __init__(self, exists: bool) -> None:
        self._exists = exists

    def is_dir(self) -> bool:
        return self._exists


class FakePciRoot:
    """A bus that enumerates exactly the given addresses.

    A real directory tree cannot stand in: PCI addresses contain colons, which
    Windows will not accept as a path component, and this runs wherever the
    suite does.
    """

    def __init__(self, present) -> None:
        self._present = set(present)

    def __truediv__(self, name: str) -> FakeEntry:
        return FakeEntry(name in self._present)


class PresentAddressTests(unittest.TestCase):
    def _enumerate(self, *addresses):
        return patch.object(
            live_disconnect_runtime, "PCI_DEVICE_ROOT", FakePciRoot(addresses)
        )

    def test_both_functions_are_reported_when_the_bus_has_them(self) -> None:
        with self._enumerate(GPU, AUDIO):
            self.assertEqual(present_addresses(GPU, AUDIO), (AUDIO, GPU))

    def test_a_half_detached_device_reports_only_what_remains(self) -> None:
        """The reading `reconcile` treats as needing recovery."""
        with self._enumerate(GPU):
            self.assertEqual(present_addresses(GPU, AUDIO), (GPU,))

    def test_a_fully_removed_device_reports_nothing(self) -> None:
        with self._enumerate():
            self.assertEqual(present_addresses(GPU, AUDIO), ())


class SelfExclusionTests(unittest.TestCase):
    def test_the_disconnect_excludes_itself_from_its_own_client_scan(self) -> None:
        """It holds the card open to keep DRM master while releasing the display.

        Without this the scan sees this process holding the device and the
        disconnect reports itself as the thing blocking the disconnect.
        """
        scanner = disconnect_snapshot_service()._discovery._egpu_clients

        self.assertEqual(scanner._exclude_pids, frozenset({os.getpid()}))


class PayloadTests(unittest.TestCase):
    """What a caller receives, and what it must not have to work out."""

    def test_holders_and_completeness_are_both_reported_never_summarised(
        self,
    ) -> None:
        """A caller must not infer a clear device from an empty holder list."""
        evidence = replace(
            NO_DISPLAY, client_holders=("steam.service",), client_scan_complete=False
        )
        payload = disconnect_status_to_payload(
            build(readiness=CLIENTS_BLOCKED, display=evidence).status()
        )

        self.assertEqual(payload["holders"], ["steam.service"])
        self.assertIs(payload["scan_complete"], False)
        self.assertIs(payload["ready"], False)
        self.assertIs(payload["attemptable"], False)
        self.assertEqual(payload["code"], "removal_safety.clients_active_or_protected")

    def test_a_standing_display_is_attemptable_and_says_the_approval_is_needed(
        self,
    ) -> None:
        payload = disconnect_status_to_payload(
            build(readiness=DISPLAY_BLOCKED, display=DISPLAY_HELD).status()
        )

        self.assertIs(payload["attemptable"], True)
        self.assertIs(payload["ready"], False)
        self.assertIs(payload["display_release_required"], True)

    def test_a_status_with_no_prior_attempt_reports_none_rather_than_omitting_it(
        self,
    ) -> None:
        payload = disconnect_status_to_payload(build().status())
        self.assertIsNone(payload["last"])

    def test_the_last_outcome_travels_with_the_status(self) -> None:
        runtime = build()
        runtime.execute(release_display=False)

        payload = disconnect_status_to_payload(runtime.status())

        self.assertIsNotNone(payload["last"])
        self.assertEqual(payload["last"]["removed"], [AUDIO, GPU])

    def test_a_removal_that_left_the_device_disturbed_says_so(self) -> None:
        """A caller showing this reports a system needing attention."""
        result = LiveDisconnectResult(
            LiveDisconnectStage.REMOVAL_UNRECOVERABLE, "device_removal.rescan_failed"
        )

        payload = disconnect_result_to_payload(result)

        self.assertIs(payload["ok"], False)
        self.assertIs(payload["device_disturbed"], True)

    def test_every_payload_value_survives_json(self) -> None:
        """These cross an RPC boundary, so tuples and enums cannot travel."""
        runtime = build(readiness=DISPLAY_BLOCKED, display=DISPLAY_HELD)
        runtime.execute(release_display=True)

        encoded = json.dumps(disconnect_status_to_payload(runtime.status()))

        self.assertIn("display_release_required", encoded)


class GameContextTests(unittest.TestCase):
    """The dialog cannot say anything useful without these facts."""

    def test_a_running_game_travels_with_its_catalog_knowledge(self) -> None:
        context = GameContext(
            "1145360", "Hades",
            GameSaveCapability.VERIFIED_SAVE_ON_EXIT,
            EgpuHandoffStatus.VERIFIED,
        )
        payload = disconnect_status_to_payload(
            build(readiness=CLIENTS_BLOCKED, game=context).status()
        )

        self.assertEqual(payload["game"]["app_id"], "1145360")
        self.assertEqual(payload["game"]["save_capability"], "verified_save_on_exit")
        self.assertIs(payload["game"]["save_known"], True)

    def test_an_uncatalogued_game_reports_untested_rather_than_nothing(self) -> None:
        context = GameContext(
            "999", "", GameSaveCapability.UNTESTED, EgpuHandoffStatus.UNTESTED
        )
        payload = disconnect_status_to_payload(
            build(readiness=CLIENTS_BLOCKED, game=context).status()
        )

        self.assertEqual(payload["game"]["save_capability"], "untested")
        self.assertIs(payload["game"]["save_known"], False)
        self.assertEqual(payload["game"]["title"], "")

    def test_no_game_is_null_rather_than_an_empty_object(self) -> None:
        self.assertIsNone(disconnect_status_to_payload(build().status())["game"])


HADES = GameContext(
    "1145360", "Hades", GameSaveCapability.UNTESTED, EgpuHandoffStatus.UNTESTED
)


class ClosePromptTests(unittest.TestCase):
    """The status carries the decision, so the dialog does not re-derive it."""

    def test_a_running_game_asks_before_anything_closes(self) -> None:
        payload = disconnect_status_to_payload(
            build(readiness=CLIENTS_BLOCKED, game=HADES).status()
        )

        self.assertEqual(payload["close_prompt"]["decision"], "confirm")
        self.assertIs(payload["close_prompt"]["may_proceed"], False)
        self.assertEqual(payload["close_prompt"]["intent"], "disconnect")

    def test_no_game_over_a_finished_look_has_nothing_to_close(self) -> None:
        payload = disconnect_status_to_payload(build().status())

        self.assertEqual(payload["close_prompt"]["decision"], "nothing_to_close")
        self.assertIs(payload["close_prompt"]["may_proceed"], True)

    def test_a_look_that_failed_is_not_reported_as_an_empty_screen(self) -> None:
        # The failure this guards: the scan throws, the status says there is
        # nothing to close, and a player's game is closed without a word.
        payload = disconnect_status_to_payload(
            build(game=None, game_scan_complete=False).status()
        )

        self.assertEqual(payload["close_prompt"]["decision"], "confirm")
        self.assertEqual(payload["close_prompt"]["code"], "game_close.scan_incomplete")
        self.assertIsNone(payload["game"])

    def test_a_standing_answer_for_this_game_is_honoured(self) -> None:
        status = build(
            readiness=CLIENTS_BLOCKED,
            game=HADES,
            close_preference=lambda app_id: GameClosePreference(
                app_id, InterruptIntent.DISCONNECT, skip_confirmation=True
            ),
        ).status()

        self.assertEqual(status.close_prompt.decision, ConsentDecision.REMEMBERED)

    def test_an_unreadable_preference_asks_rather_than_assumes_consent(self) -> None:
        # Failing the other way would close a game on an answer nobody can
        # produce.
        def explode(app_id: str):
            raise OSError("preferences unreadable")

        status = build(
            readiness=CLIENTS_BLOCKED, game=HADES, close_preference=explode
        ).status()

        self.assertEqual(status.close_prompt.decision, ConsentDecision.CONFIRM)

    def test_an_unnamed_game_is_never_matched_to_a_stored_answer(self) -> None:
        asked: list[str] = []

        def record(app_id: str):
            asked.append(app_id)
            return GameClosePreference(
                app_id, InterruptIntent.DISCONNECT, skip_confirmation=True
            )

        unnamed = replace(HADES, app_id="", title="", identity_exact=False)
        status = build(
            readiness=CLIENTS_BLOCKED, game=unnamed, close_preference=record
        ).status()

        self.assertEqual(asked, [])
        self.assertEqual(status.close_prompt.decision, ConsentDecision.CONFIRM)
        self.assertEqual(status.close_prompt.code, "game_close.identity_unverified")

    def test_the_payload_carries_what_a_dialog_has_to_render(self) -> None:
        payload = disconnect_status_to_payload(
            build(readiness=CLIENTS_BLOCKED, game=HADES).status()
        )
        prompt = payload["close_prompt"]

        self.assertEqual(
            set(prompt),
            {
                "schema_version",
                "decision",
                "code",
                "intent",
                "may_proceed",
                "progress_at_risk",
                "save_known",
                "remember_offered",
                "relaunch_offered",
                "relaunch_requested",
            },
        )
        self.assertIs(prompt["remember_offered"], True)
        self.assertIs(prompt["relaunch_offered"], True)

    def test_a_game_known_to_lose_progress_never_offers_the_checkbox(self) -> None:
        game = replace(
            HADES, save_capability=GameSaveCapability.MANUAL_SAVE_REQUIRED
        )
        payload = disconnect_status_to_payload(
            build(
                readiness=CLIENTS_BLOCKED,
                game=game,
                close_preference=lambda app_id: GameClosePreference(
                    app_id, InterruptIntent.DISCONNECT, skip_confirmation=True
                ),
            ).status()
        )

        self.assertEqual(payload["close_prompt"]["decision"], "confirm")
        self.assertIs(payload["close_prompt"]["remember_offered"], False)
        self.assertIs(payload["close_prompt"]["progress_at_risk"], True)

    def test_the_payload_survives_serialization(self) -> None:
        encoded = json.dumps(
            disconnect_status_to_payload(
                build(readiness=CLIENTS_BLOCKED, game=HADES).status()
            )
        )

        self.assertIn("close_prompt", encoded)


if __name__ == "__main__":
    unittest.main()
