"""Strict intent parsing plus real Linux persistence and replay rejection."""
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.delivery.dock_power_intent import DockPowerIntent, DockPowerIntentStore
from regear.delivery.whole_dock_claim import WholeDockClaim, WholeDockClaimStore, FILENAME

ARGS = ('a' * 32, 'dock', 'generation', 'shutdown', 'session', 10, 100)


def consume_competing(path, output):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        store = DockPowerIntentStore(path, owner_uid=os.geteuid(), trusted_directory_fd=fd)
        output.put(store.consume(*ARGS))
    finally:
        os.close(fd)


class IntentSchemaTests(unittest.TestCase):
    def test_round_trip(self):
        value = DockPowerIntent(*ARGS)
        self.assertEqual(DockPowerIntentStore._decode_intent(
            DockPowerIntentStore._encode_intent(value)), value)

    def test_bad_values(self):
        for index, bad in ((0, '../bad'), (1, ''), (2, None), (3, 'reboot'),
                           (4, ''), (5, True), (5, -1), (6, float('nan')),
                           (6, float('inf')), (6, 10), (6, 311)):
            args = list(ARGS)
            args[index] = bad
            with self.subTest(index=index, bad=bad), self.assertRaises(ValueError):
                DockPowerIntent(*args)
        with self.assertRaises(ValueError):
            DockPowerIntent(*ARGS, consumed=1)

    def test_strict_schema(self):
        raw = DockPowerIntentStore._encode_intent(DockPowerIntent(*ARGS))
        parsed = json.loads(raw)
        for value in (dict(parsed, extra=True), dict(parsed, schema_version=True),
                      {k: v for k, v in parsed.items() if k != 'session'}):
            with self.assertRaises(ValueError):
                DockPowerIntentStore._decode_intent(json.dumps(value).encode())
        with self.assertRaises(ValueError):
            DockPowerIntentStore._decode_intent(raw.replace(b'{', b'{"action":"sleep",', 1))
        with self.assertRaises(ValueError):
            DockPowerIntentStore._decode_intent(b' ' * 4097)


@unittest.skipUnless(sys.platform == 'linux', 'Linux descriptor-relative filesystem required')
class IntentFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.kwargs = dict(owner_uid=os.geteuid(), trusted_directory_fd=self.fd)
        self.store = DockPowerIntentStore(self.root, **self.kwargs)
        self.claim = WholeDockClaimStore(self.root, **self.kwargs)
        self.claim.claim(*ARGS[:3])
        self.path = self.root / ('dock-power-' + ARGS[0] + '.json')

    def tearDown(self):
        os.close(self.fd)
        self.temp.cleanup()

    def test_persists_once_and_preserves_claim(self):
        self.assertTrue(self.store.bind(*ARGS))
        self.assertFalse(self.store.bind(*ARGS))
        self.assertFalse(self.store.consume(*ARGS))
        self.claim.record(ARGS[0], 'software_down')
        before = (self.root / FILENAME).read_bytes()
        recreated = DockPowerIntentStore(self.root, **self.kwargs)
        self.assertTrue(recreated.consume(*ARGS))
        self.assertFalse(self.store.consume(*ARGS))
        self.assertEqual((self.root / FILENAME).read_bytes(), before)
        self.assertTrue(json.loads(self.path.read_text())['consumed'])

    def test_wrong_session_action_identity_or_time_refused(self):
        self.assertTrue(self.store.bind(*ARGS))
        self.claim.record(ARGS[0], 'software_down')
        for index, changed in ((0, 'b' * 32), (1, 'other'), (2, 'other'),
                               (3, 'sleep'), (4, 'new-session'), (5, 11), (6, 101)):
            args = list(ARGS)
            args[index] = changed
            self.assertFalse(self.store.consume(*args))
        self.assertTrue(self.store.consume(*ARGS))

    def test_late_binding_and_absent_intent_refused(self):
        self.claim.record(ARGS[0], 'software_down')
        self.assertFalse(self.store.bind(*ARGS))
        self.assertFalse(self.store.consume(*ARGS))

    def test_corrupt_or_unsafe_record_refused(self):
        self.store.bind(*ARGS)
        self.claim.record(ARGS[0], 'software_down')
        self.path.write_bytes(b'{')
        with self.assertRaises(ValueError):
            self.store.consume(*ARGS)
        self.path.unlink()
        self.path.symlink_to(self.root / FILENAME)
        with self.assertRaises(OSError):
            self.store.consume(*ARGS)

    def test_fsync_failure_does_not_report_consumption_success(self):
        self.store.bind(*ARGS)
        self.claim.record(ARGS[0], 'software_down')
        original = os.fsync
        calls = []
        def fail_directory(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError('directory durability unavailable')
            return original(fd)
        with patch('regear.delivery.dock_power_intent.os.fsync', side_effect=fail_directory):
            with self.assertRaises(OSError):
                self.store.consume(*ARGS)
        self.assertFalse(self.store.consume(*ARGS))

    def test_temp_write_failure_is_not_a_power_submission_grant(self):
        self.store.bind(*ARGS)
        self.claim.record(ARGS[0], 'software_down')
        with patch.object(self.store, '_write_intent', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                self.store.consume(*ARGS)
        self.assertFalse(json.loads(self.path.read_text())['consumed'])
        # Store has not consumed; coordinator must retain its attempted bit and
        # never submit power after the failed durable write or reconstruct it.
        changed_session = (*ARGS[:4], 'new-process', *ARGS[5:])
        self.assertFalse(self.store.consume(*changed_session))

    def test_old_operation_does_not_block_new_operation(self):
        self.store.bind(*ARGS)
        # Fixture models a separately verified claim retirement, not store API.
        (self.root / FILENAME).unlink()
        other = ('b' * 32, *ARGS[1:])
        self.claim.claim(*other[:3])
        self.assertTrue(self.store.bind(*other))
        self.assertTrue(self.path.exists())

    def test_competing_processes_consume_only_once(self):
        self.store.bind(*ARGS)
        self.claim.record(ARGS[0], 'software_down')
        ctx = multiprocessing.get_context('spawn')
        output = ctx.Queue()
        processes = [ctx.Process(target=consume_competing, args=(str(self.root), output))
                     for _ in range(4)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(sum(output.get(timeout=2) for _ in processes), 1)
        output.close()

    def test_hardlink_and_public_permissions_rejected(self):
        self.store.bind(*ARGS)
        self.claim.record(ARGS[0], 'software_down')
        alias = self.root / 'alias'
        os.link(self.path, alias)
        with self.assertRaises(ValueError):
            self.store.consume(*ARGS)
        alias.unlink()
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            self.store.consume(*ARGS)

    def prepare_boot_intent(self, *, action='shutdown', consume=True, session=None):
        args = (*ARGS[:3], action, session or ('1' * 64 + ':' + 'a' * 32), *ARGS[5:])
        self.assertTrue(self.store.bind(*args))
        self.claim.record(ARGS[0], 'software_down')
        if consume:
            self.assertTrue(self.store.consume(*args))
        return self.claim.load()

    def test_shutdown_intent_retires_after_verified_new_boot(self):
        expected = self.prepare_boot_intent()
        before = self.path.read_bytes()
        self.assertTrue(self.store.retire_after_boot(expected, '2' * 64, lambda: True))
        self.assertIsNone(self.claim.load())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(list(self.root.glob('power-completed-whole-dock-*.json'))), 1)
        self.assertFalse(self.store.retire_after_boot(expected, '2' * 64, lambda: True))

    def test_same_boot_and_false_guard_refuse_retirement(self):
        expected = self.prepare_boot_intent()
        self.assertFalse(self.store.retire_after_boot(expected, '1' * 64, lambda: True))
        self.assertFalse(self.store.retire_after_boot(expected, '2' * 64, lambda: False))
        self.assertEqual(self.claim.load(), expected)

    def test_unconsumed_boot_intent_refused(self):
        expected = self.prepare_boot_intent(consume=False)
        self.assertFalse(self.store.retire_after_boot(expected, '2' * 64, lambda: True))

    def test_sleep_intent_refused_after_boot(self):
        expected = self.prepare_boot_intent(action='sleep')
        self.assertFalse(self.store.retire_after_boot(expected, '2' * 64, lambda: True))

    def test_legacy_session_and_missing_intent_refused(self):
        expected = self.prepare_boot_intent(session='legacy')
        self.assertFalse(self.store.retire_after_boot(expected, '2' * 64, lambda: True))
        self.path.unlink()
        self.assertFalse(self.store.retire_after_boot(expected, '2' * 64, lambda: True))

    def test_mismatched_identity_and_invalid_boot_refused(self):
        expected = self.prepare_boot_intent()
        changed = WholeDockClaim(expected.operation, 'wrong', expected.generation, 'software_down')
        self.assertFalse(self.store.retire_after_boot(changed, '2' * 64, lambda: True))
        self.assertFalse(self.store.retire_after_boot(expected, 'bad', lambda: True))
        raw = json.loads(self.path.read_text())
        raw['binding'] = 'wrong'
        self.path.write_text(json.dumps(raw))
        self.assertFalse(self.store.retire_after_boot(expected, '2' * 64, lambda: True))

    def test_retirement_fsync_failure_restores_claim(self):
        expected = self.prepare_boot_intent()
        with patch('regear.delivery.dock_power_intent.os.fsync',
                   side_effect=[OSError('durability unavailable'), None]):
            with self.assertRaises(OSError):
                self.store.retire_after_boot(expected, '2' * 64, lambda: True)
        self.assertEqual(self.claim.load(), expected)


if __name__ == '__main__':
    unittest.main()
