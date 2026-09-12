"""Legacy repair must retain uncertain intent and never issue hardware commands."""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.delivery import whole_dock_reset as m
from regear.delivery.whole_dock_claim import WholeDockClaim, WholeDockClaimStore, FILENAME, RESET_PENDING
from regear.delivery.dock_mutation_gate import DockMutationGate, DockMutationDenied


class ResetServiceTests(unittest.TestCase):
    def fixture(self, *, stage='reauthorize_intent', answer=True, changed=False,
                preview=False, busy=False, expired=False):
        claim = WholeDockClaim('op', 'dock', 'generation', stage)
        store = Mock()
        store.load.return_value = claim
        store._encode = WholeDockClaimStore._encode
        held = []
        @contextmanager
        def admit(**options):
            self.assertTrue(options['allow_inhibited'])
            if busy:
                raise DockMutationDenied('dock_mutation.unavailable_or_busy')
            held.append(True)
            try:
                yield
            finally:
                held.clear()
        def archive(expected, guard, publication_guard):
            self.assertTrue(held)
            self.assertEqual(expected, claim)
            if not guard() or not publication_guard():
                raise ValueError('changed')
        store.retire_operator_reset.side_effect = archive
        confirm = Mock(return_value=answer)
        observe = Mock(side_effect=['stable', 'changed' if changed else 'stable'])
        clock = Mock(side_effect=[0, 121] if expired else [0, 1, 2, 3])
        result = m.reconcile_record(store=store, gate=Mock(admit=admit), observe=observe,
            confirm=None if preview else confirm, now=clock)
        self.assertFalse(result['hardware_write'])
        self.assertFalse(result['safe_to_unplug'])
        return result, store, confirm, observe

    def test_confirmed_exact_record_archived_after_reobservation(self):
        result, store, confirm, observe = self.fixture()
        self.assertTrue(result['ok'])
        self.assertEqual(observe.call_count, 2)
        self.assertEqual(len(confirm.call_args.args[0]), 64)
        store.retire_operator_reset.assert_called_once()

    def test_preview_has_no_retirement(self):
        result, store, confirm, _ = self.fixture(preview=True)
        self.assertTrue(result['ready'])
        store.retire_operator_reset.assert_not_called()
        confirm.assert_not_called()

    def test_declined_nonboolean_or_expired_confirmation_never_retires(self):
        for options in ({'answer': False}, {'answer': 1}, {'expired': True}):
            with self.subTest(options=options):
                result, store, _, _ = self.fixture(**options)
                self.assertFalse(result['ok'])
                store.retire_operator_reset.assert_not_called()

    def test_busy_and_other_stages_refuse_before_observation(self):
        for options in ({'busy': True}, {'stage': 'software_down'}, {'stage': 'release_intent'},
                        {'stage': 'software_reconnected'}):
            with self.subTest(options=options):
                result, store, _, observe = self.fixture(**options)
                self.assertFalse(result['ok'])
                store.retire_operator_reset.assert_not_called()
                observe.assert_not_called()

    def test_changed_observation_never_claims_success(self):
        result, _, _, _ = self.fixture(changed=True)
        self.assertFalse(result['ok'])

    def test_external_confirmation_revocation_after_final_observe_blocks_archive(self):
        @contextmanager
        def admitted(**kwargs):
            yield
        store = Mock()
        store.load.return_value = WholeDockClaim('op', 'dock', 'generation', 'reauthorize_intent')
        store._encode = WholeDockClaimStore._encode
        valid = [True]
        observations = []
        def observe(_):
            observations.append(True)
            if len(observations) == 2:
                valid[0] = False
            return 'same proof'
        def archive(expected, guard, publication_guard):
            if guard() is not True or publication_guard() is not True:
                raise ValueError('revoked')
            self.fail('revoked confirmation reached archive')
        store.retire_operator_reset.side_effect = archive
        result = m.reconcile_record(store=store, gate=Mock(admit=admitted), observe=observe,
            confirm=lambda *args: True, still_confirmed=lambda: valid[0])
        self.assertFalse(result['ok'])


class ResetObservationTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with ExitStack() as stack:
            def patched(name, **kwargs):
                return stack.enter_context(patch.object(m, name, **kwargs))
            value = NS(game_state=m.GameState.IDLE,
                       gamescope=NS(running=True, confidence=m.Confidence.VERIFIED))
            discovery = patched('SteamOsDiscovery')
            discovery.return_value.collect_snapshot.return_value = value
            patched('infer_operating_mode', return_value=NS(mode=m.OperatingMode.PORTABLE))
            patched('resolve_runtime_profiles', return_value=NS(exact_host=True))
            cards = patched('DrmDiscovery')
            cards.return_value.scan.return_value = [NS(boot_vga=False, pci_bdf='fixture-gpu')]
            topology = patched('resolve_whole_dock', return_value=NS(binding='dock'))
            session = patched('GamescopeDiscovery')
            session.return_value.scan.return_value = NS(ok=True,
                process=NS(pid=101, start_time_ticks=1000, uid=1000))
            patched('resolve_gamescope_user', return_value=NS(ok=True, context=NS(uid=1000, username='deck')))
            boot = patched('read_boot_hash', return_value='a' * 64)
            pending = patched('no_pending_records', return_value=True)
            inner = patched('inner_removal_records_absent', return_value=True)
            audit = patched('HeldTrialLauncher')
            audit.return_value.audit_archive.return_value = {'code': 'held_helper.settled', 'settled': True}
            yield NS(value=value, discovery=discovery, cards=cards, topology=topology,
                     boot=boot, pending=pending, inner=inner, audit=audit, session=session)

    def test_stable_full_topology_and_idle_session_are_reobserved(self):
        with self.fixture() as f:
            m.observe_restored('dock', Mock(), '/fixture.pyz')
            self.assertEqual(f.topology.call_count, 2)
            self.assertEqual(f.discovery.return_value.collect_snapshot.call_count, 2)
            f.audit.return_value.audit_archive.assert_called_once()

    def test_unknown_running_or_nonportable_game_state_refuses(self):
        for game in (m.GameState.UNKNOWN, m.GameState.RUNNING):
            with self.subTest(game=game), self.fixture() as f:
                f.value.game_state = game
                with self.assertRaisesRegex(ValueError, 'portable_unverified'):
                    m.observe_restored('dock', Mock(), '/fixture.pyz')
                f.audit.assert_not_called()

    def test_pending_inner_or_parent_work_refuses(self):
        for field in ('pending', 'inner'):
            with self.subTest(field=field), self.fixture() as f:
                getattr(f, field).return_value = False
                with self.assertRaisesRegex(ValueError, 'pending_work'):
                    m.observe_restored('dock', Mock(), '/fixture.pyz')
                f.audit.assert_not_called()

    def test_missing_gpu_or_driver_or_changed_dock_refuses(self):
        for case in ('gpu', 'driver', 'dock'):
            with self.subTest(case=case), self.fixture() as f:
                if case == 'gpu':
                    f.cards.return_value.scan.return_value = []
                elif case == 'driver':
                    f.topology.side_effect = ValueError('driver missing')
                else:
                    f.topology.return_value = NS(binding='another dock')
                with self.assertRaises(ValueError):
                    m.observe_restored('dock', Mock(), '/fixture.pyz')

    def test_unsettled_helper_or_changed_final_evidence_refuses(self):
        for case in ('helper', 'boot', 'topology', 'game', 'session'):
            with self.subTest(case=case), self.fixture() as f:
                if case == 'helper':
                    f.audit.return_value.audit_archive.return_value = {'code': 'held_helper.unavailable'}
                elif case == 'boot':
                    f.boot.side_effect = ['a' * 64, 'b' * 64]
                elif case == 'topology':
                    f.topology.side_effect = [NS(binding='dock', generation='one'), NS(binding='dock', generation='two')]
                elif case == 'session':
                    f.session.return_value.scan.side_effect = [
                        NS(ok=True, process=NS(pid=101, start_time_ticks=1000, uid=1000)),
                        NS(ok=True, process=NS(pid=101, start_time_ticks=2000, uid=1000))]
                else:
                    f.discovery.return_value.collect_snapshot.side_effect = [f.value,
                        NS(game_state=m.GameState.RUNNING)]
                with self.assertRaises(ValueError):
                    m.observe_restored('dock', Mock(), '/fixture.pyz')


@unittest.skipUnless(sys.platform == 'linux', 'Linux descriptor-relative filesystem required')
class ResetFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        args = dict(owner_uid=os.geteuid(), trusted_directory_fd=self.fd)
        self.store = WholeDockClaimStore(self.root, **args)
        self.gate = DockMutationGate(self.root, **args)
        self.store.claim('op', 'dock', 'generation')
        self.store.record('op', 'reauthorize_intent')
        self.original = (self.root / FILENAME).read_bytes()

    def tearDown(self):
        os.close(self.fd)
        self.temp.cleanup()

    def run_reset(self, **overrides):
        options = dict(store=self.store, gate=self.gate, observe=lambda _: 'stable',
                       confirm=lambda *args: True)
        options.update(overrides)
        return m.reconcile_record(**options)

    def test_real_gate_retains_exact_failure_audit_and_duplicate_refuses(self):
        with self.assertRaises(DockMutationDenied):
            with self.gate.admit():
                self.fail('retained claim admitted')
        self.assertTrue(self.run_reset()['ok'])
        archives = list(self.root.glob('operator-physical-reset-*.json'))
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0].read_bytes(), self.original)
        with self.gate.admit():
            self.assertIsNone(self.store.load())
        self.assertFalse(self.run_reset()['ok'])

    def test_changed_claim_refuses(self):
        def confirm(*args):
            self.store.record('op', 'software_reconnected')
            return True
        self.assertFalse(self.run_reset(confirm=confirm)['ok'])
        self.assertEqual(self.store.load().stage, 'software_reconnected')
        self.assertEqual(list(self.root.glob('operator-physical-reset-*')), [])

    def test_archive_collision_preserves_claim(self):
        target = self.root / ('operator-physical-reset-' + 'a' * 32 + '.json')
        target.write_text('existing')
        with patch('regear.delivery.whole_dock_claim.secrets.token_hex', return_value='a' * 32):
            self.assertFalse(self.run_reset()['ok'])
        self.assertEqual(target.read_text(), 'existing')
        self.assertEqual((self.root / FILENAME).read_bytes(), self.original)

    def test_fsync_failure_restores_inhibition(self):
        original = os.fsync
        calls = []
        def fail_once(fd):
            calls.append(fd)
            if len(calls) == 1:
                raise OSError('disk failure')
            return original(fd)
        with patch('regear.delivery.whole_dock_claim.os.fsync', side_effect=fail_once):
            self.assertFalse(self.run_reset()['ok'])
        self.assertEqual((self.root / FILENAME).read_bytes(), self.original)

    def test_archive_fsync_failure_or_interruption_keeps_new_gate_inhibited(self):
        for failure in (OSError('disk failure'), SystemExit('interruption')):
            with self.subTest(failure=type(failure).__name__):
                calls = []
                original = os.fsync
                def fail_after_archive(fd):
                    calls.append(fd)
                    if len(calls) == 3:
                        raise failure
                    return original(fd)
                with patch('regear.delivery.whole_dock_claim.os.fsync', side_effect=fail_after_archive):
                    if isinstance(failure, Exception):
                        self.assertFalse(self.run_reset()['ok'])
                    else:
                        with self.assertRaises(SystemExit):
                            self.run_reset()
                self.assertTrue((self.root / RESET_PENDING).exists())
                self.assertFalse((self.root / FILENAME).exists())
                gate = DockMutationGate(self.root, owner_uid=os.geteuid(), trusted_directory_fd=self.fd)
                for continuation in (False, True):
                    with self.assertRaises(DockMutationDenied):
                        with gate.admit(allow_inhibited=continuation):
                            self.fail('unfinished archival admitted')
                archives = list(self.root.glob('operator-physical-reset-*.json'))
                self.assertEqual(archives[-1].read_bytes(), self.original)
                # Fixture reset only: production never clears pending markers.
                (self.root / RESET_PENDING).unlink()
                (self.root / FILENAME).write_bytes(self.original)
                (self.root / FILENAME).chmod(0o600)

    def test_pending_marker_any_kind_refuses_even_teardown_continuation(self):
        for kind in ('file', 'directory', 'symlink'):
            with self.subTest(kind=kind):
                path = self.root / RESET_PENDING
                if kind == 'file':
                    path.write_text('malformed')
                elif kind == 'directory':
                    path.mkdir()
                else:
                    path.symlink_to(self.root / 'absent')
                with self.assertRaises(DockMutationDenied):
                    with self.gate.admit(allow_inhibited=True):
                        self.fail('marker admitted')
                path.rmdir() if kind == 'directory' else path.unlink()

    def test_pending_power_or_journal_records_refuse_and_are_not_removed(self):
        for name in ('dock-power-old.json', 'active-transition.json'):
            path = self.root / name
            path.write_text('uninterpreted')
            self.assertFalse(m.no_pending_records(self.store))
            self.assertTrue(path.exists())
            path.unlink()
        self.assertTrue(m.no_pending_records(self.store))
