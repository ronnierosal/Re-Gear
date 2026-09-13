import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.application.audio_levels import AudioLevelsService
from regear.domain.audio_levels import (
    MAX_SETTABLE_PERCENT,
    parse_level,
    readback_verified,
    settable_percent,
)
from regear.ports.audio_levels import LevelCommandResult


class FakePort:
    """Records what was dispatched and replays scripted command output."""

    def __init__(self, volume="Volume: 0.50", mute="Volume: 0.50 [MUTED]",
                 apply_ok=True, apply_code=""):
        self.volume = volume
        self.mute = mute
        self.apply_ok = apply_ok
        self.apply_code = apply_code
        self.applied_percent = []
        self.applied_mute = []
        self.reads = 0

    def read_sink_volume(self):
        self.reads += 1
        return LevelCommandResult(True, self.volume)

    def apply_sink_volume(self, percent):
        self.applied_percent.append(percent)
        return LevelCommandResult(self.apply_ok, code=self.apply_code)

    def read_source_mute(self):
        self.reads += 1
        return LevelCommandResult(True, self.mute)

    def apply_source_mute(self, muted):
        self.applied_mute.append(muted)
        return LevelCommandResult(self.apply_ok, code=self.apply_code)


class ParseLevelTests(unittest.TestCase):
    def test_reads_a_plain_volume(self):
        level = parse_level("Volume: 0.65")
        self.assertTrue(level.known)
        self.assertEqual(level.percent, 65)
        self.assertFalse(level.muted)

    def test_reads_the_muted_marker_as_a_separate_fact(self):
        level = parse_level("Volume: 0.65 [MUTED]")
        self.assertEqual(level.percent, 65, "muting does not change the level")
        self.assertTrue(level.muted)

    def test_unrecognised_output_is_unknown_rather_than_zero(self):
        """A silent fallback to 0 would show a muted slider for a loud device."""
        for output in ("", "   ", "wpctl: command not found", "Volume 0.65",
                       "Volume: abc", "Volume: 0.65 of 1.00", "0.65", None, 17):
            level = parse_level(output)
            self.assertFalse(level.known, repr(output))
            self.assertIsNone(level.percent, repr(output))

    def test_multi_line_output_is_refused_rather_than_scanned(self):
        """A command that printed a warning first is not one to trust."""
        level = parse_level("WARNING: node changed\nVolume: 0.65")
        self.assertFalse(level.known)

    def test_over_amplification_is_reported_not_clamped(self):
        """1.4 is a real state, and hiding it hides why audio is distorting."""
        level = parse_level("Volume: 1.40")
        self.assertTrue(level.known)
        self.assertEqual(level.percent, 140)
        self.assertTrue(level.over_amplified)

    def test_an_absurd_value_is_a_parse_failure(self):
        self.assertFalse(parse_level("Volume: 99.0").known)

    def test_zero_is_a_real_reading_and_stays_known(self):
        level = parse_level("Volume: 0.00")
        self.assertTrue(level.known, "a genuinely silent device is not unknown")
        self.assertEqual(level.percent, 0)


class SettablePercentTests(unittest.TestCase):
    def test_accepts_the_supported_range_inclusive(self):
        for value in (0, 1, 50, MAX_SETTABLE_PERCENT):
            self.assertEqual(settable_percent(value), value)

    def test_refuses_out_of_range_rather_than_clamping(self):
        """Silently moving to a different value than the slider showed is worse
        than refusing: Re-Gear must not be what pushed a device to distort."""
        for value in (-1, 101, 140, 1000):
            self.assertIsNone(settable_percent(value))

    def test_refuses_non_integers_including_bool(self):
        for value in (0.5, "50", None, True, False, [50]):
            self.assertIsNone(settable_percent(value))


class ReadbackTests(unittest.TestCase):
    def test_within_tolerance_counts_as_applied(self):
        self.assertTrue(readback_verified(65, parse_level("Volume: 0.65")))
        self.assertTrue(readback_verified(65, parse_level("Volume: 0.66")))

    def test_a_clamped_device_is_not_verified(self):
        self.assertFalse(readback_verified(90, parse_level("Volume: 1.00")))

    def test_an_unknown_reading_is_never_verification(self):
        self.assertFalse(readback_verified(65, parse_level("nonsense")))


class ServiceTests(unittest.TestCase):
    def test_without_a_port_every_control_is_unavailable(self):
        service = AudioLevelsService(None)
        self.assertFalse(service.supported)
        reading = service.observe()
        self.assertFalse(reading.available)
        self.assertFalse(reading.volume.known)
        self.assertEqual(service.set_volume(50).state, "unavailable")
        self.assertEqual(service.set_microphone_muted(True).state, "unavailable")

    def test_observe_reports_both_levels_independently(self):
        service = AudioLevelsService(FakePort(volume="Volume: 0.30", mute="Volume: 1.00 [MUTED]"))
        reading = service.observe()
        self.assertTrue(reading.available)
        self.assertEqual(reading.volume.percent, 30)
        self.assertTrue(reading.microphone.muted)

    def test_an_unreadable_sink_does_not_hide_a_readable_microphone(self):
        service = AudioLevelsService(FakePort(volume="nonsense", mute="Volume: 0.80"))
        reading = service.observe()
        self.assertFalse(reading.volume.known)
        self.assertTrue(reading.microphone.known, "one unknown reading is not both")
        self.assertFalse(reading.available)

    def test_a_set_is_verified_only_after_a_readback(self):
        port = FakePort(volume="Volume: 0.70")
        outcome = AudioLevelsService(port).set_volume(70)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.state, "verified")
        self.assertEqual(port.applied_percent, [70])
        self.assertEqual(port.reads, 1, "the write must be confirmed by a read")

    def test_an_accepted_command_that_did_not_move_the_device_is_unverified(self):
        """Exit zero is not evidence. A clamped device reports exactly this."""
        port = FakePort(volume="Volume: 1.00")
        outcome = AudioLevelsService(port).set_volume(90)
        self.assertEqual(outcome.state, "unverified")
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.code, "audio_levels.readback_disagreed")
        self.assertEqual(outcome.level.percent, 100, "report what it actually is")

    def test_an_unreadable_readback_is_unverified_not_successful(self):
        port = FakePort(volume="nonsense")
        outcome = AudioLevelsService(port).set_volume(40)
        self.assertEqual(outcome.state, "unverified")
        self.assertEqual(outcome.code, "audio_levels.readback_unreadable")

    def test_an_out_of_range_request_is_blocked_and_never_dispatched(self):
        port = FakePort(volume="Volume: 0.50")
        outcome = AudioLevelsService(port).set_volume(140)
        self.assertEqual(outcome.state, "blocked")
        self.assertEqual(port.applied_percent, [], "nothing may reach the device")
        self.assertEqual(outcome.level.percent, 50, "the level is what it already was")

    def test_a_failed_command_is_an_error_carrying_its_code(self):
        port = FakePort(apply_ok=False, apply_code="audio.root_required")
        outcome = AudioLevelsService(port).set_volume(50)
        self.assertEqual(outcome.state, "error")
        self.assertEqual(outcome.code, "audio.root_required")

    def test_mute_is_verified_against_the_readback_too(self):
        port = FakePort(mute="Volume: 0.50 [MUTED]")
        self.assertTrue(AudioLevelsService(port).set_microphone_muted(True).ok)
        self.assertEqual(port.applied_mute, [True])

    def test_an_unmute_that_did_not_take_is_unverified(self):
        port = FakePort(mute="Volume: 0.50 [MUTED]")
        outcome = AudioLevelsService(port).set_microphone_muted(False)
        self.assertEqual(outcome.state, "unverified")
        self.assertEqual(outcome.code, "audio_levels.readback_disagreed")

    def test_a_non_boolean_mute_request_is_blocked(self):
        port = FakePort()
        outcome = AudioLevelsService(port).set_microphone_muted("yes")
        self.assertEqual(outcome.state, "blocked")
        self.assertEqual(port.applied_mute, [])

    def test_a_port_that_raises_is_a_broken_port_not_a_silent_device(self):
        class Exploding(FakePort):
            def read_sink_volume(self):
                raise RuntimeError("transport gone")

        reading = AudioLevelsService(Exploding()).observe()
        self.assertFalse(reading.volume.known)
        self.assertEqual(reading.volume.code, "audio_levels.port_failed")

    def test_a_read_failure_preserves_the_adapters_own_code(self):
        class Refusing(FakePort):
            def read_sink_volume(self):
                return LevelCommandResult(False, code="audio.user_invalid")

        reading = AudioLevelsService(Refusing()).observe()
        self.assertFalse(reading.volume.known)
        self.assertEqual(reading.volume.code, "audio.user_invalid")


if __name__ == "__main__":
    unittest.main()
