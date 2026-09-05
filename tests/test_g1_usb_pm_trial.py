import importlib.util
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('pm_trial', SCRIPTS / 'g1_usb_pm_trial.py')
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class SysfsControl:
    """Model a sysfs store callback replacing an attribute on each write."""
    def __init__(self, path, writes, fail=False):
        self.path, self.writes, self.fail = path, writes, fail

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def seek(self, offset):
        pass

    def write(self, value):
        self.writes.append(value.strip())
        self.path.write_text(value)
        if self.fail and value.strip() == 'on':
            raise OSError('failure_after_mutation')

    def flush(self):
        pass


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        branch = self.root / 'branch'
        usb = branch / 'usb_bridge' / 'usb'
        gpu = branch / 'gpu_bridge' / 'gpu'
        usb.mkdir(parents=True)
        gpu.mkdir(parents=True)
        (usb / 'power').mkdir()
        self.control = usb / 'power/control'
        self.control.write_text('auto\n')
        (usb / 'power/runtime_status').write_text('active\n')
        self.target = gpu, usb, branch
        for node in {gpu, usb, usb.parent, branch}:
            for name in ('aer_dev_nonfatal', 'aer_dev_fatal'):
                (node / name).write_text('ACSViol 0\nTOTAL_ERR 0\n')
        self.writes = []
        self.events = []
        self.stop = threading.Event()
        self.identity = ('boot', 'same_devices')

    def run_trial(self, **kwargs):
        options = dict(hold_seconds=1, stop=self.stop,
                       emit_event=lambda event, **_: self.events.append(event),
                       identify=lambda _: self.identity,
                       open_control=lambda p: SysfsControl(p, self.writes),
                       wait=lambda _: self.stop.set())
        options.update(kwargs)
        return trial.change_and_restore(self.target, **options)

    def test_success_restores_exact_original(self):
        self.assertTrue(self.run_trial())
        self.assertEqual(self.writes, ['on', 'auto'])
        self.assertEqual(self.control.read_text().strip(), 'auto')
        self.assertEqual(self.events[-1], 'restored')

    def test_existing_errors_prevent_any_write(self):
        (self.target[1].parent / 'aer_dev_nonfatal').write_text('ACSViol 4\n')
        with self.assertRaisesRegex(ValueError, 'aer_missing_or_nonzero'):
            self.run_trial()
        self.assertEqual(self.writes, [])

    def test_missing_counter_is_not_zero(self):
        (self.target[2] / 'aer_dev_fatal').unlink()
        with self.assertRaisesRegex(ValueError, 'aer_missing_or_nonzero'):
            self.run_trial()
        self.assertEqual(self.writes, [])

    def test_storage_prevents_write(self):
        (self.target[1] / 'usb1' / 'block').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'usb_storage_present'):
            self.run_trial()
        self.assertEqual(self.writes, [])

    def test_existing_manual_power_setting_is_preserved(self):
        self.control.write_text('on\n')
        with self.assertRaisesRegex(ValueError, 'baseline_must_be_auto'):
            self.run_trial()
        self.assertEqual(self.writes, [])

    def test_new_errors_abort_hold_and_restore(self):
        def wait(_):
            (self.target[1].parent / 'aer_dev_nonfatal').write_text('ACSViol 1\n')
        with self.assertRaisesRegex(ValueError, 'aer_missing_or_nonzero'):
            self.run_trial(wait=wait)
        self.assertEqual(self.writes, ['on', 'auto'])

    def test_mutating_write_failure_still_restores(self):
        with self.assertRaisesRegex(OSError, 'failure_after_mutation'):
            self.run_trial(open_control=lambda p: SysfsControl(p, self.writes, True))
        self.assertEqual(self.writes, ['on', 'auto'])

    def test_replaced_device_is_never_written_during_restore(self):
        def wait(_):
            self.identity = ('boot', 'replacement_device')
        with self.assertRaisesRegex(RuntimeError, 'restore_unverified'):
            self.run_trial(wait=wait)
        self.assertEqual(self.writes, ['on'])
        self.assertIn('restore_unverified', self.events)

    def test_external_restoration_is_not_overwritten(self):
        def wait(_):
            self.control.write_text('auto\n')
        with self.assertRaisesRegex(ValueError, 'control_changed_during_hold'):
            self.run_trial(wait=wait)
        self.assertEqual(self.writes, ['on'])
        self.assertEqual(self.events[-1], 'restored')

    def test_unknown_boot_prevents_write(self):
        with self.assertRaisesRegex(ValueError, 'boot_unverified'):
            self.run_trial(identify=lambda _: (None, 'devices'))
        self.assertEqual(self.writes, [])

    def test_target_changes_before_apply(self):
        identities = iter([('boot', 'a'), ('boot', 'b')])
        with self.assertRaisesRegex(ValueError, 'target_changed_before_write'):
            self.run_trial(identify=lambda _: next(identities))
        self.assertEqual(self.writes, [])

    def test_cancel_before_write_leaves_setting_alone(self):
        self.stop.set()
        with self.assertRaisesRegex(ValueError, 'cancelled_before_write'):
            self.run_trial()
        self.assertEqual(self.writes, [])

    def test_control_on_without_active_state_is_not_success(self):
        (self.target[1] / 'power/runtime_status').write_text('suspended\n')
        with self.assertRaisesRegex(ValueError, 'controller_not_active'):
            self.run_trial()
        self.assertEqual(self.writes, ['on', 'auto'])

    def test_watchdog_signals_unknown_without_hardware_mutation(self):
        trial.watch_deadline(threading.Event(), self.stop, 0,
                             lambda event, **_: self.events.append(event))
        self.assertTrue(self.stop.is_set())
        self.assertEqual(self.events, ['deadline_exceeded'])
        self.assertEqual(self.writes, [])

    def test_completed_trial_does_not_trigger_watchdog(self):
        done = threading.Event()
        done.set()
        trial.watch_deadline(done, self.stop, 0,
                             lambda event, **_: self.events.append(event))
        self.assertFalse(self.stop.is_set())
        self.assertEqual(self.events, [])

    def discovery_fixture(self):
        gpu, usb, branch = self.target
        internal = self.root / 'internal'
        internal.mkdir()
        for node, vendor, device in [(internal, '1002', '15bf'),
                                     (gpu, '1002', '7480'),
                                     (usb, '8086', '15f0'),
                                     (usb.parent, '8086', '15ef'),
                                     (gpu.parent, '8086', '15ef'),
                                     (branch, '8086', '15ef')]:
            (node / 'vendor').write_text('0x' + vendor)
            (node / 'device').write_text('0x' + device)
        (usb / 'class').write_text('0x0c0330')
        (usb / 'driver').mkdir()
        (gpu / 'driver').mkdir()
        mapping = {str(usb / 'driver'): self.root / 'xhci_hcd',
                   str(gpu / 'driver'): self.root / 'amdgpu'}
        registry = Mock()
        registry.iterdir.return_value = [internal, gpu, usb, branch, usb.parent, gpu.parent]
        return registry, mapping

    def test_discovery_selects_same_transport_usb(self):
        registry, mapping = self.discovery_fixture()
        with patch.object(Path, 'resolve', lambda p, strict=False: mapping.get(str(p), p)):
            self.assertEqual(trial.discover(registry), self.target)

    def test_discovery_does_not_select_other_transport_usb(self):
        registry, mapping = self.discovery_fixture()
        other = self.root / 'unrelated_usb'
        other.mkdir()
        (other / 'vendor').write_text('0x8086')
        (other / 'device').write_text('0x15f0')
        registry.iterdir.return_value.append(other)
        with patch.object(Path, 'resolve', lambda p, strict=False: mapping.get(str(p), p)):
            self.assertEqual(trial.discover(registry), self.target)

    def test_discovery_ambiguous_same_transport_usb_is_rejected(self):
        registry, mapping = self.discovery_fixture()
        other = self.target[2] / 'second_usb'
        other.mkdir()
        (other / 'vendor').write_text('0x8086')
        (other / 'device').write_text('0x15f0')
        registry.iterdir.return_value.append(other)
        with patch.object(Path, 'resolve', lambda p, strict=False: mapping.get(str(p), p)):
            with self.assertRaisesRegex(ValueError, 'g1_usb_unverified'):
                trial.discover(registry)

    def test_discovery_wrong_driver_rejected(self):
        registry, mapping = self.discovery_fixture()
        mapping[str(self.target[1] / 'driver')] = self.root / 'unrelated_driver'
        with patch.object(Path, 'resolve', lambda p, strict=False: mapping.get(str(p), p)):
            with self.assertRaisesRegex(ValueError, 'usb_driver_unready'):
                trial.discover(registry)
