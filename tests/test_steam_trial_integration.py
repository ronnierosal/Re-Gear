import sys
import unittest
import os
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from hdm.delivery.steam_trial_integration import (
    SteamIntegrationEvidence, UNIT_SHA256, LAUNCHER_SHA256, OS_UNIT, OS_LAUNCHER,
    plan_integration, rollback_dropin,
)


class SteamIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.evidence = SteamIntegrationEvidence(OS_UNIT, UNIT_SHA256, LAUNCHER_SHA256,
            (OS_LAUNCHER,), (), (), True, True, True)
        self.args = dict(plugin_root='/plugin', state_root='/home/deck/.local/share/hdm',
            shim_bytes=b'#!/usr/bin/python3\n# Re-Gear supervised Steam trial shim\n',
            actual_dropin=None, evidence=self.evidence)

    def test_exact_optional_integration_and_rollback(self):
        plan = plan_integration(**self.args)
        self.assertIn('ExecStart=\nExecStart=/usr/bin/env PATH=/plugin/bin:/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin:/usr/lib/steamos steam-launcher\n', plan.after)
        self.assertIsNone(rollback_dropin(plan, current=plan.after))
        with self.assertRaises(ValueError):
            rollback_dropin(plan, current=plan.after + '# user modification')

    def test_changed_os_command_environment_or_topology_blocks(self):
        for changes in (dict(unit_sha256='a'*64), dict(launcher_sha256='a'*64),
                dict(fragment_path='/etc/systemd/user/steam-launcher.service'),
                dict(effective_argv=(OS_LAUNCHER, '--custom')),
                dict(other_dropins=('custom.conf',)), dict(environment_overrides=('DRI_PRIME',)),
                dict(idle_verified=False), dict(portable_verified=None),
                dict(egpu_absent_verified=False)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                plan_integration(**dict(self.args, evidence=replace(self.evidence, **changes)))

    def test_modified_managed_content_refused(self):
        with self.assertRaises(ValueError):
            plan_integration(**dict(self.args, actual_dropin='foreign'))

    def test_installed_exact_plan_is_idempotent(self):
        plan = plan_integration(**self.args)
        repeated = plan_integration(**dict(self.args, actual_dropin=plan.after,
            evidence=replace(self.evidence, effective_argv=('/usr/bin/env',
                'PATH=/plugin/bin:/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin:/usr/lib/steamos', 'steam-launcher'))))
        self.assertEqual(repeated.before, repeated.after)

    def test_shim_changes_invalidate_fingerprint(self):
        first = plan_integration(**self.args)
        changed = plan_integration(**dict(self.args, shim_bytes=self.args['shim_bytes'] + b'# changed\n'))
        self.assertNotEqual(first.fingerprint, changed.fingerprint)

    def test_unsafe_paths_and_non_linux_shims_rejected(self):
        for changes in (dict(plugin_root='/plugin/../other'), dict(plugin_root='/space path'),
                dict(state_root='/a//b'), dict(shim_bytes=b'#!/usr/bin/python3\r\n')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                plan_integration(**dict(self.args, **changes))

    @unittest.skipUnless(os.name == 'posix', 'Linux executable search required')
    def test_missing_plugin_shim_falls_back_to_native_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / 'plugin'
            native = root / 'native'
            plugin.mkdir()
            native.mkdir()
            for parent, result in ((plugin, 'trial'), (native, 'native')):
                launcher = parent / 'steam-launcher'
                launcher.write_text('#!/bin/sh\nprintf ' + result)
                launcher.chmod(0o755)
            command = ['/usr/bin/env', f'PATH={plugin}:{native}:/usr/bin:/bin', 'steam-launcher']
            self.assertEqual(subprocess.check_output(command), b'trial')
            (plugin / 'steam-launcher').unlink()
            self.assertEqual(subprocess.check_output(command), b'native')
