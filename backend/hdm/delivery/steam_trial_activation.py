"""Fixed, opt-in Steam unit preparation using existing approval/rollback owner."""
from __future__ import annotations

import hashlib
import re
import shlex
from pathlib import Path

from .gamescope_integration import GamescopeIntegrationStore
from .steam_trial_integration import OS_UNIT, OS_LAUNCHER, UNIT_SHA256, LAUNCHER_SHA256, DROPIN_NAME, steam_launch_argv
from ..ports.presentation_activation import UserServiceOperation

ROUTING_KEYS = frozenset(('DRI_PRIME', 'VK_ICD_FILENAMES', 'VK_DRIVER_FILES',
    'VK_LOADER_DRIVERS_SELECT', 'VK_LOADER_DRIVERS_DISABLE', 'VK_LOADER_LAYERS_DISABLE',
    'VK_LAYER_PATH', 'VK_INSTANCE_LAYERS', 'NODEVICE_SELECT',
    'MESA_VK_DEVICE_SELECT', 'MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE'))


class SteamTrialIntegrationStore(GamescopeIntegrationStore):
    SERVICE = 'steam-launcher.service'
    SHIM_NAME = 'steam-launcher'
    SHIM_MARKER = 'Re-Gear supervised Steam trial shim'
    DROPIN_NAME = DROPIN_NAME

    def __init__(self, *, commands, os_root=Path('/'), **kwargs):
        super().__init__(**kwargs)
        self._commands = commands
        self._os_root = os_root

    def expected_text(self):
        state = self._path_text(self._state_root)
        return ('# Managed experimental Re-Gear Steam trial.\n[Service]\n'
                'ExecStart=\n' + f'ExecStart={self._launch_command()}\n'
                f'Environment="HDM_STATE_ROOT={state}"\n')

    def _launch_command(self):
        # An older package/uninstalled plugin has no shim; fixed PATH then finds
        # the native OS launcher. The trial shim itself execs its absolute path.
        return ' '.join(steam_launch_argv(self._path_text(self._plugin_root)))

    def _os_path(self, value):
        return self._os_root / value.lstrip('/')

    def _inspect(self):
        result = self._commands.run(UserServiceOperation.INSPECT_STEAM_UNIT,
                                    uid=self.user.uid, username=self.user.username)
        if not result.ok or len(result.output) > 4096:
            raise ValueError('Steam unit observation unavailable')
        fields = {}
        for line in result.output.splitlines():
            key, value = line.split('=', 1)
            if key in fields:
                raise ValueError('duplicate Steam unit property')
            fields[key] = value
        if (set(fields) != {'LoadState', 'FragmentPath', 'DropInPaths', 'ExecStart', 'Environment'}
                or fields['LoadState'] != 'loaded' or fields['FragmentPath'] != OS_UNIT):
            raise ValueError('Steam unit identity changed')
        return fields

    def _command_matches(self, value, path, argv=None):
        # systemd show uses this fixed no-argument serialization. Never parse or
        # execute caller commands; extra commands/arguments fail closed.
        prefix = '{ path=' + path + ' ; argv[]=' + (argv or path) + ' ; '
        return value.startswith(prefix) and value.count('{') == 1 and value.count('}') == 1 and value.endswith(' }')

    def _conflicts(self):
        for filename, expected in ((OS_UNIT, UNIT_SHA256), (OS_LAUNCHER, LAUNCHER_SHA256)):
            text = self._read_required(self._os_path(filename))
            if hashlib.sha256(text.encode()).hexdigest() != expected:
                raise ValueError('Steam OS launch lineage changed')
        roots = [self._dropin_root, self.user.runtime_directory / 'systemd/user/steam-launcher.service.d']
        roots.extend(self._os_path(prefix + '/systemd/user/steam-launcher.service.d')
                     for prefix in ('etc', 'run', 'usr/lib', 'usr/local/lib'))
        # Generic service drop-ins can affect this unit as well.
        roots.extend(self._os_path(prefix + '/systemd/user/service.d') for prefix in ('etc', 'run', 'usr/lib'))
        roots.append(self.user.home / '.config/systemd/user/service.d')
        for root in roots:
            if root.is_symlink():
                raise ValueError('Steam drop-in directory is a symlink')
            if root.exists():
                for path in root.glob('*.conf'):
                    if path != self._target:
                        return ('steam_unit_override',)
        fields = self._inspect()
        paths = shlex.split(fields['DropInPaths'])
        if any(value != self._target.as_posix() for value in paths):
            return ('steam_unit_override',)
        if not (self._command_matches(fields['ExecStart'], OS_LAUNCHER)
                or self._command_matches(fields['ExecStart'], '/usr/bin/env', self._launch_command())):
            return ('steam_command_override',)
        environment = shlex.split(fields['Environment'])
        # No manager/config routing overrides are admitted to this experiment.
        envfile = self._read_required(self.user.runtime_directory / 'gamescope-environment')
        original_path = (self._shim.parent.as_posix()
                         + ':/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin')
        if [line for line in envfile.splitlines() if line.startswith('PATH=')] != ['PATH=' + original_path]:
            return ('steam_path_override',)
        environment.extend(envfile.splitlines())
        for entry in environment:
            key, _, value = entry.partition('=')
            if key in ROUTING_KEYS:
                return ('steam_routing_override',)
            if key == 'HDM_STATE_ROOT' and value != self._state_root.as_posix():
                return ('steam_state_override',)
        return ()

    def activation_fingerprint(self):
        if self._conflicts():
            raise ValueError('Steam integration conflict')
        digest = hashlib.sha256(super().activation_fingerprint().encode())
        for name in ('steam_trial_wrapper.py', 'portable_trial_store.py', 'portable_trial_launch.py'):
            value = self._read_required(self._plugin_root / 'backend/hdm/delivery' / name)
            digest.update(value.encode())
        digest.update(UNIT_SHA256.encode())
        digest.update(LAUNCHER_SHA256.encode())
        return digest.hexdigest()

    def verify_effective(self):
        if not self.status().ready:
            return False
        fields = self._inspect()
        return (shlex.split(fields['DropInPaths']) == [self._target.as_posix()]
                and self._command_matches(fields['ExecStart'], '/usr/bin/env', self._launch_command()))
