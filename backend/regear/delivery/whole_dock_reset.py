"""Explicit operator repair of a legacy failed reconnect; never device eject.

Physical reset is human-attested, not inferred from sysfs generations. Default
mode is preview. The interactive confirmation expires and binds the exact record
and current observation while exclusive dock admission remains held.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import sys
import time

from ..adapters.steamos.commands import HeldTrialLauncher
from ..adapters.steamos.discovery import SteamOsDiscovery
from ..adapters.steamos.drm import DrmDiscovery
from ..adapters.steamos.gamescope import GamescopeDiscovery
from ..adapters.steamos.gamescope_user import resolve_gamescope_user
from ..adapters.steamos.owner_identity import read_boot_hash
from ..adapters.steamos.whole_dock_topology import resolve_whole_dock
from ..domain.inference import infer_operating_mode
from ..domain.models import Confidence, GameState, OperatingMode
from ..profiles.registry import resolve_runtime_profiles
from .dock_mutation_gate import DockMutationGate
from .whole_dock_claim import WholeDockClaim, WholeDockClaimStore, inner_removal_records_absent
from .held_session_helper import dispatch as user_helper
from .runtime_state import DEFAULT_RUNTIME_STATE_ROOT

ROOT = DEFAULT_RUNTIME_STATE_ROOT
CONFIRM_SECONDS = 120


def no_pending_records(store):
    """Refuse even retained parent-power history; never interpret it as settled."""
    directory = store._directory()
    try:
        names = os.listdir(directory)
        if len(names) > 4096:
            return False
        return not any(name == 'active-transition.json' or name.startswith('dock-power-')
                       for name in names)
    finally:
        os.close(directory)


def observe_restored(binding, store, archive=None):
    def session():
        scan = GamescopeDiscovery().scan()
        process = scan.process
        if (scan.ok is not True or process is None
                or any(type(value) is not int or value <= 0
                       for value in (process.pid, process.start_time_ticks, process.uid))):
            raise ValueError('dock_reset.session_unverified')
        user = resolve_gamescope_user(scan)
        if not user.ok or user.context is None or user.context.uid != process.uid:
            raise ValueError('dock_reset.user_unverified')
        return user.context, (process.pid, process.start_time_ticks, process.uid)

    def snapshot():
        value = SteamOsDiscovery().collect_snapshot()
        if (value.game_state is not GameState.IDLE
                or value.gamescope.running is not True
                or value.gamescope.confidence is not Confidence.VERIFIED
                or not resolve_runtime_profiles(value).exact_host
                or infer_operating_mode(value).mode is not OperatingMode.PORTABLE):
            raise ValueError('dock_reset.portable_unverified')
        return value

    def topology():
        cards = [card for card in DrmDiscovery().scan() if card.boot_vga is False]
        if len(cards) != 1:
            raise ValueError('dock_reset.gpu_unverified')
        value = resolve_whole_dock(cards[0].pci_bdf)
        if value.binding != binding:
            raise ValueError('dock_reset.dock_changed')
        return value

    snapshot()
    first = topology()
    user, session_identity = session()
    boot = read_boot_hash()
    if len(boot) != 64:
        raise ValueError('dock_reset.user_unverified')
    if not no_pending_records(store) or not inner_removal_records_absent():
        raise ValueError('dock_reset.pending_work')
    launcher = HeldTrialLauncher(uid=user.uid, username=user.username)
    audit = launcher.audit_archive(archive) if archive else launcher.call('audit', '0' * 32)
    if audit.get('code') != 'held_helper.settled' or audit.get('settled') is not True:
        raise ValueError('dock_reset.held_recovery_pending')
    snapshot()
    if (topology() != first or read_boot_hash() != boot
            or session() != (user, session_identity)
            or not no_pending_records(store) or not inner_removal_records_absent()):
        raise ValueError('dock_reset.observation_changed')
    return first, user, session_identity, boot


def reconcile_record(*, store, gate, observe, confirm=None, now=time.monotonic,
                     still_confirmed=lambda: True):
    result = {'code': 'dock_reset.refused', 'ok': False,
              'safe_to_unplug': False, 'hardware_write': False}
    try:
        with gate.admit(allow_inhibited=True):
            claim = store.load()
            if type(claim) is not WholeDockClaim or claim.stage != 'reauthorize_intent':
                return result
            proof = observe(claim.binding)
            # The confirmation binds both the exact failed record and the
            # reobserved attachment/session/boot, not merely a stage name.
            digest = hashlib.sha256(store._encode(claim) + repr(proof).encode()).hexdigest()
            if confirm is None:
                return {**result, 'code': 'dock_reset.preview_ready', 'ready': True,
                        'record_digest': digest, 'confirmation_required': True}
            deadline = now() + CONFIRM_SECONDS
            if confirm(digest, CONFIRM_SECONDS) is not True or now() >= deadline:
                return {**result, 'code': 'dock_reset.confirmation_missing_or_expired'}
            def guard():
                fresh = observe(claim.binding)
                return fresh == proof and publication_guard()
            def publication_guard():
                return now() < deadline and still_confirmed() is True
            store.retire_operator_reset(claim, guard, publication_guard=publication_guard)
            return {**result, 'code': 'dock_reset.legacy_hold_archived', 'ok': True}
    except Exception as error:
        code = str(error)
        allowed = {'dock_reset.portable_unverified', 'dock_reset.gpu_unverified',
                   'dock_reset.dock_changed', 'dock_reset.user_unverified', 'dock_reset.session_unverified',
                   'dock_reset.pending_work', 'dock_reset.held_recovery_pending',
                   'dock_reset.observation_changed'}
        return {**result, 'code': code if code in allowed else result['code']}


def terminal_confirmation(digest, seconds):
    if not sys.stdin.isatty():
        return False
    phrase = 'PHYSICAL RESET ' + digest
    print('Confirm only after a fresh full handheld shutdown, enclosure power removal', flush=True)
    print('and cooldown, then normal startup and physical reconnection.', flush=True)
    print('This attests your actions; the software cannot verify the past power cycle.', flush=True)
    print('To archive this exact failed record, type within 120 seconds: ' + phrase, flush=True)
    readable, _, _ = select.select([sys.stdin], [], [], seconds)
    return bool(readable) and sys.stdin.readline(128).strip() == phrase


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reconcile-after-physical-reset', action='store_true')
    parser.add_argument('--audit', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.audit:
        if args.reconcile_after_physical_reset or getattr(os, 'geteuid', lambda: 0)() <= 0:
            parser.error('audit requires the session user')
        result = user_helper('audit', '0' * 32)
        print(json.dumps(result))
        return 0 if result.get('code') == 'held_helper.settled' and result.get('settled') is True else 1
    if getattr(os, 'geteuid', lambda: -1)() != 0:
        print(json.dumps({'code': 'dock_reset.root_required', 'ok': False, 'hardware_write': False}))
        return 1
    if args.reconcile_after_physical_reset:
        # Standalone repair is not compatible with an older running admission
        # reader. This build intentionally ships preview-only until the updated
        # plugin and its live capability handshake are deployed and verified.
        print(json.dumps({'code': 'dock_reset.live_guard_handshake_required',
                          'ok': False, 'hardware_write': False}))
        return 1
    store = WholeDockClaimStore(ROOT)
    result = reconcile_record(store=store, gate=DockMutationGate(ROOT),
        observe=lambda binding: observe_restored(binding, store, str(Path(sys.argv[0]).absolute())),
        confirm=terminal_confirmation if args.reconcile_after_physical_reset else None)
    print(json.dumps(result, separators=(',', ':')))
    return 0 if result.get('ok') or result.get('ready') else 1
