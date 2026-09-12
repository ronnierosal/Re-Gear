"""Operator completion reconciliation: record only, no kernel writes.

Keep the original plugin instance alive. After successful reconciliation its
normal reconnect action still verifies the original function identities. This
helper neither reconstructs those identities nor grants physical unplug clearance.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from ..adapters.steamos.discovery import SteamOsDiscovery
from ..adapters.steamos.gamescope import GamescopeDiscovery
from ..adapters.steamos.gamescope_user import resolve_gamescope_user
from ..adapters.steamos.commands import HeldTrialLauncher
from ..adapters.steamos.whole_dock_topology import resolve_deauthorized_transport
from ..domain.inference import infer_operating_mode
from ..domain.models import GameState, OperatingMode
from .dock_mutation_gate import DockMutationGate
from .whole_dock_claim import WholeDockClaimStore
from .held_session_helper import dispatch as user_helper

ROOT = Path('/var/lib/handheld-dock-mode')


def observe_down(binding, generation):
    transport = resolve_deauthorized_transport(binding, generation)
    user = resolve_gamescope_user(GamescopeDiscovery().scan())
    if not user.ok or user.context is None:
        raise ValueError('dock_completion.user_unverified')
    snapshot = SteamOsDiscovery().collect_snapshot()
    if (snapshot.game_state is not GameState.IDLE
            or infer_operating_mode(snapshot).mode is not OperatingMode.PORTABLE):
        raise ValueError('dock_completion.portable_unverified')
    if os.geteuid() == user.context.uid:
        audit = user_helper('audit', '0' * 32)
    else:
        audit = HeldTrialLauncher(uid=user.context.uid,
            username=user.context.username).audit_archive(str(Path(sys.argv[0]).absolute()))
    if audit.get('code') != 'held_helper.settled' or audit.get('settled') is not True:
        raise ValueError('dock_completion.held_recovery_pending')
    if (resolve_deauthorized_transport(binding, generation) != transport
            or resolve_gamescope_user(GamescopeDiscovery().scan()) != user):
        raise ValueError('dock_completion.observation_changed')
    snapshot = SteamOsDiscovery().collect_snapshot()
    if (snapshot.game_state is not GameState.IDLE
            or infer_operating_mode(snapshot).mode is not OperatingMode.PORTABLE):
        raise ValueError('dock_completion.portable_changed')
    return transport, user.context


def complete_record(*, binding, generation, confirmed, store, gate, observe):
    result = {'code': 'dock_completion.refused', 'ok': False,
              'safe_to_unplug': False, 'hardware_write': False}
    try:
        with gate.admit(allow_inhibited=True):
            claim = store.load()
            if (claim is None or claim.stage != 'tunnel_remove_intent'
                    or claim.binding != binding or claim.generation != generation):
                return result
            proof = observe(binding, generation)
            if confirmed is not True:
                return {**result, 'code': 'dock_completion.ready', 'ready': True}
            store.confirm_software_down(claim,
                lambda: observe(binding, generation) == proof)
            return {**result, 'code': 'dock_completion.record_completed', 'ok': True}
    except Exception:
        return result


def main(*, expected_binding, expected_generation):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm', action='store_true',
        help='Complete only the matching verified-down record; no hardware write.')
    parser.add_argument('--observe', action='store_true',
        help='Read-only hardware/session check; does not inspect or change the root claim.')
    parser.add_argument('--audit', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.audit:
        if args.confirm or args.observe or getattr(os, 'geteuid', lambda:0)() <= 0:
            parser.error('audit requires the session user and no other operation')
        result = user_helper('audit', '0' * 32)
        print(json.dumps(result, separators=(',', ':')))
        return 0 if result.get('code') == 'held_helper.settled' and result.get('settled') is True else 1
    if args.observe:
        if args.confirm:
            parser.error('--observe and --confirm cannot be combined')
        try:
            observe_down(expected_binding, expected_generation)
            print(json.dumps({'code':'dock_completion.observation_ready', 'hardware_write':False}))
            return 0
        except Exception:
            print(json.dumps({'code':'dock_completion.observation_unavailable', 'hardware_write':False}))
            return 1
    if getattr(os, 'geteuid', lambda:-1)() != 0:
        print(json.dumps({'code':'dock_completion.root_required', 'ok':False}))
        return 1
    result = complete_record(binding=expected_binding, generation=expected_generation,
        confirmed=args.confirm, store=WholeDockClaimStore(ROOT),
        gate=DockMutationGate(ROOT), observe=observe_down)
    print(json.dumps(result, separators=(',', ':')))
    return 0 if result.get('ok') or result.get('ready') else 1
