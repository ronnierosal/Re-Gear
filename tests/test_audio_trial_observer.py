from dataclasses import replace
from types import SimpleNamespace
import json
import unittest
from unittest.mock import Mock, patch

from backend.regear.adapters.steamos.audio_trial_observer import AudioTrialContext, AudioTrialLiveObserver


class AudioTrialObserverTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.context = AudioTrialContext("a" * 64, "b" * 64, "0000:08:00.1",
            "0000:64:00.6", "portable.sink", 1000, "c" * 32, True, True, self.now)
        self.contexts = Mock(side_effect=lambda: replace(self.context, observed_at=self.now))
        self.commands = Mock()
        self.commands.dump.return_value = SimpleNamespace(ok=True, output=b"same dump")
        self.observer = AudioTrialLiveObserver(SimpleNamespace(uid=1000), self.contexts,
            deadline=20, commands=self.commands, clock=lambda: self.now)
        self.profile = SimpleNamespace(ready=True)
        self.portable = SimpleNamespace(ready=True, sink_name="portable.sink")

    def observe(self):
        prefix = "backend.regear.adapters.steamos.audio_trial_observer."
        with patch(prefix + "parse_audio_profile_observation", return_value=self.profile) as profile, \
             patch(prefix + "parse_portable_default", return_value=self.portable) as portable:
            value = self.observer()
            profile.assert_called_once_with(b"same dump", audio_bdf=self.context.audio_bdf)
            portable.assert_called_once_with(b"same dump", sink_name=self.context.portable_sink,
                                            audio_bdf=self.context.portable_audio_bdf)
            return value

    def test_one_dump_and_exact_internal_identity(self):
        value = self.observe()
        self.assertEqual(value.portable_sink, "portable.sink")
        self.assertEqual(value.observed_at, 10)
        self.assertEqual(self.contexts.call_count, 2)
        self.commands.dump.assert_called_once()
        self.assertEqual(self.commands.dump.call_args.kwargs["timeout_seconds"], 2)

    def test_unverified_context_never_dumps(self):
        for changes in ({"no_game": None}, {"no_game": 1}, {"portable_ready": False},
                        {"uid": True}, {"uid": 1001}, {"session_invocation": "unknown"},
                        {"portable_audio_bdf": self.context.audio_bdf}, {"portable_audio_bdf": ""}):
            initial = self.context
            self.context = replace(initial, **changes)
            with self.assertRaises(ValueError): self.observe()
            self.context = initial
        self.commands.dump.assert_not_called()

    def test_context_change_during_dump_rejected(self):
        for changes in ({"topology_hash": "d" * 64}, {"session_invocation": "e" * 32},
                        {"portable_sink": "other"}, {"portable_audio_bdf": "0000:65:00.6"}):
            self.contexts.side_effect = [self.context, replace(self.context, **changes)]
            with self.assertRaises(ValueError): self.observe()

    def test_failed_dump_or_either_parser_withholds_observation(self):
        self.commands.dump.return_value.ok = False
        with self.assertRaises(OSError): self.observe()
        self.commands.dump.return_value.ok = True
        self.profile.ready = False
        with self.assertRaises(ValueError): self.observe()
        self.profile.ready = True
        self.portable.ready = False
        with self.assertRaises(ValueError): self.observe()

    def test_expired_source_is_not_retimestamped(self):
        def slow(*args, **kwargs):
            self.now += 2.1
            return SimpleNamespace(ok=True, output=b"same dump")
        self.commands.dump.side_effect = slow
        with self.assertRaises(ValueError): self.observe()

    def test_expired_deadline_and_cached_context_fail(self):
        self.observer.deadline = 10
        with self.assertRaises(TimeoutError): self.observe()
        self.observer.deadline = 20
        self.contexts.side_effect = None
        self.contexts.return_value = replace(self.context, observed_at=9)
        with self.assertRaises(ValueError): self.observe()
        self.commands.dump.assert_not_called()

    def test_same_dump_parsers_drive_journaled_off_and_restore(self):
        from tests.test_portable_audio_observation import PortableAudioObservationTests, SINK
        from tests.test_audio_profile_observation import AudioProfileObservationTests
        from tests.test_audio_profile_trial import FakeStore
        from backend.regear.delivery.audio_profile_trial import AudioProfileTrial
        portable = PortableAudioObservationTests()
        portable.setUp()
        external = AudioProfileObservationTests()
        external.setUp()
        values = [*portable.values, external.device]
        self.context = replace(self.context, portable_sink=SINK)
        self.commands.dump.side_effect = lambda *a, **kw: SimpleNamespace(ok=True, output=json.dumps(values).encode())
        store = FakeStore()
        def command(user, device_id, index, **kwargs):
            self.assertEqual(device_id, external.device['id'])
            params = external.device['info']['params']
            target = next(p for p in params['EnumProfile'] if p['index'] == index)
            expected_phase = 'off_requested' if target['name'] == 'off' else 'restore_requested'
            self.assertEqual(store.read('trial').phase.value, expected_phase)
            params['Profile'] = [{'index': index, 'name': target['name']}]
            return SimpleNamespace(ok=True)
        self.commands.set_profile.side_effect = command
        trial = AudioProfileTrial(store, self.observer.user, self.observer,
                                  commands=self.commands, clock=lambda: self.now)
        result = trial.off('trial', boot_hash=self.context.boot_hash, topology_hash=self.context.topology_hash,
            audio_bdf=self.context.audio_bdf, portable_sink=SINK, deadline=20)
        self.assertEqual(result.record.phase.value, 'off_observed')
        self.assertFalse(result.resources_released)
        result = trial.restore('trial', deadline=20)
        self.assertEqual(result.record.phase.value, 'restored')
        self.assertEqual(self.commands.set_profile.call_count, 2)


if __name__ == "__main__":
    unittest.main()
