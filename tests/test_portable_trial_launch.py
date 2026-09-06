import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from hdm.delivery.gamescope_wrapper import GamescopeLaunchConfig, config_to_dict
from hdm.delivery.portable_trial_launch import candidate_from_record, consume_launch_candidate
from hdm.delivery.portable_trial_store import PortableTrialStore


class TrialLaunchTests(unittest.TestCase):
    def setUp(self):
        self.boot = 'fixture-boot'
        self.boot_hash = hashlib.sha256(self.boot.encode()).hexdigest()
        self.config = GamescopeLaunchConfig(self.boot_hash, 'portable', 'eDP-1')
        self.card = SimpleNamespace(boot_vga=True, vendor_device='1002:150e',
            connectors=(SimpleNamespace(name='eDP-1', internal=True, connected=True),))
        self.record = dict(expected_config=config_to_dict(self.config),
            boot_id_sha256=self.boot_hash, egpu_binding_sha256='b' * 64,
            internal_gpu='1002:150e', internal_connector='eDP-1',
            generation='generation-1', expires_at=100)
        self.arguments = dict(config=self.config, argv=('--', 'steam'), environment={'KEEP': 'yes'},
            boot_hash=self.boot_hash, egpu_binding_hash='b' * 64, now=20,
            cards=(self.card,), game_idle=True, layer_available=True)

    def test_exact_internal_launch_and_original_environment_preserved(self):
        argv, env = candidate_from_record(self.record, **self.arguments)
        self.assertEqual(env['MESA_VK_DEVICE_SELECT'], '1002:150e')
        self.assertEqual(env['MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE'], '1')
        self.assertEqual(argv[-2:], ('--', 'steam'))
        self.assertEqual(self.arguments['environment'], {'KEEP': 'yes'})

    def test_fresh_launch_evidence_required(self):
        for changes in ({'now': 100}, {'now': -30}, {'boot_hash': 'c' * 64},
                        {'egpu_binding_hash': 'c' * 64}, {'game_idle': False},
                        {'game_idle': None}, {'layer_available': False}, {'cards': ()},
                        {'cards': (self.card, self.card)}, {'config': None},
                        {'environment': {'DRI_PRIME': '1'}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                candidate_from_record(self.record, **dict(self.arguments, **changes))

    def test_connector_must_belong_to_verified_internal_gpu(self):
        self.card.connectors = ()
        with self.assertRaises(ValueError):
            candidate_from_record(self.record, **self.arguments)

    def test_failed_receipt_publication_burns_gamescope_trial(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PortableTrialStore(Path(directory))
            store.arm(operation_id='operation-1', boot_id_sha256=self.boot_hash,
                generation='generation-1', internal_gpu='1002:150e', internal_connector='eDP-1',
                egpu_binding_sha256='b'*64, original_config=None,
                expected_config=self.config, expires_at=100)
            with (patch('hdm.delivery.portable_trial_launch.live_candidate_from_record',
                        return_value=((), {})),
                  patch.object(PortableTrialStore, 'publish_gamescope_launch', side_effect=OSError)):
                result = consume_launch_candidate(Path(directory), config=self.config,
                    argv=(), environment={'INVOCATION_ID': 'c'*32}, raw_boot_id=self.boot)
                self.assertIsNone(result)
                self.assertIsNone(store.consume())

    def test_normal_gamescope_launch_clears_both_stale_trial_selectors(self):
        from hdm.delivery import gamescope_wrapper as wrapper
        with (patch.object(wrapper.os, 'environ', {
                    'MESA_VK_DEVICE_SELECT': 'stale',
                    'MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE': '1'}),
              patch.object(wrapper, '_connected_connectors', return_value=()),
              patch.object(wrapper, '_boot_identity', return_value=('', '')),
              patch.object(wrapper, '_present_vendor_devices', return_value=()),
              patch.object(wrapper, '_verified_egpu_binding_sha256', return_value=''),
              patch.object(wrapper.os.sys, 'argv', ['gamescope']),
              patch.object(wrapper.os, 'execve') as execute):
            wrapper.main()
        self.assertNotIn('MESA_VK_DEVICE_SELECT', execute.call_args.args[2])
        self.assertNotIn('MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE', execute.call_args.args[2])

    def test_rejected_expired_launch_is_consumed_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PortableTrialStore(Path(directory))
            store.arm(operation_id='operation-1', boot_id_sha256=self.boot_hash,
                generation='generation-1', internal_gpu='1002:150e', internal_connector='eDP-1',
                egpu_binding_sha256='b' * 64, original_config=None,
                expected_config=self.config, expires_at=1)
            with (patch('hdm.delivery.gamescope_wrapper._verified_egpu_binding_sha256', return_value='b'*64),
                 patch('hdm.adapters.steamos.drm.DrmDiscovery.scan', return_value=(self.card,)),
                 patch('hdm.adapters.steamos.game_scopes.SystemdGameScopeDiscovery.scan') as game,
                 patch('hdm.delivery.portable_trial_launch.os.getuid', return_value=1000, create=True)):
                from hdm.domain.models import GameState
                game.return_value.state = GameState.IDLE
                result = consume_launch_candidate(Path(directory), config=self.config,
                    argv=(), environment={}, raw_boot_id=self.boot)
                self.assertIsNone(result)
                self.assertIsNone(store.consume())


if __name__ == '__main__':
    unittest.main()
