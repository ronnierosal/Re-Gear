"""Live PipeWire evidence bracketed by trusted portable hardware observations.

The context source must use existing hardware/session/game discovery. This
adapter never infers internal identity merely from the absence of a G1 match.
"""
from dataclasses import dataclass, replace
import math
import re
import time

from ...delivery.audio_profile_trial import AudioTrialObservation
from .audio_profile_observation import parse_audio_profile_observation
from .portable_audio_observation import parse_portable_default
from .commands import PipeWireCommandRunner


@dataclass(frozen=True)
class AudioTrialContext:
    boot_hash: str
    topology_hash: str
    audio_bdf: str
    portable_audio_bdf: str
    portable_sink: str
    uid: int
    session_invocation: str
    no_game: bool
    portable_ready: bool
    observed_at: float


class AudioTrialLiveObserver:
    def __init__(self, user, observe_context, *, deadline, commands=None, clock=time.monotonic):
        self.user, self.observe_context, self.deadline = user, observe_context, deadline
        self.commands = PipeWireCommandRunner() if commands is None else commands
        self.clock = clock

    def _now(self):
        now = self.clock()
        if (type(now) not in (int, float) or not math.isfinite(now) or now < 0
                or type(self.deadline) not in (int, float) or not math.isfinite(self.deadline)
                or not 0 < self.deadline - now <= 30):
            raise TimeoutError("audio observation deadline expired")
        return now

    def _context(self):
        started = self._now()
        value = self.observe_context()
        ended = self._now()
        if (type(value) is not AudioTrialContext or value.no_game is not True
                or value.portable_ready is not True or type(value.uid) is not int
                or value.uid <= 0 or value.uid != self.user.uid
                or type(value.observed_at) not in (int, float) or not math.isfinite(value.observed_at)
                or not started <= value.observed_at <= ended or ended - value.observed_at > 2
                or value.audio_bdf == value.portable_audio_bdf):
            raise ValueError("fresh independently verified portable context required")
        for text, pattern in ((value.boot_hash, r"[0-9a-f]{64}"),
                (value.topology_hash, r"[0-9a-f]{64}"),
                (value.session_invocation, r"[0-9a-f]{32}"),
                (value.audio_bdf, r"[0-9a-f]{4}:[0-9a-f]{2}:[01][0-9a-f]\.[0-7]"),
                (value.portable_audio_bdf, r"[0-9a-f]{4}:[0-9a-f]{2}:[01][0-9a-f]\.[0-7]"),
                (value.portable_sink, r"[A-Za-z0-9_.:-]{1,256}")):
            if type(text) is not str or re.fullmatch(pattern, text) is None:
                raise ValueError("invalid audio context identity")
        return value

    def __call__(self):
        before = self._context()
        started = self._now()
        result = self.commands.dump(self.user, timeout_seconds=min(2.0, self.deadline - started))
        if result.ok is not True:
            raise OSError("live audio observation unavailable")
        profile = parse_audio_profile_observation(result.output, audio_bdf=before.audio_bdf)
        portable = parse_portable_default(result.output, sink_name=before.portable_sink,
                                          audio_bdf=before.portable_audio_bdf)
        if profile.ready is not True or portable.ready is not True:
            raise ValueError("audio profile or portable default unverified")
        after = self._context()
        ended = self._now()
        if (replace(before, observed_at=after.observed_at) != after or not 0 <= ended - started <= 2):
            raise ValueError("audio context changed or dump expired")
        # Timestamp the collection start, not completion: parsing and context
        # checks must not make an old dump appear newly observed.
        return AudioTrialObservation(before.boot_hash, before.topology_hash, profile,
                                     portable.sink_name, True, True, started)
