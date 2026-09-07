from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock
from tests.test_device_filter_prepared_source import PreparedSourceTests
from tests.test_device_filter_prepare_server import PrepareServerTests
from backend.hdm.delivery.device_filter_session_prepare import *
from backend.hdm.delivery.device_filter_runtime_peer import RuntimePeerObservation


class SessionSourceTests(PreparedSourceTests):
    def setUp(self):
        super().setUp()
        self.arm=replace(self.arm,unit='gamescope-session.service')
        self.identity=replace(self.identity,unit=self.arm.unit)
        self.held.revalidate.return_value=self.identity
        self.runtime=replace(self.runtime,session_argv=('/usr/bin/python3','-I',self.runtime.path,'session'))
        self.expectation=SessionEntryExpectation(self.runtime,(),('/etc/systemd/user/gamescope-session.service.d/fixture.conf',),SessionEntryPurpose.PREPARE_WITHHOLD)
        self.effective.side_effect=lambda identity:EffectiveSessionEntry(identity,self.runtime.digest,self.clock())
        self.source=SessionEntryPreparedObservationSource(SimpleNamespace(uid=1000),self.arm,self.runtime,self.hardware_value,
            self.expectation,state_root=Path.cwd(),deadline=14,hardware=self.hardware,scopes=self.scopes,
            effective_observer=self.effective,inherited_scan=self.scan,config_loader=self.config,hash_config=lambda value:value,
            btf_reader=self.btf,symbols_reader=self.symbols,layout_cache=self.cache,clock=self.clock)

    def test_gamescope_is_unsupported_before_hardware_reads(self):
        self.held.revalidate.return_value=replace(self.identity,unit='steam-launcher.service')
        with self.assertRaises(ValueError):self.source(self.held)
        self.hardware.collect.assert_not_called()

    def test_effective_configuration_change_or_failure_at_end_refuses(self):
        for mode in ('runtime','purpose','native','stale','failure'):
            with self.subTest(mode=mode):
                self.setUp()
                calls=0
                def effective(identity):
                    nonlocal calls
                    calls+=1
                    value=EffectiveSessionEntry(identity,self.runtime.digest,self.clock())
                    if calls==2:
                        if mode=='runtime':value=replace(value,runtime_digest='f'*64)
                        if mode=='purpose':value=replace(value,purpose='prepare_withhold')
                        if mode=='native':value=replace(value,native_execution_authorized=True)
                        if mode=='stale':value=replace(value,observed_at=0)
                        if mode=='failure':raise ValueError()
                    return value
                self.effective.side_effect=effective
                with self.assertRaises(ValueError):self.source(self.held)
                self.assertEqual(calls,2)

    def test_session_collection_never_authorizes_native_execution(self):
        value=self.source(self.held)
        self.assertIs(type(value),SessionEntryPreparedCollection)
        self.assertFalse(value.native_execution_authorized)
        with self.assertRaises(ValueError):replace(value,native_execution_authorized=True)


class SessionServerTests(PrepareServerTests):
    def setUp(self):
        super().setUp()
        self.source=SessionEntryRuntimeObservation(self.identity,self.runtime.digest,2,3)
        self.handler=SessionEntryPrepareServer(self.journal,SimpleNamespace(uid=1000),
            lambda held:SessionEntryPreparedCollection(self.evidence,self.dma),arms=self.arms,clock=lambda:10,
            observer_factory=Mock(),hold_peer=Mock(return_value=self.held),observe_runtime=self.runtime_observer,
            preparation_factory=self.factory)

    def test_prepare_is_cancelled_then_closed_without_sender(self):
        result=self.handle()
        self.assertEqual(self.events,['create','prepare','cancel'])
        self.assertFalse(result.launch_authorized);self.assertFalse(result.native_execution_authorized)
        self.connection.send.assert_not_called();self.connection.sendmsg.assert_not_called()
        self.connection.__exit__.assert_called_once()

    def test_explicit_combined_source_collects_once_and_keeps_outer_checks(self):
        from backend.hdm.delivery.device_filter_prepared_source import PreparedLaunchCollection
        self.handler.observe_combined=lambda held:PreparedLaunchCollection(self.evidence,self.dma)
        with self.assertRaises(ValueError):self.handle()
        self.journal.create.assert_not_called()

    def test_deadline_expiry_during_dma_collection_blocks_preparation(self):
        def combined(held):
            self.handler.clock=lambda:14
            return SessionEntryPreparedCollection(self.evidence,self.dma)
        self.handler.observe_combined=combined
        with self.assertRaises(ValueError):self.handle()
        self.factory.assert_not_called()

    def test_runtime_roles_are_not_interchangeable(self):
        self.source=RuntimePeerObservation(self.identity,self.runtime.digest,2,3)
        with self.assertRaises(ValueError):self.handle()
        self.journal.create.assert_not_called()
        from backend.hdm.delivery.device_filter_prepare_server import FilterPrepareServer
        generic=FilterPrepareServer(self.journal,SimpleNamespace(uid=1000),None,None)
        self.assertFalse(generic._runtime_valid(SessionEntryRuntimeObservation(self.identity,self.runtime.digest,2,3)))
        self.assertFalse(generic._combined_valid(SessionEntryPreparedCollection(self.evidence,self.dma)))

    def test_policy_is_built_once_after_authenticated_collection(self):
        builder=Mock(return_value=self.policy)
        result=self.handler.handle(self.connection,expected_arm=self.arm,
            runtime=self.runtime,deadline=14,policy_builder=builder)
        self.assertFalse(result.launch_authorized)
        builder.assert_called_once()
        self.assertIs(builder.call_args.args[0],self.held)
        self.assertIs(type(builder.call_args.args[1]),SessionEntryPreparedCollection)
        self.assertEqual(self.events,['create','prepare','cancel'])
        self.connection.send.assert_not_called()

    def test_bad_policy_builder_result_never_creates_journal(self):
        for value in (None,replace(self.policy,binding=replace(self.binding,pid=99),
                evidence=replace(self.dma,binding=replace(self.binding,pid=99)))):
            with self.assertRaises(ValueError):
                self.handler.handle(self.connection,expected_arm=self.arm,
                    runtime=self.runtime,deadline=14,policy_builder=Mock(return_value=value))
            self.journal.create.assert_not_called()

    def test_unverified_runtime_cannot_invoke_policy_builder(self):
        self.source=RuntimePeerObservation(self.identity,self.runtime.digest,2,3)
        builder=Mock(return_value=self.policy)
        with self.assertRaises(ValueError):
            self.handler.handle(self.connection,expected_arm=self.arm,
                runtime=self.runtime,deadline=14,policy_builder=builder)
        builder.assert_not_called()
        self.journal.create.assert_not_called()

    def test_policy_and_builder_are_mutually_exclusive(self):
        builder=Mock(return_value=self.policy)
        with self.assertRaises(ValueError):
            self.handler.handle(self.connection,expected_arm=self.arm,runtime=self.runtime,
                deadline=14,expected_policy=self.policy,policy_builder=builder)
        builder.assert_not_called()
        self.journal.create.assert_not_called()

    def test_real_policy_builder_composes_with_authenticated_server(self):
        from functools import partial
        from backend.hdm.delivery.device_filter_prepare_policy import build_prepare_policy
        builder=partial(build_prepare_policy,expected_denied_devices=self.evidence.denied_devices)
        result=self.handler.handle(self.connection,expected_arm=self.arm,runtime=self.runtime,
            deadline=14,policy_builder=builder)
        self.assertFalse(result.launch_authorized)
        self.assertEqual(self.events,['create','prepare','cancel'])
        self.assertEqual(result.binding,self.binding)
