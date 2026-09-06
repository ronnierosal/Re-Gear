import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from hdm.delivery.steam_trial_activation import SteamTrialIntegrationStore, OS_UNIT, OS_LAUNCHER
from hdm.ports.presentation_activation import GamescopeUserContext


class SteamActivationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir()
        (self.runtime / 'gamescope-environment').write_text('DISPLAY=:0\n')
        self.plugin = self.root / 'plugin'
        self.shim = self.plugin / 'bin/steam-launcher'
        self.shim.parent.mkdir(parents=True)
        (self.runtime / 'gamescope-environment').write_text('DISPLAY=:0\nPATH='
            + self.shim.parent.as_posix()
            + ':/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin\n')
        self.shim.write_bytes(b'#!/usr/bin/python3\n# Re-Gear supervised Steam trial shim\n')
        self.shim.chmod(0o755)
        for name in ('steam_trial_wrapper.py', 'portable_trial_store.py', 'portable_trial_launch.py'):
            p = self.plugin / 'backend/hdm/delivery' / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('# fixture\n')
        for value in (OS_UNIT, OS_LAUNCHER):
            p = self.root / value.lstrip('/')
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'fixture\n')
        for name in ('UNIT_SHA256', 'LAUNCHER_SHA256'):
            p = patch('hdm.delivery.steam_trial_activation.' + name,
                      hashlib.sha256(b'fixture\n').hexdigest())
            p.start()
            self.addCleanup(p.stop)
        uid = getattr(os, 'getuid', lambda: 1000)()
        gid = getattr(os, 'getgid', lambda: 1000)()
        user = GamescopeUserContext('deck', uid, gid, self.home, self.runtime, self.runtime / 'bus')
        self.loaded = False
        self.environment = ''
        self.extra_argv = ''
        self.store = SteamTrialIntegrationStore(plugin_root=self.plugin, user=user,
            commands=SimpleNamespace(run=lambda *a, **k: self.observation()),
            os_root=self.root, effective_uid=lambda: 0, set_owner=lambda *a: None)

    def observation(self):
        command = '/usr/bin/env' if self.loaded else OS_LAUNCHER
        argv = self.store._launch_command() if self.loaded else OS_LAUNCHER
        dropin = self.store.target.as_posix() if self.loaded else ''
        return SimpleNamespace(ok=True, output=f'LoadState=loaded\nFragmentPath={OS_UNIT}\n'
            f'DropInPaths={dropin}\nExecStart={{ path={command} ; argv[]={argv}{self.extra_argv} ; ignore_errors=no ; }}\n'
            f'Environment={self.environment}')

    def test_preparation_readback_and_exact_deactivation(self):
        fingerprint = self.store.activation_fingerprint()
        self.assertTrue(self.store.activate().ok)
        self.assertEqual(self.store.activation_fingerprint(), fingerprint)
        self.assertFalse(self.store.verify_effective())
        self.loaded = True
        self.assertTrue(self.store.verify_effective())
        self.assertFalse(self.store.activate().changed)
        self.assertTrue(self.store.deactivate().changed)
        self.assertFalse(self.store.target.exists())

    def test_foreign_or_modified_dropin_not_overwritten(self):
        self.assertTrue(self.store.activate().ok)
        self.store.target.write_text('# user modification')
        self.assertFalse(self.store.activate().ok)
        self.assertFalse(self.store.deactivate().changed)
        self.assertEqual(self.store.target.read_text(), '# user modification')

    def test_extra_os_dropin_blocks(self):
        root = self.root / 'etc/systemd/user/steam-launcher.service.d'
        root.mkdir(parents=True)
        (root / 'override.conf').write_text('[Service]\nExecStart=/other')
        self.assertFalse(self.store.activate().ok)
        self.assertFalse(self.store.target.exists())

    def test_environment_and_argument_overrides_block(self):
        self.environment = 'MESA_VK_DEVICE_SELECT=custom'
        self.assertFalse(self.store.activate().ok)
        self.environment = ''
        self.extra_argv = ' --custom'
        self.assertFalse(self.store.activate().ok)

    def test_os_update_requires_review(self):
        (self.root / OS_LAUNCHER.lstrip('/')).write_text('changed')
        self.assertFalse(self.store.activate().ok)

    def test_shared_environment_routing_override_blocks(self):
        (self.runtime / 'gamescope-environment').write_text('DRI_PRIME=1\n')
        self.assertFalse(self.store.activate().ok)

    def test_wrapper_changes_invalidate_fingerprint(self):
        before = self.store.activation_fingerprint()
        (self.plugin / 'backend/hdm/delivery/steam_trial_wrapper.py').write_text('# changed\n')
        self.assertNotEqual(before, self.store.activation_fingerprint())
