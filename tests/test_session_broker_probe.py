import importlib.util
from pathlib import Path
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
import subprocess

from regear.adapters.steamos import commands

SPEC = importlib.util.spec_from_file_location("broker_probe", Path(__file__).resolve().parents[1] / "scripts/probe_session_broker_release.py")
probe_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe_module)


class BrokerProbeTests(unittest.TestCase):
    def test_execute_never_observes_or_mutates(self):
        def forbidden():
            self.fail("execution must refuse before observation")
        result = probe_module.probe(execute=True, euid=0, observer=forbidden)
        self.assertEqual(result["code"], "broker_probe.execution_not_implemented")
        self.assertFalse(result["execution_enabled"])

    def test_nonroot_refuses_before_observation(self):
        result = probe_module.probe(euid=1000, observer=lambda: self.fail("nonroot"))
        self.assertEqual(result["code"], "broker_probe.root_required")

    def test_complete_observation_is_not_permission(self):
        result = probe_module.probe(euid=0, observer=lambda: {
            "stable": True, "complete": True, "holder_categories": ["system_broker"]})
        self.assertEqual(result["code"], "broker_probe.observed")
        self.assertFalse(result["safe_to_unplug"])
        self.assertFalse(result["execution_enabled"])

    def test_unstable_binding_refuses(self):
        result = probe_module.probe(euid=0, observer=lambda: {
            "stable": False, "complete": True, "holder_categories": []})
        self.assertEqual(result["code"], "broker_probe.identity_changed")

    def test_incomplete_is_not_clear(self):
        result = probe_module.probe(euid=0, observer=lambda: {
            "stable": True, "complete": False, "holder_categories": []})
        self.assertEqual(result["code"], "broker_probe.scan_incomplete")
        self.assertFalse(result["scan_complete"])

    def test_raw_identity_and_exception_never_leak(self):
        for observer in (lambda: {"stable": True, "complete": True,
                                  "holder_categories": ["private-serial"]},
                         lambda: (_ for _ in ()).throw(ValueError("private-serial"))):
            result = probe_module.probe(euid=0, observer=observer)
            self.assertNotIn("private-serial", str(result))
            self.assertEqual(result["code"], "broker_probe.evidence_unavailable")


class RestoreTimerTests(unittest.TestCase):
    def test_root_system_timer_has_fixed_restore_target_and_no_shell(self):
        with patch.object(commands.os, 'geteuid', return_value=0, create=True), \
                patch.object(commands.subprocess, 'run', side_effect=[
                    NS(returncode=0), NS(returncode=0, stdout=b'active\n')]) as run:
            self.assertTrue(commands.BrokerCaptureRestoreTimer().arm(
                uid=1000, username='deck', token='a' * 32))
        argv = run.call_args_list[0].args[0]
        self.assertEqual(argv[0], '/usr/bin/systemd-run')
        self.assertIn('--on-active=25s', argv)
        self.assertIn('--property=ExecStartPre=/usr/bin/systemctl start user@1000.service', argv)
        self.assertIn('--property=TimeoutStartSec=20s', argv)
        self.assertEqual(argv[-4:], ('/usr/bin/systemctl', '--user', 'start', 'gamescope-session.target'))
        self.assertIn('DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus', argv)
        self.assertIn('XDG_RUNTIME_DIR=/run/user/1000', argv)
        self.assertEqual(run.call_args_list[1].args[0],
                         ('/usr/bin/systemctl', 'is-active', 'regear-broker-restore-' + 'a' * 32 + '.timer'))
        for call in run.call_args_list:
            self.assertFalse(call.kwargs.get('shell', False))
            self.assertEqual(call.kwargs['timeout'], 8)

    def test_nonroot_or_invalid_identity_never_runs(self):
        for uid, name, token, effective in ((1000, 'deck', 'a' * 32, 1000),
                (0, 'deck', 'a' * 32, 0), (True, 'deck', 'a' * 32, 0),
                (1000, 'deck;bad', 'a' * 32, 0), (1000, 'deck', '../bad', 0)):
            with self.subTest(uid=uid, name=name, token=token, effective=effective), \
                    patch.object(commands.os, 'geteuid', return_value=effective, create=True), \
                    patch.object(commands.subprocess, 'run') as run:
                self.assertFalse(commands.BrokerCaptureRestoreTimer().arm(uid=uid, username=name, token=token))
                run.assert_not_called()

    def test_timer_creation_or_active_verification_failure_refuses(self):
        for replies in ([NS(returncode=1)], [NS(returncode=0), NS(returncode=1, stdout=b'active')],
                        [NS(returncode=0), NS(returncode=0, stdout=b'inactive')],
                        [subprocess.TimeoutExpired('timer', 8)], [OSError('unavailable')]):
            with self.subTest(replies=replies), \
                    patch.object(commands.os, 'geteuid', return_value=0, create=True), \
                    patch.object(commands.subprocess, 'run', side_effect=replies):
                self.assertFalse(commands.BrokerCaptureRestoreTimer().arm(
                    uid=1000, username='deck', token='a' * 32))


if __name__ == "__main__":
    unittest.main()

class HeldSessionCommandTests(unittest.TestCase):
    def test_root_cannot_run_user_only_executor(self):
        with patch.object(commands.os, 'geteuid', return_value=0, create=True), self.assertRaises(ValueError):
            commands.HeldSessionCommandRunner(1000)

    def test_fixed_units_and_environment(self):
        with patch.object(commands.os, 'geteuid', return_value=1000, create=True), patch.object(commands.subprocess, 'run', return_value=NS(returncode=0, stdout=b'active\n')) as run:
            runner = commands.HeldSessionCommandRunner(1000)
            self.assertEqual(runner.run('state', 'gamescope-session.target'), 'active')
            self.assertEqual(run.call_args.args[0], ('/usr/bin/systemctl', '--user', 'show', 'gamescope-session.target', '--property=ActiveState', '--value'))
            self.assertFalse(run.call_args.kwargs['shell'])
            self.assertEqual(run.call_args.kwargs['env']['XDG_RUNTIME_DIR'], '/run/user/1000')
            run.reset_mock()
            for action, unit in (('unmask', 'gamescope-session.target'), ('start', 'other.service'), ('start', '../bad'), ('reload', 'pipewire.service')):
                self.assertIsNone(runner.run(action, unit))
            run.assert_not_called()

    def test_unknown_state_and_timeout_are_unverified(self):
        with patch.object(commands.os, 'geteuid', return_value=1000, create=True):
            runner = commands.HeldSessionCommandRunner(1000)
            for outcome in (NS(returncode=0, stdout=b'activating\n'), NS(returncode=1), subprocess.TimeoutExpired('systemctl', 5)):
                with patch.object(commands.subprocess, 'run', side_effect=[outcome]):
                    self.assertIsNone(runner.run('state', 'pipewire.service'))
