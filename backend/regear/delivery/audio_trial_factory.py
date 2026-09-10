"""Construct fresh live audio recovery dependencies without activating a trial."""
from dataclasses import replace
import math
import time

from .audio_profile_trial import AudioProfileTrial
from .audio_profile_trial_state import AudioTrialRecord
from ..adapters.steamos.audio_trial_context import AudioTrialContextSource
from ..adapters.steamos.audio_trial_observer import AudioTrialLiveObserver
from ..adapters.steamos.commands import PipeWireCommandRunner
from ..adapters.steamos.gamescope import GamescopeDiscovery
from ..adapters.steamos.gamescope_user import resolve_gamescope_user


class LiveAudioTrialFactory:
    """Each invocation resolves the current owner and constructs new observers."""
    def __init__(self, store, *, scan_gamescope=None, resolve_user=resolve_gamescope_user,
                 source_factory=AudioTrialContextSource, observer_factory=AudioTrialLiveObserver,
                 clock=time.monotonic, commands=None):
        self.store = store
        self.scan_gamescope = GamescopeDiscovery().scan if scan_gamescope is None else scan_gamescope
        self.resolve_user = resolve_user
        self.source_factory, self.observer_factory = source_factory, observer_factory
        self.clock = clock
        self.commands = PipeWireCommandRunner() if commands is None else commands

    def _now(self, deadline):
        now = self.clock()
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or type(now) not in (int, float) or not math.isfinite(now)
                or now < 0 or not 0 < deadline - now <= 30):
            raise TimeoutError('audio factory deadline expired')
        return now

    def __call__(self, record, deadline):
        started = self._now(deadline)
        if type(record) is not AudioTrialRecord:
            raise ValueError('typed audio trial record required')
        replace(record)  # Revalidate every durable field; never repair it.
        scan = self.scan_gamescope()
        if not scan.ok:
            raise ValueError('Gamescope observation unavailable')
        owner = self.resolve_user(scan)
        if (not owner.ok or owner.context is None
                or type(owner.context.uid) is not int or owner.context.uid != record.uid):
            raise ValueError('current Gamescope owner does not match audio trial')
        if self._now(deadline) < started:
            raise TimeoutError('audio factory clock changed')
        source = self.source_factory(owner.context, record.portable_sink,
                                     deadline=deadline, clock=self.clock)
        observer = self.observer_factory(owner.context, source, deadline=deadline,
                                         commands=self.commands, clock=self.clock)
        return AudioProfileTrial(self.store, owner.context, observer,
                                 commands=self.commands, clock=self.clock)
