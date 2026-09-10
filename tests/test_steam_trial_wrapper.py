import concurrent.futures
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.delivery.gamescope_wrapper import GamescopeLaunchConfig
from regear.delivery.portable_trial_store import PortableTrialStore
from regear.delivery.steam_trial_wrapper import consume_steam_environment, current_gamescope_invocation, main


class SteamTrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = PortableTrialStore(self.root)
        self.config = GamescopeLaunchConfig('a'*64, 'portable', 'eDP-1')
        self.store.arm(operation_id='operation-1', boot_id_sha256='a'*64,
            generation='generation-1', internal_gpu='1002:150e', internal_connector='eDP-1',
            egpu_binding_sha256='b'*64, original_config=None,
            expected_config=self.config, expires_at=100)
        self.invocation = 'c'*32
        self.original = dict(KEEP='yes', MESA_VK_DEVICE_SELECT='stale',
                            MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE='1')
        self.clean = {'KEEP': 'yes'}
        self.candidate = dict(self.clean, MESA_VK_DEVICE_SELECT='1002:150e',
                              MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE='1')

    def publish(self):
        self.store.consume()
        self.store.publish_gamescope_launch('operation-1', self.invocation)

    def launch(self, reader=None):
        return consume_steam_environment(self.root, config=self.config,
            environment=self.original, raw_boot_id='boot',
            invocation_reader=reader or (lambda: self.invocation))

    def test_fresh_receipt_grants_exactly_one_launch_without_parent_mutation(self):
        self.publish()
        with patch('regear.delivery.steam_trial_wrapper.live_candidate_from_record',
                   return_value=((), self.candidate)) as validate:
            self.assertEqual(self.launch(), self.candidate)
            self.assertEqual(self.launch(), self.clean)
        validate.assert_called_once()
        self.assertEqual(validate.call_args.kwargs['environment'], self.clean)
        self.assertEqual(self.original['MESA_VK_DEVICE_SELECT'], 'stale')

    def test_v2_prime_is_child_only_and_inherited_prime_remains_a_conflict(self):
        from regear.delivery.portable_trial_launch import candidate_from_record
        def live(record, **kwargs):
            return candidate_from_record(record, config=kwargs['config'], argv=(),
                environment=kwargs['environment'], boot_hash='a'*64, egpu_binding_hash='b'*64,
                now=20, cards=(SimpleNamespace(boot_vga=True,vendor_device='1002:150e',
                    connectors=(SimpleNamespace(name='eDP-1',internal=True,connected=True),)),),
                game_idle=True, layer_available=True)
        for index, prime in enumerate((None,'1002:150e','custom')):
            root=self.root/str(index);root.mkdir()
            store=PortableTrialStore(root)
            store.arm(operation_id='fresh',boot_id_sha256='a'*64,generation='fresh',
                internal_gpu='1002:150e',internal_connector='eDP-1',egpu_binding_sha256='b'*64,
                original_config=None,expected_config=self.config,expires_at=100,schema_version=2)
            store.consume();store.publish_gamescope_launch('fresh',self.invocation)
            original={'KEEP':'yes'}
            if prime is not None:original['DRI_PRIME']=prime
            def launch():
                return consume_steam_environment(root,config=self.config,environment=original,
                    raw_boot_id='boot',invocation_reader=lambda:self.invocation)
            with patch('regear.delivery.steam_trial_wrapper.live_candidate_from_record',side_effect=live):
                result=launch()
                self.assertEqual(launch(),original)
            if prime is None:
                self.assertEqual(result['DRI_PRIME'],'1002:150e')
                self.assertNotIn('DRI_PRIME',original)
            else:
                self.assertEqual(result,original)
                self.assertNotIn('MESA_VK_DEVICE_SELECT',result)

    def test_ordinary_launch_preserves_user_prime(self):
        self.original['DRI_PRIME']='custom'
        self.assertEqual(self.launch(),dict(self.clean,DRI_PRIME='custom'))

    def test_old_consumed_trial_without_receipt_cannot_authorize_steam(self):
        self.store.consume()
        self.assertEqual(self.launch(), self.clean)
        self.store.publish_gamescope_launch('operation-1', self.invocation)
        self.assertEqual(self.launch(), self.clean)

    def test_early_steam_launch_burns_before_late_publication(self):
        self.assertEqual(self.launch(), self.clean)
        self.publish()
        self.assertEqual(self.launch(), self.clean)

    def test_cancel_before_late_receipt_blocks_steam(self):
        self.store.cancel('operation-1')
        self.store.publish_gamescope_launch('operation-1', self.invocation)
        self.assertEqual(self.launch(), self.clean)

    def test_cancel_after_receipt_blocks_steam(self):
        self.publish()
        self.store.cancel('operation-1')
        self.assertEqual(self.launch(), self.clean)

    def test_receipt_is_exclusive_and_requires_consumed_operation(self):
        with self.assertRaises(OSError):
            self.store.publish_gamescope_launch('operation-1', self.invocation)
        self.publish()
        with self.assertRaises(FileExistsError):
            self.store.publish_gamescope_launch('operation-1', self.invocation)
        with self.assertRaises(ValueError):
            self.store.publish_gamescope_launch('foreign', self.invocation)

    def test_changed_invocation_before_or_during_collection_burns(self):
        self.publish()
        with patch('regear.delivery.steam_trial_wrapper.live_candidate_from_record',
                   return_value=((), self.candidate)):
            answers = iter((self.invocation, 'd'*32))
            self.assertEqual(self.launch(lambda: next(answers)), self.clean)
            self.assertEqual(self.launch(), self.clean)

    def test_unknown_invocation_burns(self):
        self.publish()
        self.assertEqual(self.launch(lambda: ''), self.clean)
        self.assertEqual(self.launch(), self.clean)

    def test_validation_failure_burns_without_replay(self):
        self.publish()
        with patch('regear.delivery.steam_trial_wrapper.live_candidate_from_record',
                   side_effect=ValueError('stale hardware')):
            self.assertEqual(self.launch(), self.clean)
        with patch('regear.delivery.steam_trial_wrapper.live_candidate_from_record',
                   return_value=((), self.candidate)):
            self.assertEqual(self.launch(), self.clean)

    def test_concurrent_claims_have_one_winner(self):
        self.publish()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: PortableTrialStore(self.root).consume_steam(), range(4)))
        self.assertEqual(sum(value is not None for value in results), 1)

    def test_malformed_receipt_burns(self):
        self.publish()
        receipt = self.root / 'portable-vulkan-trial.gamescope-launch'
        receipt.write_text('operation-1\nforeign\nextra')
        self.assertEqual(self.launch(), self.clean)
        receipt.write_text('operation-1\n' + self.invocation)
        self.assertEqual(self.launch(), self.clean)

    def test_active_service_observation_required(self):
        with patch('regear.delivery.steam_trial_wrapper.subprocess.run') as run:
            run.return_value.stdout = 'ActiveState=active\nInvocationID=' + self.invocation + '\n'
            self.assertEqual(current_gamescope_invocation(), self.invocation)
            run.return_value.stdout = 'ActiveState=inactive\nInvocationID=' + self.invocation + '\n'
            with self.assertRaises(ValueError):
                current_gamescope_invocation()

    def test_cancel_cannot_retract_an_already_claimed_launch(self):
        self.publish()
        def validate(*args, **kwargs):
            self.store.cancel('operation-1')
            return (), self.candidate
        with patch('regear.delivery.steam_trial_wrapper.live_candidate_from_record', side_effect=validate):
            self.assertEqual(self.launch(), self.candidate)
        self.assertEqual(self.launch(), self.clean)

    def test_entry_point_uses_only_fixed_launcher_and_cleans_stale_environment(self):
        with (patch('regear.delivery.steam_trial_wrapper.os.environ', self.original),
              patch('regear.delivery.steam_trial_wrapper._boot_identity', side_effect=OSError),
              patch('regear.delivery.steam_trial_wrapper.os.execve') as execute):
            self.assertEqual(main(), 127)
        execute.assert_called_once_with('/usr/lib/steamos/steam-launcher',
            ('/usr/lib/steamos/steam-launcher',), self.clean)


if __name__ == '__main__':
    unittest.main()
