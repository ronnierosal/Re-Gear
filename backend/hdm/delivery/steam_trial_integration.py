"""Pure review plan for a separate, reversible supervised Steam launch shim.

No filesystem/service mutation occurs here. Activation remains separately gated.
"""
from dataclasses import dataclass
import hashlib
import re

OS_LAUNCHER = '/usr/lib/steamos/steam-launcher'
OS_UNIT = '/usr/lib/systemd/user/steam-launcher.service'
UNIT_SHA256 = 'db9a4802fc1e4829130e3a69b42b836cfabf81021c0e9dcb1a2787d875f34201'
LAUNCHER_SHA256 = 'bc2e16bbff2357091f04b7049b9fa40d3fc8d75e909c09310ebe39acc5c09621'
DROPIN_NAME = '90-regear-supervised-steam-trial.conf'


def steam_launch_argv(plugin_root):
    return ('/usr/bin/env',
            f'PATH={plugin_root}/bin:/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin:/usr/lib/steamos',
            'steam-launcher')


@dataclass(frozen=True)
class SteamIntegrationEvidence:
    fragment_path: str
    unit_sha256: str
    launcher_sha256: str
    effective_argv: tuple[str, ...]
    other_dropins: tuple[str, ...]
    environment_overrides: tuple[str, ...]
    idle_verified: bool
    portable_verified: bool
    egpu_absent_verified: bool


@dataclass(frozen=True)
class SteamIntegrationPlan:
    relative_path: str
    before: str | None
    after: str
    fingerprint: str


def plan_integration(*, plugin_root: str, state_root: str, shim_bytes: bytes,
                     actual_dropin: str | None, evidence: SteamIntegrationEvidence):
    """Only the observed OS lineage and detached idle preparation are admitted."""
    for value in (plugin_root, state_root):
        if (not re.fullmatch(r'/[A-Za-z0-9_.@+/-]+', value)
                or any(part in ('.', '..', '') for part in value[1:].split('/'))):
            raise ValueError('unsafe integration path')
    if (evidence.fragment_path != OS_UNIT or evidence.unit_sha256 != UNIT_SHA256
            or evidence.launcher_sha256 != LAUNCHER_SHA256 or evidence.other_dropins
            or evidence.environment_overrides):
        raise ValueError('Steam launch integration requires review')
    if not all(value is True for value in (evidence.idle_verified,
               evidence.portable_verified, evidence.egpu_absent_verified)):
        raise ValueError('detached idle Portable preparation required')
    if (len(shim_bytes) > 16384 or not shim_bytes.startswith(b'#!/usr/bin/python3\n')
            or b'\r' in shim_bytes or b'Re-Gear supervised Steam trial shim' not in shim_bytes):
        raise ValueError('Steam trial shim unavailable')
    launch_argv = steam_launch_argv(plugin_root)
    expected = ('# Managed experimental Re-Gear Steam trial.\n[Service]\n'
                'ExecStart=\n' + f'ExecStart={" ".join(launch_argv)}\n'
                f'Environment="HDM_STATE_ROOT={state_root}"\n')
    if actual_dropin not in (None, expected):
        raise ValueError('managed Steam drop-in changed')
    expected_argv = (OS_LAUNCHER,) if actual_dropin is None else launch_argv
    if evidence.effective_argv != expected_argv:
        raise ValueError('effective Steam command changed')
    fingerprint = hashlib.sha256(shim_bytes + b'\0' + expected.encode()
                                 + b'\0' + UNIT_SHA256.encode()
                                 + b'\0' + LAUNCHER_SHA256.encode()).hexdigest()
    return SteamIntegrationPlan('steam-launcher.service.d/' + DROPIN_NAME,
                                actual_dropin, expected, fingerprint)


def rollback_dropin(plan: SteamIntegrationPlan, *, current: str):
    """Exact compare-before-restore; never overwrite subsequent user changes."""
    if current != plan.after:
        raise ValueError('Steam drop-in changed since preparation')
    return plan.before
