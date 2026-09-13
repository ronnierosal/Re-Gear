"""Observe and change audio levels, reporting exactly what is known.

This is the half that talks to a port and decides what a player is told. The
outcome vocabulary is the project's, kept distinct rather than collapsed into
"unavailable":

- **unavailable** -- no port at all. The capability does not exist on this
  device or was never wired. Nothing to retry.
- **unknown** -- a port exists and the reading could not be understood. This is
  a device or format problem, and it is worth retrying.
- **blocked** -- the request was refused before dispatch, because the value was
  outside what may be written. The control is working; the input was not.
- **error** -- the command ran and failed.
- **unverified** -- the command was accepted and the readback did not confirm
  it. Distinct from success, because a clamped device reports exactly this and
  a player deserves to know their 90 became something else.

A set never reports success on the strength of an exit code. It re-reads, and
`domain.audio_levels` decides whether the reading agrees.
"""
from __future__ import annotations

from dataclasses import dataclass

from regear.domain.audio_levels import (
    AudioLevel,
    UNKNOWN_LEVEL,
    mute_verified,
    parse_level,
    readback_verified,
    settable_percent,
)
from regear.ports.audio_levels import AudioLevelsPort


@dataclass(frozen=True)
class LevelOutcome:
    """What happened, and what the level is now."""

    state: str
    level: AudioLevel = UNKNOWN_LEVEL
    code: str = ""

    @property
    def ok(self) -> bool:
        return self.state == "verified"


@dataclass(frozen=True)
class AudioLevelsReading:
    """Both observations. Either may be unknown independently of the other."""

    volume: AudioLevel = UNKNOWN_LEVEL
    microphone: AudioLevel = UNKNOWN_LEVEL
    supported: bool = False

    @property
    def available(self) -> bool:
        """Only a supported capability with an understood reading is usable."""
        return self.supported and self.volume.known


class AudioLevelsService:
    """Bounded volume and mic-mute operations over one port.

    An absent port is the supported-capability answer: this device has no
    verified way to read or change levels, so every control stays unavailable
    rather than appearing and failing on first press.
    """

    def __init__(self, port: AudioLevelsPort | None = None) -> None:
        self._port = port

    @property
    def supported(self) -> bool:
        return self._port is not None

    def observe(self) -> AudioLevelsReading:
        if self._port is None:
            return AudioLevelsReading(supported=False)
        return AudioLevelsReading(
            volume=self._read(self._port.read_sink_volume),
            microphone=self._read(self._port.read_source_mute),
            supported=True,
        )

    def set_volume(self, percent: object) -> LevelOutcome:
        if self._port is None:
            return LevelOutcome("unavailable", code="audio_levels.unsupported")
        requested = settable_percent(percent)
        if requested is None:
            # Refused before dispatch: nothing was sent to the device, so the
            # level is whatever it already was rather than unknown.
            return LevelOutcome("blocked", self._read(self._port.read_sink_volume),
                                code="audio_levels.out_of_range")
        applied = self._port.apply_sink_volume(requested)
        if not applied.ok:
            return LevelOutcome("error", code=applied.code or "audio_levels.apply_failed")
        observed = self._read(self._port.read_sink_volume)
        if not observed.known:
            return LevelOutcome("unverified", observed, code="audio_levels.readback_unreadable")
        if not readback_verified(requested, observed):
            return LevelOutcome("unverified", observed, code="audio_levels.readback_disagreed")
        return LevelOutcome("verified", observed)

    def set_microphone_muted(self, muted: object) -> LevelOutcome:
        if self._port is None:
            return LevelOutcome("unavailable", code="audio_levels.unsupported")
        if not isinstance(muted, bool):
            return LevelOutcome("blocked", code="audio_levels.invalid_request")
        applied = self._port.apply_source_mute(muted)
        if not applied.ok:
            return LevelOutcome("error", code=applied.code or "audio_levels.apply_failed")
        observed = self._read(self._port.read_source_mute)
        if not observed.known:
            return LevelOutcome("unverified", observed, code="audio_levels.readback_unreadable")
        if not mute_verified(muted, observed):
            return LevelOutcome("unverified", observed, code="audio_levels.readback_disagreed")
        return LevelOutcome("verified", observed)

    @staticmethod
    def _read(command) -> AudioLevel:
        """One read, with the adapter's own failure code preserved.

        A failed command and unparseable output are both unknown to a player,
        but they are not the same thing to whoever is debugging it, so the code
        survives even though the level does not.
        """
        try:
            result = command()
        except Exception:
            # A port that raises is a broken port, not a muted device.
            return AudioLevel(False, code="audio_levels.port_failed")
        if not result.ok:
            return AudioLevel(False, code=result.code or "audio_levels.read_failed")
        return parse_level(result.output)
