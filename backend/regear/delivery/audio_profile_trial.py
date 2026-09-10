"""Separate, journaled audio-profile off/restore controller; not RPC activated.

Caller supplies a supervised operation and a fresh trusted observation adapter.
An off profile is never evidence that audio descriptors have been released.
"""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
import math
import time

from ..adapters.steamos.audio_profile_observation import AudioProfileObservation
from ..adapters.steamos.commands import PipeWireCommandRunner
from ..adapters.steamos.owner_identity import read_boot_hash
from ..ports.audio_recovery import AudioRecoveryBlocked
from .audio_profile_trial_state import (AudioTrialBootVerdict, AudioTrialRecord,
                                        AudioTrialPhase as Phase, TERMINAL_PHASES,
                                        decide_trial_boot)


@dataclass(frozen=True)
class AudioTrialObservation:
    boot_hash: str
    topology_hash: str
    profile: AudioProfileObservation
    portable_sink: str
    no_game: bool
    portable_ready: bool
    observed_at: float


@dataclass(frozen=True)
class AudioTrialResult:
    record: AudioTrialRecord
    resources_released: bool = False
    disconnect_clearance: bool = False


class AudioProfileTrial:
    def __init__(self, store, user, observe, *, commands=None, clock=time.monotonic, wait=time.sleep):
        self.store, self.user, self.observe = store, user, observe
        self.commands = PipeWireCommandRunner() if commands is None else commands
        self.clock, self.wait = clock, wait

    def _now(self, deadline):
        now = self.clock()
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or type(now) not in (int, float) or not math.isfinite(now)
                or now < 0 or not 0 < deadline - now <= 30):
            raise TimeoutError("audio trial deadline expired")
        return now

    def _fresh(self, record, deadline):
        before = self._now(deadline)
        value = self.observe()
        after = self._now(deadline)
        if (type(value) is not AudioTrialObservation or value.no_game is not True
                or value.portable_ready is not True or type(value.profile) is not AudioProfileObservation
                or value.profile.ready is not True
                or type(value.observed_at) not in (int, float) or not math.isfinite(value.observed_at)
                or not before <= value.observed_at <= after or after - value.observed_at > 2
                or (value.boot_hash, value.topology_hash, value.profile.device_bdf, value.portable_sink)
                    != (record.boot_hash, record.topology_hash, record.audio_bdf, record.portable_sink)
                or self.user.uid != record.uid):
            raise ValueError("fresh portable audio attachment evidence required")
        return value.profile

    @staticmethod
    def _advance(tx, record, phase):
        updated = replace(record, revision=record.revision + 1, phase=phase)
        tx.save(record, updated)
        return updated

    def _recoverable(self, tx, operation):
        # A failed fsync may already have published the requested revision.
        # Re-read actual durable state instead of guessing a CAS revision.
        latest = tx.read(operation)
        if latest.phase not in TERMINAL_PHASES and latest.phase is not Phase.RECOVERY_REQUIRED:
            self._advance(tx, latest, Phase.RECOVERY_REQUIRED)

    @staticmethod
    def _original(profile, record):
        matches = [p for p in profile.profiles if p.name == record.original_profile and p.available == "yes"]
        if len(matches) != 1:
            raise ValueError("original profile is not currently restorable")
        return matches[0]

    def _set(self, profile, target, deadline):
        remaining = deadline - self._now(deadline)
        result = self.commands.set_profile(self.user, profile.device_id, target.index,
                                          timeout_seconds=min(5.0, remaining))
        if result.ok is not True:
            raise OSError("audio profile command failed or is uncertain")

    def _wait_for(self, record, name, deadline):
        while True:
            profile = self._fresh(record, deadline)
            if profile.current_profile.name == name:
                return
            if profile.current_profile.name not in ("off", record.original_profile):
                raise ValueError("audio profile changed externally")
            self.wait(min(0.1, deadline - self._now(deadline)))

    def off(self, operation, *, boot_hash, topology_hash, audio_bdf, portable_sink, deadline):
        # A temporary identity object allows fresh source validation without
        # persisting a guessed original profile. It is never sent to the store.
        identity = AudioTrialRecord(operation, boot_hash, topology_hash, audio_bdf,
                                    "unobserved", portable_sink, self.user.uid)
        with self.store.transaction() as tx:
            profile = self._fresh(identity, deadline)
            if profile.current_profile.name == "off" or profile.current_profile.available != "yes":
                raise ValueError("original audio profile unavailable")
            record = replace(identity, original_profile=profile.current_profile.name)
            # Exclusive create is intentionally outside failure recovery: an
            # existing operation may belong to a prior run and must not replay.
            tx.create(record)
            try:
                record = self._advance(tx, record, Phase.OFF_REQUESTED)
                fresh = self._fresh(record, deadline)
                self._original(fresh, record)
                if fresh.current_profile.name != record.original_profile:
                    raise ValueError("audio profile changed before off")
                self._set(fresh, fresh.off_profile, deadline)
                self._wait_for(record, "off", deadline)
                record = self._advance(tx, record, Phase.OFF_OBSERVED)
                return AudioTrialResult(record)
            except BaseException:
                self._recoverable(tx, operation)
                raise

    def restore(self, operation, *, deadline):
        with self.store.transaction() as tx:
            return self._restore_transaction(tx, operation, deadline=deadline)

    def _restore_transaction(self, tx, operation, *, deadline):
        record = tx.read(operation)
        try:
            fresh = self._fresh(record, deadline)
            self._original(fresh, record)
            if fresh.current_profile.name == record.original_profile:
                if record.phase is not Phase.RESTORED:
                    record = self._advance(tx, record, Phase.RESTORED)
                return AudioTrialResult(record)
            if record.phase is Phase.RESTORED or fresh.current_profile.name != "off":
                raise ValueError("closed trial or conflicting audio profile")
            record = self._advance(tx, record, Phase.RESTORE_REQUESTED)
            fresh = self._fresh(record, deadline)
            target = self._original(fresh, record)
            if fresh.current_profile.name == "off":
                self._set(fresh, target, deadline)
            elif fresh.current_profile.name != record.original_profile:
                raise ValueError("audio profile changed before restoration")
            self._wait_for(record, record.original_profile, deadline)
            record = self._advance(tx, record, Phase.RESTORED)
            return AudioTrialResult(record)
        except BaseException:
            self._recoverable(tx, operation)
            raise



class AudioProfileRecovery:
    """Long-lived guard; factory builds fresh bounded observations per recovery.

    The factory receives the pending record only as a requested identity to
    revalidate, and the absolute deadline for this attempt. It must construct
    a fresh AudioProfileTrial backed by this same journal.
    """
    def __init__(self, store, trial_factory, *, clock=time.monotonic,
                 read_boot_hash=read_boot_hash):
        self.store, self.trial_factory, self.clock = store, trial_factory, clock
        # The live boot identity, read fresh per recovery. It decides only
        # whether a pending record still belongs to this boot; it is never
        # substituted for the record's own bound identity, which every
        # observation is still checked against in `_fresh`.
        self.read_boot_hash = read_boot_hash

    @staticmethod
    def _retire(tx, pending):
        """End a record whose boot is gone, without restoring anything.

        The record is not repaired and nothing is issued to the audio device:
        the profile is left exactly as the reboot found it. Only the durable
        claim is closed, so it stops refusing transitions it can no longer be
        revalidated for. A reboot has already released every audio descriptor
        the previous boot held, which is the ownership question this record
        existed to answer; what it cannot answer is whether that boot left the
        profile off, and `audio.recovery_abandoned` is how the operator is told
        to look rather than being told nothing.
        """
        AudioProfileTrial._advance(tx, pending, Phase.ABANDONED)
        if tx.pending() is not None:
            raise AudioRecoveryBlocked("audio.recovery_unverified")

    def recovery_status(self):
        try:
            with self.store.transaction() as tx:
                return "audio.recovery_required" if tx.pending() is not None else ""
        except (OSError, ValueError, RuntimeError):
            return "audio.recovery_unavailable"

    @contextmanager
    def transition_guard(self, *, recover=False):
        # Hold the same durable lock used by off() across the presentation body.
        # A second process cannot arm audio after a clear check but before restart.
        with ExitStack() as stack:
            try:
                tx = stack.enter_context(self.store.transaction())
            except (OSError, ValueError, RuntimeError) as exc:
                raise AudioRecoveryBlocked("audio.recovery_unavailable") from exc
            try:
                pending = tx.pending()
                if pending is not None:
                    if recover is not True:
                        raise AudioRecoveryBlocked("audio.recovery_required")
                    # A record from another boot can never be revalidated: every
                    # observation is bound to `record.boot_hash`, so restoration
                    # would refuse forever and the record would refuse every
                    # transition and every new trial with it. Retire it and still
                    # refuse this attempt -- the way out is the next one, not this
                    # one. See `decide_trial_boot`.
                    if decide_trial_boot(pending, self.read_boot_hash()) is AudioTrialBootVerdict.DIFFERENT_BOOT:
                        self._retire(tx, pending)
                        raise AudioRecoveryBlocked("audio.recovery_abandoned")
                    # The controller still requires fresh Portable/internal-default
                    # evidence throughout restoration; the saved record is not authority.
                    now = self.clock()
                    if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
                        raise ValueError("invalid recovery clock")
                    deadline = now + 10
                    trial = self.trial_factory(pending, deadline)
                    if type(trial) is not AudioProfileTrial or trial.store is not self.store:
                        raise ValueError("fresh trial must use the guarded journal")
                    trial._restore_transaction(tx, pending.operation, deadline=deadline)
                    if tx.read(pending.operation).phase is not Phase.RESTORED or tx.pending() is not None:
                        raise AudioRecoveryBlocked("audio.recovery_unverified")
            except AudioRecoveryBlocked:
                raise
            except (OSError, ValueError, RuntimeError) as exc:
                raise AudioRecoveryBlocked("audio.recovery_unavailable") from exc
            yield
