"""Fixed launcher argv tests; no subprocess or hardware actions."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.adapters.steamos import commands as m


class HeldTrialLauncherTests(unittest.TestCase):
    token = 'a' * 32

    def setUp(self):
        root = patch.object(m.os, 'geteuid', return_value=0, create=True)
        root.start()
        self.addCleanup(root.stop)
        self.launcher = m.HeldTrialLauncher(uid=1000, username='deck')
        self.pins = dict(units_device=1, units_inode=2, lease_device=1,
                         lease_inode=3, boot_identity='b' * 64)

    def test_root_only_and_strict_user_identity(self):
        with patch.object(m.os, 'geteuid', return_value=1000):
            with self.assertRaises(ValueError):
                m.HeldTrialLauncher(uid=1000, username='deck')
        for uid, username in ((True, 'deck'), (0, 'deck'), (1000, 'deck;bad'),
                              (1000, '--root'), ('1000', 'deck')):
            with self.subTest(uid=uid, username=username):
                with self.assertRaises(ValueError):
                    m.HeldTrialLauncher(uid=uid, username=username)

    def test_restore_uses_fixed_user_helper_and_isolated_python(self):
        argv = self.launcher.argv('restore', self.token, self.pins)
        self.assertEqual(argv[:4], ('/usr/bin/runuser', '-u', 'deck', '--'))
        self.assertIn('/usr/bin/python3', argv)
        self.assertIn('-I', argv)
        helper = str(Path('/run/user/1000/regear-held') / self.token /
                     'code/regear/delivery/held_session_helper.py')
        self.assertIn(helper, argv)
        self.assertEqual(json.loads(argv[-1]), self.pins)
        self.assertEqual(argv[-4:-1], ('restore', self.token, '--pins'))

    def test_bad_verbs_tokens_and_pins_never_spawn(self):
        with patch.object(m.subprocess, 'run') as run:
            requests = [('exec', self.token, self.pins),
                        ('hold', '../bad', self.pins),
                        ('prepare', self.token, self.pins),
                        ('restore', self.token, None)]
            for pins in ({**self.pins, 'extra': 1}, {**self.pins, 'units_inode': True},
                         {**self.pins, 'lease_device': -1},
                         {**self.pins, 'boot_identity': '%n'}):
                requests.append(('restore', self.token, pins))
            for request in requests:
                with self.subTest(request=request):
                    self.assertEqual(self.launcher.call(*request)['code'], 'held_helper.unavailable')
            run.assert_not_called()

    def test_invalid_output_and_timeout_are_refused(self):
        for output in (b'[]', b'x' * 16385, b'invalid'):
            with patch.object(m.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout=output)):
                self.assertIn(self.launcher.call('status', self.token, self.pins)['code'],
                              ('held_helper.output_invalid', 'held_helper.unavailable'))
        with patch.object(m.subprocess, 'run', side_effect=m.subprocess.TimeoutExpired('helper', 70)):
            self.assertEqual(self.launcher.call('hold', self.token, self.pins)['code'],
                             'held_helper.unavailable')

    def test_fixed_watchdog_dependencies_retry_and_activation(self):
        with patch.object(m.subprocess, 'run', side_effect=[
                SimpleNamespace(returncode=0, stdout=b''),
                SimpleNamespace(returncode=0, stdout=b'active\n')]) as run:
            self.assertTrue(m.HeldTrialRestoreTimer().arm(self.launcher, self.token, self.pins))
        argv = run.call_args_list[0].args[0]
        for item in ('--on-active=90s', '--timer-property=Requires=user@1000.service',
                     '--timer-property=After=user@1000.service',
                     '--property=Requires=user@1000.service', '--property=After=user@1000.service',
                     '--property=TimeoutStartSec=120s', '--property=Restart=on-failure',
                     '--property=RuntimeMaxSec=120s', '--property=RestartSec=30s', '--property=StartLimitBurst=3'):
            self.assertIn(item, argv)
        self.assertFalse(run.call_args_list[0].kwargs['shell'])
        self.assertEqual(run.call_args_list[0].kwargs['timeout'], 8)
        self.assertIn('regear-held-restore-' + self.token + '.timer', run.call_args_list[1].args[0])

    def test_timer_failure_and_inactive_results_fail_closed(self):
        timer = m.HeldTrialRestoreTimer()
        with patch.object(m.subprocess, 'run') as run:
            self.assertFalse(timer.active('%n'))
            self.assertFalse(timer.arm(self.launcher, None, self.pins))
            run.assert_not_called()
        for rc, output in ((1, b'active'), (0, b'inactive'), (0, b'')):
            with patch.object(m.subprocess, 'run', return_value=SimpleNamespace(returncode=rc, stdout=output)):
                self.assertFalse(timer.active(self.token))
        with patch.object(m.subprocess, 'run', side_effect=OSError('unavailable')):
            self.assertFalse(timer.arm(self.launcher, self.token, self.pins))
        with patch.object(m.os, 'geteuid', return_value=1000), patch.object(m.subprocess, 'run') as run:
            self.assertFalse(timer.arm(self.launcher, self.token, self.pins))
            run.assert_not_called()

    def test_nonzero_helper_exit_cannot_report_success(self):
        with patch.object(m.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stdout=b'{"code":"held_helper.held","restored":true}')):
            result = self.launcher.call('hold', self.token, self.pins)
        self.assertEqual(result, {'code': 'held_helper.failed'})

    def test_archive_audit_uses_same_zipapp_in_session_user_mode(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            path=Path(directory)/'Re-Gear-complete-trial-123456abcdef.pyz'
            path.write_bytes(b'fixture')
            with patch.object(m.subprocess,'run',return_value=SimpleNamespace(
                    returncode=0,stdout=b'{"code":"held_helper.settled","settled":true}')) as run:
                self.assertTrue(self.launcher.audit_archive(str(path))['settled'])
                argv=run.call_args.args[0]
                self.assertEqual(argv[-4:],('/usr/bin/python3','-I',str(path),'--audit'))
                self.assertEqual(argv[:4],('/usr/bin/runuser','-u','deck','--'))
                self.assertFalse(run.call_args.kwargs['shell'])
            with patch.object(m.subprocess,'run',return_value=SimpleNamespace(
                    returncode=1,stdout=b'{"code":"held_helper.settled","settled":true}')):
                self.assertEqual(self.launcher.audit_archive(str(path))['code'],'held_helper.unavailable')


if __name__ == '__main__':
    unittest.main()
