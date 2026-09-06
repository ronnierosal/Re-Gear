"""Opt-in fixed Steam launcher; no service activation or shared environment writes.

This entry point requires separately reviewed integration. It never arms a trial.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .gamescope_wrapper import _boot_identity, _load_config
from .portable_trial_launch import live_candidate_from_record
from .portable_trial_store import PortableTrialStore

REAL_STEAM_LAUNCHER = '/usr/lib/steamos/steam-launcher'
TRIAL_KEYS = ('MESA_VK_DEVICE_SELECT', 'MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE')


def current_gamescope_invocation():
    result = subprocess.run(
        ['/usr/bin/systemctl', '--user', 'show', 'gamescope-session.service',
         '--property=InvocationID', '--property=ActiveState'],
        capture_output=True, text=True, timeout=3, check=True,
    )
    if len(result.stdout) > 256:
        raise ValueError('Gamescope service observation exceeds bound')
    fields = dict(line.split('=', 1) for line in result.stdout.splitlines())
    invocation = fields.get('InvocationID', '')
    if fields.get('ActiveState') != 'active' or not re.fullmatch('[0-9a-f]{32}', invocation):
        raise ValueError('active Gamescope invocation unavailable')
    return invocation


def consume_steam_environment(state_root, *, config, environment, raw_boot_id,
                              invocation_reader=current_gamescope_invocation):
    # Never trust selectors from a stale/shared environment file. The candidate
    # starts clean and requires its own exclusive, invocation-bound grant.
    clean = {key: value for key, value in environment.items() if key not in TRIAL_KEYS}
    try:
        claim = PortableTrialStore(state_root).consume_steam()
        if claim is None:
            return clean
        record, expected_invocation = claim
        if invocation_reader() != expected_invocation:
            raise ValueError('Gamescope launch changed')
        _, candidate = live_candidate_from_record(
            record, config=config, argv=(), environment=clean, raw_boot_id=raw_boot_id,
        )
        # Repeat after hardware collection; no stale invocation can pass merely
        # because it was active before the slow read-only probes.
        if invocation_reader() != expected_invocation:
            raise ValueError('Gamescope changed during launch validation')
        return candidate
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return clean


def main():
    environment = dict(os.environ)
    root = Path(environment.get('HDM_STATE_ROOT', ''))
    clean = {key: value for key, value in environment.items() if key not in TRIAL_KEYS}
    try:
        boot, _ = _boot_identity()
        if root.is_absolute():
            clean = consume_steam_environment(root, config=_load_config(root),
                environment=environment, raw_boot_id=boot)
    except (OSError, ValueError):
        pass
    os.execve(REAL_STEAM_LAUNCHER, (REAL_STEAM_LAUNCHER,), clean)
    return 127
