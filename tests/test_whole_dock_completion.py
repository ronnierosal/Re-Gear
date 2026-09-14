"""Completion reconciliation never writes hardware or accepts changed proof."""
from contextlib import contextmanager
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.delivery.whole_dock_completion import complete_record
from regear.delivery.whole_dock_claim import WholeDockClaim
from regear.delivery import whole_dock_completion as m


class CompletionTests(unittest.TestCase):
    def fixture(self, *, confirm=True, stage='tunnel_remove_intent', changed=False,
                foreign=False, failed=False):
        held=[]
        @contextmanager
        def admit(**kw):
            self.assertIs(kw['allow_inhibited'], True)
            held.append(True)
            try: yield
            finally: held.clear()
        store=Mock()
        store.load.return_value=WholeDockClaim('operation','other' if foreign else 'dock','generation',stage)
        def commit(expected, guard):
            self.assertTrue(held)
            if guard() is not True: raise ValueError('changed')
        store.confirm_software_down.side_effect=commit
        observe=Mock(side_effect=ValueError('incomplete') if failed else ['proof','changed' if changed else 'proof'])
        result=complete_record(binding='dock',generation='generation',confirmed=confirm,
            store=store,gate=NS(admit=admit),observe=observe)
        self.assertFalse(result['hardware_write'])
        self.assertFalse(result['safe_to_unplug'])
        return result,store,observe

    def test_exact_completed_down_advances_record(self):
        result,store,observe=self.fixture()
        self.assertTrue(result['ok'])
        self.assertEqual(observe.call_count,2)
        store.confirm_software_down.assert_called_once()

    def test_read_only_preview_never_advances(self):
        result,store,_=self.fixture(confirm=False)
        self.assertTrue(result['ready'])
        store.confirm_software_down.assert_not_called()

    def test_other_stages_identity_and_unknown_proof_refuse(self):
        for options in ({'stage':'release_intent'},{'stage':'software_down'},
                        {'foreign':True},{'changed':True},{'failed':True}):
            with self.subTest(options=options):
                result,_,_=self.fixture(**options)
                self.assertFalse(result['ok'])

    def test_game_starting_during_audit_refuses_completion_proof(self):
        user=NS(ok=True,context=NS(uid=1000,username='deck'))
        with patch.object(m.os,'geteuid',return_value=1000,create=True), \
             patch.object(m,'resolve_deauthorized_transport',return_value='transport'), \
             patch.object(m,'GamescopeDiscovery'), \
             patch.object(m,'resolve_gamescope_user',return_value=user), \
             patch.object(m,'infer_operating_mode',return_value=NS(mode=m.OperatingMode.PORTABLE)), \
             patch.object(m,'user_helper',return_value={'code':'held_helper.settled','settled':True}), \
             patch.object(m,'SteamOsDiscovery') as discovery:
            discovery.return_value.collect_snapshot.side_effect=[
                NS(game_state=m.GameState.IDLE),NS(game_state=m.GameState.RUNNING)]
            with self.assertRaisesRegex(ValueError,'portable_changed'):
                m.observe_down('binding','generation')
