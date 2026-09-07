from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from backend.hdm.delivery.device_filter_prepared_source import PreparedLaunchObservationSource
from backend.hdm.delivery.device_filter_prepare_server import IsolationCoverage
from backend.hdm.delivery.device_filter_arm import FilterArm
from backend.hdm.delivery.device_filter_peer import WaitingPeerIdentity
from backend.hdm.delivery.device_filter_runtime_bundle import RuntimeBundle
from backend.hdm.delivery.device_filter_effective_launch import SteamLaunchExpectation,EffectiveSteamLaunch
from backend.hdm.delivery.device_receive_layout_cache import CachedDmaLayout
from backend.hdm.delivery.inherited_resource_scan import InheritedResourceObservation
from backend.hdm.adapters.steamos.prepare_hardware_identity import PrepareHardwareIdentity,RenderTarget
from backend.hdm.adapters.steamos.game_scopes import GameScopeScan
from backend.hdm.adapters.steamos.device_receive_symbols import ReceiveSymbols
from backend.hdm.domain.models import GameState
from tests.test_dma_receive_program import LAYOUT,FOPS,OPS


class PreparedSourceTests(unittest.TestCase):
    def setUp(self):
        self.arm=FilterArm(1,'op','steam-launcher.service',1000,'a'*64,'b'*64,'c'*64,'d'*32,14)
        path='/var/lib/regear/filter-runtime/'+'e'*64+'/runtime.pyz'
        self.runtime=RuntimeBundle(b'', 'e'*64,path,b'',('/usr/bin/python3','-I',path,'steam'),())
        self.expectation=SteamLaunchExpectation(self.runtime,())
        self.identity=WaitingPeerIdentity(1,1000,2,'f'*32,self.arm.unit,'/fixture',3,4)
        self.held=Mock();self.held.revalidate.return_value=self.identity
        self.hardware_value=PrepareHardwareIdentity('a'*64,'b'*64,RenderTarget('/dev/dri/renderD128',128,0,'0000:01:00.0'),
            RenderTarget('/dev/dri/renderD129',129,1,'0000:02:00.0'))
        self.hardware=Mock();self.hardware.collect.return_value=self.hardware_value
        self.scopes=Mock();self.scopes.scan.return_value=GameScopeScan(GameState.IDLE)
        self.now=10.
        def clock():self.now+=.001;return self.now
        self.clock=clock
        self.effective=Mock(side_effect=lambda identity:EffectiveSteamLaunch(identity,self.runtime.digest,self.clock()))
        self.scan=Mock(return_value=InheritedResourceObservation(True))
        self.config=Mock(return_value='c'*64)
        self.cache=Mock();self.cache.parse.return_value=CachedDmaLayout('1'*64,8,LAYOUT)
        self.btf=Mock(return_value=b'fresh')
        self.symbols=Mock(return_value=ReceiveSymbols(FOPS,OPS))
        self.source=PreparedLaunchObservationSource(SimpleNamespace(uid=1000),self.arm,self.runtime,self.hardware_value,
            self.expectation,state_root=Path.cwd(),deadline=14,hardware=self.hardware,scopes=self.scopes,
            effective_observer=self.effective,inherited_scan=self.scan,config_loader=self.config,hash_config=lambda value:value,
            btf_reader=self.btf,symbols_reader=self.symbols,layout_cache=self.cache,clock=self.clock)
        self.major=patch('backend.hdm.delivery.device_filter_prepared_source.os.major',lambda dev:226,create=True)
        self.minor=patch('backend.hdm.delivery.device_filter_prepared_source.os.minor',lambda dev:dev,create=True)
        self.major.start();self.minor.start();self.addCleanup(self.major.stop);self.addCleanup(self.minor.stop)

    def test_complete_bracket_uses_start_timestamp_and_unknown_limitations(self):
        result=self.source(self.held)
        self.assertAlmostEqual(result.dma.observed_at,10.001)
        self.assertEqual(result.evidence.denied_devices,((226,1),(226,129)))
        self.assertEqual(result.evidence.broker_coverage,IsolationCoverage.UNKNOWN)
        self.assertEqual(result.evidence.importer_coverage,IsolationCoverage.UNKNOWN)
        self.assertTrue(result.evidence.no_game)
        self.assertEqual(self.hardware.collect.call_count,2);self.assertEqual(self.scopes.scan.call_count,2)
        self.assertEqual(self.config.call_count,2)
        self.assertNotIn(str(FOPS),repr(result))

    def test_every_collection_reads_fresh_btf_symbols_and_scope(self):
        first=self.source(self.held);second=self.source(self.held)
        self.assertEqual(self.btf.call_count,2);self.assertEqual(self.symbols.call_count,2)
        self.assertEqual(self.scopes.scan.call_count,4)
        self.assertGreater(second.dma.observed_at,first.dma.observed_at)

    def test_changed_hardware_config_or_peer_refuses(self):
        for mode in ('hardware','config','peer'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode=='hardware':self.hardware.collect.side_effect=[self.hardware_value,replace(self.hardware_value,topology_hash='2'*64)]
                elif mode=='config':self.config.side_effect=['c'*64,'2'*64]
                else:self.held.revalidate.side_effect=[self.identity,replace(self.identity,starttime=3)]
                with self.assertRaises(ValueError):self.source(self.held)

    def test_unknown_scope_and_any_inherited_resource_refuse(self):
        self.scopes.scan.return_value=GameScopeScan(GameState.UNKNOWN)
        with self.assertRaises(ValueError):self.source(self.held)
        self.scopes.scan.return_value=GameScopeScan(GameState.IDLE)
        for fields in (dict(complete=False),dict(dma_buf_seen=True),dict(target_character_seen=True),dict(unclassified_seen=True)):
            self.scan.return_value=replace(InheritedResourceObservation(True),**fields)
            with self.assertRaises(ValueError):self.source(self.held)

    def test_gamescope_is_unsupported_before_hardware_reads(self):
        self.held.revalidate.return_value=replace(self.identity,unit='gamescope-session.service')
        with self.assertRaisesRegex(ValueError,'Gamescope unsupported'):self.source(self.held)
        self.hardware.collect.assert_not_called()

    def test_slow_bracket_does_not_renew_timestamp(self):
        def symbols():self.now+=2.1;return ReceiveSymbols(FOPS,OPS)
        self.symbols.side_effect=symbols
        with self.assertRaisesRegex(ValueError,'freshness'):self.source(self.held)

    def test_dma_construction_time_is_included_in_final_freshness_check(self):
        from backend.hdm.delivery import device_filter_prepared_source as module
        original=module.DmaReceiveObservation
        def slow(*args,**kwargs):
            value=original(*args,**kwargs)
            self.now+=2.1
            return value
        with patch.object(module,'DmaReceiveObservation',side_effect=slow):
            with self.assertRaisesRegex(ValueError,'freshness'):self.source(self.held)

    def test_effective_configuration_change_or_failure_at_end_refuses(self):
        for failure in (False,True):
            with self.subTest(failure=failure):
                self.setUp()
                calls=0
                def effective(identity):
                    nonlocal calls
                    calls+=1
                    if calls==2:
                        if failure:raise ValueError('effective configuration changed')
                        return EffectiveSteamLaunch(identity,'f'*64,self.clock())
                    return EffectiveSteamLaunch(identity,self.runtime.digest,self.clock())
                self.effective.side_effect=effective
                with self.assertRaises(ValueError):self.source(self.held)
                self.assertEqual(calls,2)


if __name__=='__main__':unittest.main()
