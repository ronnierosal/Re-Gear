from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch
from dataclasses import replace
from pathlib import Path

from backend.hdm.delivery import device_filter_prepare_controller as module


class PrepareControllerTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.listener = MagicMock()
        self.listener.__enter__.return_value = self.listener
        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection
        self.listener.accept.return_value = self.connection
        self.factory = Mock(return_value=self.listener)
        self.handler = Mock(return_value="withheld")
        self.peer = self.stack.enter_context(patch.object(module, "peer_identity",
                                                        return_value=SimpleNamespace(uid=1000)))

    def run_once(self, clock=lambda: 10):
        return module.serve_prepare_once(self.handler, session_gid=1000,
            expected_uid=1000, deadline=14, clock=clock, listener_factory=self.factory)

    def test_one_authenticated_request_preserves_listener_contract(self):
        self.assertEqual(self.run_once(), "withheld")
        self.factory.assert_called_once_with(1000)
        self.listener.accept.assert_called_once()
        self.handler.assert_called_once_with(self.connection, deadline=14)
        self.connection.__exit__.assert_called_once()
        self.listener.__exit__.assert_called_once()

    def test_uid_mismatch_never_calls_handler(self):
        self.peer.return_value = SimpleNamespace(uid=1001)
        with self.assertRaises(ValueError): self.run_once()
        self.handler.assert_not_called()
        self.connection.__exit__.assert_called_once()
        self.listener.__exit__.assert_called_once()

    def test_handler_error_closes_both_contexts(self):
        self.handler.side_effect = RuntimeError("failed preparation")
        with self.assertRaises(RuntimeError): self.run_once()
        self.connection.__exit__.assert_called_once()
        self.listener.__exit__.assert_called_once()

    def test_deadline_expired_before_handler(self):
        with self.assertRaises(TimeoutError): self.run_once(clock=lambda: 15)
        self.handler.assert_not_called()

    def test_handler_overrun_rejected_without_second_accept(self):
        ticks = iter((10, 15))
        with self.assertRaises(TimeoutError): self.run_once(clock=lambda: next(ticks))
        self.handler.assert_called_once()
        self.listener.accept.assert_called_once()

    def test_invalid_uid_rejected_before_listener_creation(self):
        for uid in (0, True, "1000"):
            with self.assertRaises(ValueError):
                module.serve_prepare_once(self.handler, session_gid=1000,
                    expected_uid=uid, deadline=14, listener_factory=self.factory)
        self.factory.assert_not_called()


class SessionCompositionTests(unittest.TestCase):
    def setUp(self):
        from tests.test_device_filter_prepare_server import PrepareServerTests
        from backend.hdm.delivery.device_filter_session_prepare import SessionEntryPreparedCollection
        from backend.hdm.delivery.device_filter_runtime_peer import SessionEntryRuntimeObservation
        self.fixture = PrepareServerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        path = '/var/lib/regear/filter-runtime/' + '1'*64 + '/runtime.pyz'
        self.runtime = module.RuntimeBundle(b'', '1'*64, path, b'',
            ('/usr/bin/python3','-I',path,'steam'), ('/usr/bin/python3','-I',path,'session'))
        from backend.hdm.delivery.device_filter_session_entry import SessionEntryPurpose
        self.expectation = module.SessionEntryExpectation(self.runtime, (),
            ('/etc/systemd/user/gamescope-session.service.d/fixture.conf',), SessionEntryPurpose.PREPARE_WITHHOLD)
        self.hardware = module.PrepareHardwareIdentity('a'*64, 'b'*64,
            module.RenderTarget('/fixture/internal', 1, 0, 'internal'),
            module.RenderTarget('/fixture/external', 2, 1, 'external'))
        f.evidence = replace(f.evidence, denied_devices=((226,1),(226,128)))
        f.source = SessionEntryRuntimeObservation(f.identity, self.runtime.digest, 2, 3)
        self.source = Mock(return_value=SessionEntryPreparedCollection(f.evidence, f.dma))
        self.source_factory = Mock(return_value=self.source)
        def server_factory(journal, user, source, **kwargs):
            return module.SessionEntryPrepareServer(journal, user, source, **kwargs,
                arms=f.arms, observer_factory=Mock(), hold_peer=Mock(return_value=f.held),
                observe_runtime=f.runtime_observer, preparation_factory=f.factory)
        self.server_factory = Mock(side_effect=server_factory)
        self.listener = MagicMock()
        self.listener.__enter__.return_value = self.listener
        self.listener.accept.return_value = f.connection
        f.connection.__enter__.return_value = f.connection
        self.listener_factory = Mock(return_value=self.listener)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(module.os, 'major', return_value=226, create=True))
        self.stack.enter_context(patch.object(module.os, 'minor', return_value=128, create=True))
        self.stack.enter_context(patch.object(module, 'peer_identity', return_value=SimpleNamespace(uid=1000)))

    def run_session(self, **overrides):
        f = self.fixture
        args = dict(user=SimpleNamespace(uid=1000,gid=1000), expected_arm=f.arm,
            runtime=self.runtime, expected_hardware=self.hardware,
            effective_expectation=self.expectation, state_root=Path.cwd(), journal=f.journal,
            deadline=14, clock=lambda:10, listener_factory=self.listener_factory,
            source_factory=self.source_factory, server_factory=self.server_factory)
        args.update(overrides)
        return module.serve_session_prepare_once(**args)

    def test_real_server_prepares_cancels_and_never_grants(self):
        result = self.run_session()
        self.assertEqual(self.fixture.events, ['create','prepare','cancel'])
        self.assertFalse(result.launch_authorized)
        self.assertTrue(result.recovery_required)
        self.fixture.connection.send.assert_not_called()
        self.source_factory.assert_called_once()
        self.server_factory.assert_called_once()

    def test_invalid_role_uid_and_deadline_rejected_before_listener(self):
        for values in ({'expected_arm':replace(self.fixture.arm,unit='steam-launcher.service')},
                       {'user':SimpleNamespace(uid=1001,gid=1000)}, {'deadline':16}, {'deadline':10}):
            with self.subTest(values=values), self.assertRaises(ValueError): self.run_session(**values)
        self.listener_factory.assert_not_called()

    def test_independent_nodes_not_replaced_by_observed_nodes(self):
        from backend.hdm.delivery.device_filter_session_prepare import SessionEntryPreparedCollection
        f = self.fixture
        self.source.return_value = SessionEntryPreparedCollection(
            replace(f.evidence, denied_devices=((226,129),)), f.dma)
        with self.assertRaises(ValueError): self.run_session()
        self.assertEqual(f.events, [])


class SessionSchedulingTests(unittest.TestCase):
    def setUp(self):
        SessionCompositionTests.setUp(self)
        self.user = module.GamescopeUserContext('deck',1000,1000,Path('/home/deck'),
                                                Path('/run/user/1000'),Path('/run/user/1000/bus'))
        self.snapshot = module.SessionPreparePreflight(self.user,self.fixture.arm,self.runtime.digest,
            self.fixture.arm.boot_hash,self.fixture.arm.config_hash,self.fixture.arm.topology_hash,10,True)
        self.preflight = Mock(return_value=self.snapshot)
        self.commands = Mock()
        self.order = []
        self.listener_factory.side_effect = lambda gid:self.order.append('listening') or self.listener
        self.commands.run.side_effect = lambda *a,**k:self.order.append('restart') or Mock(ok=True)
        self.listener.accept_waiting.side_effect = lambda **k:self.order.append('accept') or self.fixture.connection

    def run_trial(self, deadline=14):
        return module.run_session_prepare_once(user=self.user, expected_arm=self.fixture.arm,
            runtime=self.runtime, expected_hardware=self.hardware,effective_expectation=self.expectation,
            state_root=Path.cwd(),journal=self.fixture.journal,deadline=deadline,commands=self.commands,
            preflight=self.preflight,arms=self.fixture.arms,clock=lambda:10,
            listener_factory=self.listener_factory,source_factory=self.source_factory,
            server_factory=self.server_factory)

    def test_restart_occurs_after_listener_then_real_prepare(self):
        result=self.run_trial()
        self.assertEqual(self.order,['listening','restart','accept'])
        self.assertEqual(self.fixture.events,['create','prepare','cancel'])
        self.assertFalse(result.launch_authorized)
        self.commands.run.assert_called_once_with(module.UserServiceOperation.RESTART_GAMESCOPE_SESSION,
            uid=1000,username='deck',timeout_seconds=4)

    def test_restart_failure_closes_listener_without_accept(self):
        self.commands.run.side_effect=None
        self.commands.run.return_value=Mock(ok=False)
        with self.assertRaises(ValueError):self.run_trial()
        self.listener.accept_waiting.assert_not_called()
        self.listener.__exit__.assert_called_once()

    def test_startup_wait_does_not_extend_prepare_budget(self):
        self.fixture.arm=replace(self.fixture.arm,deadline=100)
        self.fixture.arms.read.return_value=self.fixture.arm
        self.snapshot=replace(self.snapshot,arm=self.fixture.arm)
        self.preflight.return_value=self.snapshot
        self.run_trial(deadline=80)
        self.assertEqual(self.listener.accept_waiting.call_args.kwargs['deadline'],80)
        self.assertEqual(self.source_factory.call_args.kwargs['deadline'],14)

    def test_bad_preflight_rejects_before_restart(self):
        for snapshot in (True,replace(self.snapshot,idle=1),replace(self.snapshot,idle=False),
                         replace(self.snapshot,observed_at=8),replace(self.snapshot,boot_hash='f'*64)):
            self.preflight.return_value=snapshot
            with self.subTest(snapshot=snapshot),self.assertRaises(ValueError):self.run_trial()
        self.commands.run.assert_not_called()
        self.listener_factory.assert_not_called()

    def test_changed_arm_after_listening_prevents_restart(self):
        self.fixture.arms.read.side_effect=[self.fixture.arm,None]
        with self.assertRaises(ValueError):self.run_trial()
        self.commands.run.assert_not_called()
        self.listener.__exit__.assert_called_once()
