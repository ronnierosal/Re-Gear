"""Pure operator experiment: hold approved units stopped, observe, restore.

Adapters own exclusive leases, exact mask identities, crash recovery and prior
state restoration. This coordinator never removes devices or authorizes unplug.
"""
from dataclasses import dataclass
from typing import Callable

from .filter_arm import HolderObservation
from ..domain.filter_arm_sequence import APPROVED_EXPLICIT_RESTARTS

SESSION_UNITS = ("gamescope-session.target", "gamescope-session.service")
AUDIO_SOCKETS = ("pipewire.socket",)
HELD_UNITS = SESSION_UNITS + APPROVED_EXPLICIT_RESTARTS + AUDIO_SOCKETS
STOP_UNITS = SESSION_UNITS + AUDIO_SOCKETS + APPROVED_EXPLICIT_RESTARTS


@dataclass(frozen=True)
class HeldSessionPreflight:
    identity: str
    prior_active: tuple[str, ...]
    idle: bool
    topology_complete: bool
    units_verified: bool
    no_existing_masks: bool

    @property
    def valid(self):
        return (type(self.identity) is str and 0 < len(self.identity) <= 128
                and type(self.prior_active) is tuple
                and all(type(unit) is str and unit in HELD_UNITS for unit in self.prior_active)
                and len(set(self.prior_active)) == len(self.prior_active)
                and all(value is True for value in (self.idle, self.topology_complete,
                                                    self.units_verified, self.no_existing_masks)))


@dataclass(frozen=True)
class HeldSessionResult:
    code: str
    clear_observed: bool = False
    restored: bool = False
    journal_retained: bool = True
    safe_to_unplug: bool = False

    @property
    def ok(self):
        return self.clear_observed and self.restored and not self.journal_retained


class HeldSessionRelease:
    """One-use, bounded sequence over injected ports; no OS operations.

persist_intent must durably record prior state and fixed unit set; mask must
record its owned identity before returning. restore must handle partially
created masks and verify exact prior state. A lost lease must never authorize
removing another owner's mask. prepare_restore establishes independent recovery
before the first mask. All success callbacks must return literal True.
"""
    def __init__(self, *, preflight: Callable, ownership_held: Callable,
                 persist_intent: Callable, prepare_restore: Callable,
                 mask: Callable, masks_verified: Callable, stop: Callable,
                 stopped_verified: Callable, observe: Callable, wait: Callable,
                 restore: Callable, retire: Callable):
        self.preflight, self.ownership_held = preflight, ownership_held
        self.persist_intent, self.prepare_restore = persist_intent, prepare_restore
        self.mask, self.masks_verified, self.stop = mask, masks_verified, stop
        self.stopped_verified, self.observe, self.wait = stopped_verified, observe, wait
        self.restore, self.retire = restore, retire
        self._used = False

    def run(self):
        if self._used:
            return HeldSessionResult("held_release.already_attempted")
        self._used = True
        snapshot = None
        intent_attempted = False
        clear = restored = retired = uncertain = False
        code = "held_release.refused"
        try:
            snapshot = self.preflight()
            if type(snapshot) is not HeldSessionPreflight or not snapshot.valid:
                return HeldSessionResult(code)
            self._owned()
            intent_attempted = True
            self._true(self.persist_intent(snapshot, HELD_UNITS))
            self._owned()
            self._true(self.prepare_restore(snapshot, HELD_UNITS))
            for unit in HELD_UNITS:
                self._owned()
                self._true(self.mask(unit))
            self._owned()
            self._true(self.masks_verified(HELD_UNITS))
            for unit in STOP_UNITS:
                self._owned()
                self._true(self.stop(unit))
            for attempt in range(6):
                self._owned()
                self._true(self.masks_verified(HELD_UNITS))
                self._true(self.stopped_verified(HELD_UNITS))
                observation = self.observe()
                if type(observation) is not HolderObservation or type(observation.complete) is not bool:
                    raise ValueError("invalid observation")
                if type(observation.units) is not tuple or any(type(unit) is not str or not unit for unit in observation.units):
                    raise ValueError("invalid holders")
                if observation.clear:
                    # A scan can outlive the lease or overlap restoration.
                    # Recheck the held state before accepting its clear result.
                    self._owned()
                    self._true(self.masks_verified(HELD_UNITS))
                    self._true(self.stopped_verified(HELD_UNITS))
                    clear = True
                    break
                if attempt < 5:
                    self.wait(1)
            code = "held_release.observed_clear" if clear else "held_release.holders_unverified"
        except Exception:
            uncertain = True
            code = "held_release.unresolved"
        except BaseException:
            # Cancellation/interrupt still restores, but never retires an
            # operation whose execution did not reach a normal outcome.
            uncertain = True
            raise
        finally:
            if intent_attempted:
                try:
                    restored = self.restore(snapshot, HELD_UNITS) is True
                except Exception:
                    restored = False
                # An uncertain write keeps its record even after apparent
                # restoration, for an adapter's explicit reconciliation.
                if restored and not uncertain:
                    try:
                        self._owned()
                        retired = self.retire(snapshot) is True
                    except Exception:
                        retired = False
                if not restored:
                    code = "held_release.restore_unverified"
                elif not retired:
                    code = "held_release.journal_retained"
        return HeldSessionResult(code, clear, restored, not retired)

    def _owned(self):
        self._true(self.ownership_held())

    @staticmethod
    def _true(value):
        if value is not True:
            raise ValueError("required verification unavailable")


class HeldSessionRecovery:
    """Independent recovery policy, with durable revocation before any cleanup.

    Ports must operate on the exact journal identity. Revocation serializes with
    each mutation, never the lifetime of the original worker. The restore port
    removes only recorded masks; it must not perform a generic systemd unmask.
    """
    def __init__(self, *, revoke, load, restore_masks, reload_manager, start,
                 verify, finish):
        self.revoke, self.load = revoke, load
        self.restore_masks, self.reload_manager = restore_masks, reload_manager
        self.start, self.verify, self.finish = start, verify, finish

    def run(self):
        restored = False
        try:
            if self.revoke() is not True:
                return HeldSessionResult('held_recovery.revoke_unverified')
            snapshot = self.load()
            if type(snapshot) is not HeldSessionPreflight or not snapshot.valid:
                return HeldSessionResult('held_recovery.record_invalid')
            if self.restore_masks() is not True:
                return HeldSessionResult('held_recovery.masks_unverified')
            if self.reload_manager() is not True:
                return HeldSessionResult('held_recovery.reload_unverified')
            # The session service can refuse manual starts. Starting its target
            # restores it through dependencies; verify every prior unit after.
            order = ('pipewire.socket', 'pipewire.service', 'wireplumber.service',
                     'gamescope-session.target')
            for unit in order:
                if unit in snapshot.prior_active and self.start(unit) is not True:
                    return HeldSessionResult('held_recovery.start_unverified')
            restored = self.verify(snapshot.prior_active, HELD_UNITS) is True
            if not restored:
                return HeldSessionResult('held_recovery.state_unverified')
            if self.finish() is not True:
                return HeldSessionResult('held_recovery.journal_retained', restored=True)
            return HeldSessionResult('held_recovery.restored', restored=True,
                                     journal_retained=False)
        except Exception:
            return HeldSessionResult('held_recovery.unresolved', restored=restored)
