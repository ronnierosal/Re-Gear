from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import Mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.adapters.steamos.audio_handoff import (  # noqa: E402
    G1AudioHandoff,
    G1AudioReadiness,
)
from hdm.adapters.steamos.commands import (  # noqa: E402
    AudioCommandResult,
    PipeWireCommandRunner,
)
from hdm.adapters.steamos.gamescope_user import GamescopeUserContext  # noqa: E402
from hdm.delivery.audio_state import PortableAudioStateStore  # noqa: E402
from hdm.domain.control_plane import PlacementState  # noqa: E402


USER = GamescopeUserContext(
    "deck",
    1000,
    1000,
    Path("/home/deck"),
    Path("/run/user/1000"),
    Path("/run/user/1000/bus"),
)
INTERNAL = "alsa_loopback_device.alsa_output.pci-0000_64_00.6.analog-stereo"
EXTERNAL = "alsa_loopback_device.alsa_output.pci-0000_08_00.1.hdmi-stereo-extra1"


class FakeCommands:
    def __init__(
        self,
        *,
        default=INTERNAL,
        configured=None,
        duplicate_external=False,
        fail_set=False,
    ):
        self.default = default
        self.configured = configured or default
        self.duplicate_external = duplicate_external
        self.fail_set = fail_set
        self.set_ids = []

    def dump(self, user, **kwargs):
        values = [
            self.device(50, "0000:64:00.6"),
            self.device(105, "0000:08:00.1"),
            self.sink(62, INTERNAL, 50),
            self.sink(101, EXTERNAL, 105),
            {
                "id": 41,
                "type": "PipeWire:Interface:Metadata",
                "metadata": [
                    {"key": "default.audio.sink", "value": {"name": self.default}},
                    {
                        "key": "default.configured.audio.sink",
                        "value": {"name": self.configured},
                    },
                ],
            },
        ]
        if self.duplicate_external:
            values.append(self.sink(102, EXTERNAL + "-other", 105))
        return AudioCommandResult(True, json.dumps(values).encode("utf-8"))

    def set_default(self, user, object_id):
        self.set_ids.append(object_id)
        if self.fail_set:
            return AudioCommandResult(False, code="injected")
        self.default = {62: INTERNAL, 101: EXTERNAL}.get(object_id, self.default)
        self.configured = self.default
        return AudioCommandResult(True)

    @staticmethod
    def device(object_id, bdf):
        return {
            "id": object_id,
            "type": "PipeWire:Interface:Device",
            "info": {"props": {"device.bus-path": f"pci-{bdf}"}},
        }

    @staticmethod
    def sink(object_id, name, device_id):
        return {
            "id": object_id,
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "media.class": "Audio/Sink",
                    "alsa.loopback": True,
                    "node.name": name,
                    "device.id": device_id,
                }
            },
        }


def hide_external_sink(commands):
    original = commands.dump
    def dump(user, **kwargs):
        result = original(user)
        values = json.loads(result.output)
        return AudioCommandResult(True, json.dumps([
            v for v in values if v.get("id") != 101
        ]).encode())
    commands.dump = dump


class G1AudioHandoffTests(unittest.TestCase):
    def test_prepare_persists_rollback_before_hdmi_sink_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands()
            hide_external_sink(commands)
            self.assertTrue(self.handoff(root, commands).prepare_docked(USER).succeeded)
            self.assertEqual(PortableAudioStateStore(root).load(), INTERNAL)
            self.assertEqual(commands.set_ids, [])

    def test_prepare_save_failure_blocks_activation(self):
        commands = FakeCommands()
        state = Mock(load=lambda: "", save=Mock(side_effect=OSError()))
        handoff = G1AudioHandoff(commands=commands, state=state,
                                resolve_g1_audio_bdf=lambda: "0000:08:00.1")
        self.assertEqual(handoff.prepare_docked(USER).code, "audio.rollback_state_failed")
        self.assertEqual(commands.set_ids, [])

    def test_post_display_wait_handles_delayed_sink_and_remains_bounded(self):
        for appears in (True, False):
            with self.subTest(appears=appears), tempfile.TemporaryDirectory() as directory:
                commands = FakeCommands()
                original = commands.dump
                polls = []
                waits = []
                def dump(user, **kwargs):
                    polls.append(1)
                    values = json.loads(original(user).output)
                    if not appears or len(polls) <= 12:
                        values = [v for v in values if v.get("id") != 101]
                    return AudioCommandResult(True, json.dumps(values).encode())
                commands.dump = dump
                handoff = G1AudioHandoff(
                    commands=commands, state=PortableAudioStateStore(Path(directory)),
                    resolve_g1_audio_bdf=lambda: "0000:08:00.1",
                    readiness_attempts=40, wait=waits.append,
                )
                self.assertTrue(handoff.prepare_docked(USER).succeeded)
                result = handoff.switch(PlacementState.DOCKED_EGPU, USER)
                self.assertEqual(result.succeeded, appears)
                self.assertLessEqual(sum(waits), 9.75)
                self.assertEqual(commands.set_ids, [101] if appears else [])

    def test_slow_reads_respect_elapsed_sink_availability_deadline(self):
        now = [0.0]
        budgets = []
        def dump(user, *, timeout_seconds=None):
            budgets.append(timeout_seconds)
            now[0] += min(5.0, timeout_seconds)
            return AudioCommandResult(False, code="audio.command_timeout")
        handoff = G1AudioHandoff(
            commands=Mock(dump=dump), state=Mock(),
            resolve_g1_audio_bdf=lambda: "0000:08:00.1", readiness_attempts=40,
            clock=lambda: now[0], wait=lambda delay: now.__setitem__(0, now[0] + delay),
        )
        result = handoff._wait_for_external_sink(USER, "0000:08:00.1")
        self.assertIsNone(result[0])
        self.assertEqual(now[0], 10.0)
        self.assertEqual(budgets, [10.0, 4.75])

    def test_failed_default_verification_can_restore_durable_portable_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = FakeCommands()
            handoff = self.handoff(Path(directory), commands)
            self.assertTrue(handoff.prepare_docked(USER).succeeded)
            handoff._verify_default = lambda user, expected: expected == INTERNAL
            self.assertFalse(handoff.switch(PlacementState.DOCKED_EGPU, USER).succeeded)
            self.assertEqual(commands.default, EXTERNAL)
            self.assertTrue(handoff.switch(PlacementState.PORTABLE, USER).succeeded)
            self.assertEqual(commands.default, INTERNAL)
            self.assertEqual(commands.set_ids, [101, 62])

    def test_audio_result_callback_observes_success_and_cannot_break_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = FakeCommands()
            reports = []
            def report(target, result):
                reports.append((target, result.code, result.succeeded))
                raise RuntimeError("logging unavailable")
            handoff = G1AudioHandoff(
                commands=commands,
                state=PortableAudioStateStore(Path(directory)),
                resolve_g1_audio_bdf=lambda: "0000:08:00.1",
                report_result=report,
            )
            self.assertTrue(handoff.switch(PlacementState.DOCKED_EGPU, USER).succeeded)
            self.assertEqual(reports, [(PlacementState.DOCKED_EGPU, "audio.default_verified", True)])

    def test_saved_portable_baseline_survives_a_different_current_sink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = PortableAudioStateStore(root)
            store.save(INTERNAL)
            commands = FakeCommands()
            original_dump = commands.dump
            alternative = INTERNAL + "-alternative"
            def dump(user, **kwargs):
                values = json.loads(original_dump(user).output)
                values.append(commands.sink(63, alternative, 50))
                return AudioCommandResult(True, json.dumps(values).encode())
            commands.dump = dump
            commands.default = alternative
            result = self.handoff(root, commands).switch(PlacementState.DOCKED_EGPU, USER)
            self.assertTrue(result.succeeded)
            self.assertEqual(store.load(), INTERNAL)
            self.assertEqual(result.receipt.previous_sink_name, alternative)

    def test_attached_hdmi_cannot_replace_portable_baseline(self):
        for saved in ("", INTERNAL):
            with self.subTest(saved=saved), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                store = PortableAudioStateStore(root)
                if saved:
                    store.save(saved)
                commands = FakeCommands(default=EXTERNAL)
                result = self.handoff(root, commands).remember_portable(USER)
                self.assertFalse(result.succeeded)
                self.assertEqual(result.code, "audio.portable_sink_is_egpu")
                self.assertEqual(store.load(), saved)
                self.assertEqual(commands.set_ids, [])

    def test_corrupted_external_baseline_never_reports_portable_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            PortableAudioStateStore(root).save(EXTERNAL)
            commands = FakeCommands(default=EXTERNAL)
            result = self.handoff(root, commands).switch(PlacementState.PORTABLE, USER)
            self.assertFalse(result.succeeded)
            self.assertEqual(result.code, "audio.portable_sink_is_egpu")
            self.assertEqual(commands.set_ids, [])

    def test_dock_rejects_corrupted_external_rollback_even_if_already_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            PortableAudioStateStore(root).save(EXTERNAL)
            commands = FakeCommands(default=EXTERNAL)
            result = self.handoff(root, commands).switch(PlacementState.DOCKED_EGPU, USER)
            self.assertFalse(result.succeeded)
            self.assertEqual(result.code, "audio.rollback_sink_unavailable")
            self.assertEqual(commands.set_ids, [])

    def test_repeated_dock_portable_cycles_preserve_original_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands()
            handoff = self.handoff(root, commands)
            self.assertTrue(handoff.remember_portable(USER).succeeded)
            for _ in range(3):
                self.assertTrue(handoff.switch(PlacementState.DOCKED_EGPU, USER).succeeded)
                # An attached Portable observation must not poison the baseline.
                self.assertFalse(handoff.remember_portable(USER).succeeded)
                self.assertTrue(handoff.switch(PlacementState.PORTABLE, USER).succeeded)
                self.assertEqual(commands.default, INTERNAL)
                self.assertEqual(PortableAudioStateStore(root).load(), INTERNAL)
            self.assertEqual(commands.set_ids, [101, 62] * 3)

    def handoff(self, root, commands):
        return G1AudioHandoff(
            commands=commands,
            state=PortableAudioStateStore(root),
            resolve_g1_audio_bdf=lambda: "0000:08:00.1",
        )

    def test_dock_selects_exact_g1_loopback_and_records_portable_sink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands()
            result = self.handoff(root, commands).switch(
                PlacementState.DOCKED_EGPU, USER
            )

            self.assertTrue(result.succeeded)
            self.assertEqual(result.code, "audio.default_verified")
            self.assertEqual(commands.set_ids, [101])
            self.assertEqual(PortableAudioStateStore(root).load(), INTERNAL)
            self.assertTrue(result.receipt.changed)

    def test_portable_observation_records_current_sink_before_attach(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands()
            result = self.handoff(root, commands).remember_portable(USER)

            self.assertTrue(result.succeeded)
            self.assertEqual(PortableAudioStateStore(root).load(), INTERNAL)
            self.assertEqual(commands.set_ids, [])

    def test_current_portable_default_wins_over_stale_configured_g1_sink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands(default=INTERNAL, configured=EXTERNAL)
            result = self.handoff(root, commands).remember_portable(USER)

            self.assertTrue(result.succeeded)
            self.assertEqual(PortableAudioStateStore(root).load(), INTERNAL)

    def test_already_external_requires_a_recorded_portable_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.handoff(
                Path(directory), FakeCommands(default=EXTERNAL)
            ).switch(PlacementState.DOCKED_EGPU, USER)

            self.assertFalse(result.succeeded)
            self.assertEqual(result.code, "audio.rollback_sink_unavailable")

    def test_portable_restores_recorded_sink_and_keeps_rollback_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = PortableAudioStateStore(root)
            store.save(INTERNAL)
            commands = FakeCommands(default=EXTERNAL)
            result = self.handoff(root, commands).switch(
                PlacementState.PORTABLE, USER
            )

            self.assertTrue(result.succeeded)
            self.assertEqual(commands.set_ids, [62])
            self.assertEqual(store.load(), INTERNAL)

    def test_portable_restore_does_not_require_the_removed_g1_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = PortableAudioStateStore(root)
            store.save(INTERNAL)
            commands = FakeCommands(default=EXTERNAL)
            handoff = G1AudioHandoff(
                commands=commands,
                state=store,
                resolve_g1_audio_bdf=lambda: "",
            )

            result = handoff.switch(PlacementState.PORTABLE, USER)

            self.assertTrue(result.succeeded)
            self.assertEqual(result.code, "audio.default_verified")
            self.assertEqual(commands.set_ids, [62])

    def test_failed_presentation_can_rollback_the_audio_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands()
            handoff = self.handoff(root, commands)
            result = handoff.switch(PlacementState.DOCKED_EGPU, USER)

            self.assertTrue(handoff.rollback(result.receipt, USER))
            self.assertEqual(commands.default, INTERNAL)
            self.assertEqual(commands.set_ids, [101, 62])
            self.assertEqual(PortableAudioStateStore(root).load(), "")

    def test_ambiguous_external_sink_fails_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = FakeCommands(duplicate_external=True)
            result = self.handoff(Path(directory), commands).switch(
                PlacementState.DOCKED_EGPU, USER
            )

            self.assertFalse(result.succeeded)
            self.assertEqual(result.code, "audio.external_sink_ambiguous")
            self.assertEqual(commands.set_ids, [])

    def test_transient_ambiguous_external_sink_settles_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = FakeCommands(duplicate_external=True)
            original_dump = commands.dump
            calls = 0

            def dump(user, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    commands.duplicate_external = False
                return original_dump(user)

            commands.dump = dump
            waits = []
            handoff = G1AudioHandoff(
                commands=commands,
                state=PortableAudioStateStore(Path(directory)),
                resolve_g1_audio_bdf=lambda: "0000:08:00.1",
                wait=waits.append,
            )

            result = handoff.switch(PlacementState.DOCKED_EGPU, USER)

            self.assertTrue(result.succeeded)
            self.assertEqual(result.code, "audio.default_verified")
            self.assertEqual(commands.set_ids, [101])
            self.assertGreaterEqual(calls, 3)
            self.assertEqual(waits[:2], [0.25, 0.25])

    def test_unverified_g1_identity_fails_without_dump_or_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = FakeCommands()
            handoff = G1AudioHandoff(
                commands=commands,
                state=PortableAudioStateStore(Path(directory)),
                resolve_g1_audio_bdf=lambda: "",
            )
            result = handoff.switch(PlacementState.DOCKED_EGPU, USER)

            self.assertFalse(result.succeeded)
            self.assertEqual(result.code, "audio.g1_identity_unverified")
            self.assertEqual(commands.set_ids, [])


class G1AudioReadinessTests(unittest.TestCase):
    def readiness(self, root, commands, resolve=lambda: "0000:08:00.1"):
        return G1AudioReadiness(
            commands=commands,
            state=PortableAudioStateStore(root),
            resolve_g1_audio_bdf=resolve,
        )

    def test_before_display_allows_only_absent_sink_with_verified_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = FakeCommands()
            hide_external_sink(commands)
            readiness = self.readiness(root, commands)
            self.assertFalse(readiness.observe(USER).ready)
            result = readiness.observe_before_display(USER)
            self.assertTrue(result.ready)
            self.assertEqual(result.code, "audio.awaiting_display_activation")
            self.assertEqual(result.rollback_sink_name, INTERNAL)
            PortableAudioStateStore(root).save(INTERNAL + "-missing")
            self.assertFalse(readiness.observe_before_display(USER).ready)
            self.assertEqual(commands.set_ids, [])

    def test_before_display_still_rejects_ambiguous_external_sinks(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.readiness(Path(directory), FakeCommands(
                duplicate_external=True)).observe_before_display(USER)
            self.assertFalse(result.ready)
            self.assertEqual(result.code, "audio.external_sink_ambiguous")

    def test_exact_g1_sink_and_current_default_are_ready_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = FakeCommands()

            result = self.readiness(Path(directory), commands).observe(USER)

            self.assertTrue(result.ready)
            self.assertEqual(result.code, "audio.ready")
            self.assertEqual(result.g1_sink_name, EXTERNAL)
            self.assertEqual(result.g1_sink_object_id, 101)
            self.assertEqual(result.rollback_sink_name, INTERNAL)
            self.assertEqual(result.default_sink_name, INTERNAL)
            self.assertEqual(commands.set_ids, [])

    def test_saved_non_g1_rollback_is_ready_when_g1_is_already_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            PortableAudioStateStore(root).save(INTERNAL)
            commands = FakeCommands(default=EXTERNAL)

            result = self.readiness(root, commands).observe(USER)

            self.assertTrue(result.ready)
            self.assertEqual(result.rollback_sink_name, INTERNAL)
            self.assertEqual(result.default_sink_name, EXTERNAL)
            self.assertEqual(commands.set_ids, [])

    def test_g1_default_without_saved_portable_sink_is_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = FakeCommands(default=EXTERNAL)

            result = self.readiness(Path(directory), commands).observe(USER)

            self.assertFalse(result.ready)
            self.assertEqual(result.code, "audio.rollback_sink_unavailable")
            self.assertEqual(result.g1_sink_name, EXTERNAL)
            self.assertEqual(commands.set_ids, [])

    def test_multiple_selectable_g1_sinks_are_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = FakeCommands(duplicate_external=True)

            result = self.readiness(Path(directory), commands).observe(USER)

            self.assertFalse(result.ready)
            self.assertEqual(result.code, "audio.external_sink_ambiguous")
            self.assertEqual(commands.set_ids, [])

    def test_unverified_g1_identity_does_not_read_or_mutate_pipewire(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = FakeCommands()
            commands.dump = Mock(wraps=commands.dump)

            result = self.readiness(
                Path(directory), commands, resolve=lambda: ""
            ).observe(USER)

            self.assertFalse(result.ready)
            self.assertEqual(result.code, "audio.g1_identity_unverified")
            commands.dump.assert_not_called()
            self.assertEqual(commands.set_ids, [])

class PipeWireCommandRunnerTests(unittest.TestCase):
    def test_set_default_argv_is_numeric_only(self):
        calls = []

        def run(argv, **kwargs):
            calls.append(tuple(argv))
            return type(
                "Completed",
                (),
                {"returncode": 0, "stdout": b"", "stderr": b""},
            )()

        import hdm.adapters.steamos.commands as module

        original = module.subprocess.run
        module.subprocess.run = run
        try:
            runner = PipeWireCommandRunner(effective_uid=lambda: 0)
            self.assertTrue(runner.set_default(USER, 101).ok)
            self.assertFalse(runner.set_default(USER, -1).ok)
        finally:
            module.subprocess.run = original

        self.assertEqual(calls[0][-3:], ("/usr/bin/wpctl", "set-default", "101"))


if __name__ == "__main__":
    unittest.main()
