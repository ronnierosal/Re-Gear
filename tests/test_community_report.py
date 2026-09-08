"""Privacy, failure and consent regressions for the downloadable helper."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('community_report', Path(__file__).resolve().parents[1] / 'scripts/community_report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class CommunityReportTests(unittest.TestCase):
    def test_private_and_unknown_fields_never_pass_through(self):
        secret = 'SECRET /home/private 192.168.1.2 serial=123'
        source = {'snapshot': {
            'game_state': secret, 'gpus': [{'role': 'external', 'present': True,
                'selected_for_render': 1, 'stable_id': secret}],
            'displays': [{'kind': 'internal', 'active': True, 'connector': secret}],
            'gamescope': {'running': True, 'pid': 123, 'evidence': secret},
            'disconnect_readiness': {'ready': True, 'clients': [secret]},
            'host_profile': secret}, 'error': secret}
        result = report.summarize(source)
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(result['game_state'], 'unknown')
        self.assertIsNone(result['gpus'][0]['selected_for_render'])
        self.assertTrue(result['displays'][0]['active'])
        self.assertFalse(result['safe_to_unplug'])

    def test_malformed_shapes_and_arrays_are_bounded(self):
        for payload in (None, [], 3, 'private', {'snapshot': []}):
            self.assertEqual(report.summarize(payload)['game_state'], 'unknown')
        result = report.summarize({'snapshot': {'gpus': [None] * 100}})
        self.assertEqual(len(result['gpus']), 16)

    def test_build_metadata_never_invents_installed_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(report.build_info(root)['version'], 'unknown')
            (root / 'build_info.json').write_text(json.dumps({'schema_version': 1,
                'version': '0.3.56', 'revision': 'a' * 40}))
            self.assertEqual(report.build_info(root)['revision'], 'a' * 40)
            for value in ({'schema_version': True, 'version': '0.3.56'},
                          {'schema_version': 1, 'version': '/home/private', 'revision': ['secret']}):
                (root / 'build_info.json').write_text(json.dumps(value))
                self.assertEqual(report.build_info(root), {'version': 'unknown', 'revision': 'unknown'})

    def test_versions_omit_custom_kernel_suffix_and_os_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'os').write_text('ID=steamos\nVERSION_ID="3.7"\nPRETTY_NAME=private\n')
            (root / 'kernel').write_text('6.11.4-private-machine\n')
            value = report.os_info(root / 'os', root / 'kernel')
            self.assertEqual(value['version'], '3.7')
            self.assertEqual(value['kernel_core_version'], '6.11.4')
            self.assertNotIn('private', json.dumps(value))

    def test_save_requires_exact_consent_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(report.save_reviewed('data', root, 'yes'))
            self.assertEqual(list(root.iterdir()), [])
            name = report.save_reviewed('{"test":true}\n', root, 'save')
            self.assertEqual((root / name).read_bytes(), b'{"test":true}\n')

    def test_save_refuses_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(report, 'datetime') as clock:
                clock.now.return_value.strftime.return_value = 'fixed'
                report.save_reviewed('original', root, 'save')
                with self.assertRaises(FileExistsError):
                    report.save_reviewed('replacement', root, 'save')
            self.assertEqual(next(root.iterdir()).read_text(), 'original')

    def test_root_discovery_does_not_search_other_users(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.assertIsNone(report.find_plugin(home=home))
            root = home / 'homebrew/plugins/Re-Gear'
            (root / 'backend/hdm').mkdir(parents=True)
            (root / 'backend/hdm/cli.py').write_text('')
            (root / 'plugin.json').write_text('{}')
            self.assertEqual(report.find_plugin(home=home), root.resolve())

    def test_no_save_for_noninteractive_run(self):
        with patch.object(sys, 'platform', 'linux'), patch.object(os, 'geteuid', return_value=1000, create=True), \
             patch.object(report, 'find_plugin', return_value=None), patch.object(report, 'os_info', return_value={}), \
             patch.object(sys.stdin, 'isatty', return_value=False), patch.object(report, 'save_reviewed') as save, \
             patch('builtins.print'):
            self.assertEqual(report.main([]), 0)
            save.assert_not_called()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux subprocess pipe selector')
    def test_real_child_failures_timeout_and_output_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / 'backend/hdm'
            module.mkdir(parents=True)
            (module / '__init__.py').write_text('')
            for code, expected in [
                ('print(\'{"snapshot":{"game_state":"idle"}}\')', 'collected'),
                ('print("secret non-json")', 'invalid_output'),
                ('raise RuntimeError("private error")', 'collector_failed'),
                ('import time; time.sleep(5)', 'timed_out'),
                ('print("x" * 300000)', 'output_too_large')]:
                (module / 'cli.py').write_text('def main():\n    ' + code + '\n')
                value, status = report.collect(root, timeout=0.5)
                self.assertEqual(status, expected)
                if expected != 'collected':
                    self.assertEqual(value, {})


if __name__ == '__main__':
    unittest.main()
