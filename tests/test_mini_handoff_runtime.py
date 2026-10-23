"""Request boundaries and shared-engine fixtures; all device ports remain inert."""
from contextlib import contextmanager, ExitStack
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import builtins
import inspect
import os
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from test_experimental_handoff_approval import context
from tests.test_main_process_delivery import load_main_module
from regear.adapters.steamos.host import HostRecord
from regear.application.experimental_handoff_approval import HandoffApprovalStore
from regear.delivery import build_profile_config
from regear.delivery.experimental_handoff_runtime import ExperimentalHandoffRuntime
from regear.delivery.observation_admission import observation_plugin, ObservationDenied, mode
from regear.domain.control_plane import PlacementState
from regear.domain.runtime_admission import RuntimeAdmission, PASSIVE_RPCS


class RuntimeBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def wrapper(self, profile="development", forced=False, initial=True):
        self.effects = Mock(); self.effects.reset_mock()
        class Producer:
            def __init__(self):self.effects.composed()
            async def _main(self):self.effects.startup()
            async def preview_supervised_tv_switch(self, _request=None):self.effects.original()
            async def approve_supervised_tv_switch(self, _request=None):self.effects.original()
            async def execute_supervised_tv_switch(self, token):self.effects.original()
            async def get_transition_journal_status(self):self.effects.original()
            async def unrelated(self):self.effects.original()
            def _effectful_factory(self):self.effects.original()
        Producer.effects = self.effects
        matched = HostRecord("fixture vendor", "fixture mini", "fixture board")
        factory = Mock(side_effect=lambda: ExperimentalHandoffRuntime(read_context=lambda target: None))
        guarded = observation_plugin(Producer, passive_api=lambda: NS(), build_info=lambda:{},
            render_snapshot=lambda report:{}, experimental_profile=profile,
            experimental_match=lambda host:host == matched, experimental_factory=factory)
        guarded._runtime_host_record = staticmethod(lambda:matched if initial else HostRecord("", "", ""))
        plugin = guarded(observation_only=forced)
        return guarded, plugin, matched, factory

    async def test_experimental_route_never_composes_original_or_unknown_methods(self):
        guarded, plugin, _, factory = self.wrapper()
        self.assertIs(mode(plugin), RuntimeAdmission.EXPERIMENTAL_HANDOFF)
        for operation in (plugin._main, plugin.preview_supervised_tv_switch,
                          plugin.approve_supervised_tv_switch, plugin.get_transition_journal_status,
                          plugin.unrelated):
            await operation()
        await plugin.execute_supervised_tv_switch("absent-token-00000000")
        with self.assertRaises(ObservationDenied):plugin._effectful_factory()
        async def later(self):self.effects.original()
        guarded.new_rpc = later
        self.assertFalse((await plugin.new_rpc())["accepted"])
        self.effects.assert_not_called()
        self.assertEqual(self.effects.mock_calls, [])
        self.assertEqual(factory.call_count,1)

    async def test_production_forced_unknown_and_stale_identity_never_construct_facade(self):
        for options in ({"profile":"production"},{"forced":True},{"initial":False}):
            guarded, plugin, matched, factory = self.wrapper(**options)
            guarded._runtime_host_record = staticmethod(lambda:matched)
            result = await plugin.preview_supervised_tv_switch()
            self.assertFalse(result["accepted"])
            factory.assert_not_called(); self.assertEqual(self.effects.mock_calls,[])
        guarded, plugin, _, factory = self.wrapper()
        retained = plugin.preview_supervised_tv_switch
        guarded._runtime_host_record = staticmethod(lambda:HostRecord("", "", ""))
        self.assertFalse((await retained())["accepted"])
        factory.assert_not_called()
        # An experimental constructor cannot become a fully composed Ally runtime.
        guarded._runtime_host_record = staticmethod(lambda:HostRecord("ASUSTeK COMPUTER INC.","ROG Ally X RC72LA","RC72LA"))
        self.assertFalse((await plugin.unrelated())["accepted"])
        self.assertEqual(self.effects.mock_calls,[])

    async def test_real_plugin_denies_effects_and_executor_in_both_profiles(self):
        from regear.profiles.win_mini import _OBSERVED_DMI_IDENTITY
        host=HostRecord(*_OBSERVED_DMI_IDENTITY)
        for profile in ("development","production"):
            with patch.object(build_profile_config,"BUILD_PROFILE",profile):
                module=load_main_module(real_dock_gate=True,real_host_admission=True)
            with patch("regear.adapters.steamos.host.HostDiscovery.scan",return_value=host), \
                 patch.object(module.RootOwnedRuntimeState,"ensure",side_effect=AssertionError("root effect")) as root, \
                 patch.object(module,"DeviceAuthorizationObserver",side_effect=AssertionError("composition")) as observer, \
                 patch.object(module.asyncio,"create_task",side_effect=AssertionError("scheduled")) as tasks:
                with ExitStack() as sinks:
                    raw_open=os.open
                    raw_builtin_open=builtins.open
                    write_attempts=[]
                    def read_only_open(path, flags, *args, **kwargs):
                        if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
                            write_attempts.append("os.open")
                            raise AssertionError("filesystem write")
                        return raw_open(path, flags, *args, **kwargs)
                    def read_only_builtin(file, mode="r", *args, **kwargs):
                        if type(mode) is str and any(flag in mode for flag in "wax+"):
                            write_attempts.append("builtins.open")
                            raise AssertionError("filesystem write")
                        return raw_builtin_open(file,mode,*args,**kwargs)
                    sinks.enter_context(patch("os.open",side_effect=read_only_open))
                    sinks.enter_context(patch("builtins.open",side_effect=read_only_builtin))
                    effect_sinks=[]
                    for sink in ("os.mkdir","os.kill","subprocess.Popen","subprocess.run",
                                 "pathlib.Path.write_text","pathlib.Path.write_bytes"):
                        effect_sinks.append(sinks.enter_context(patch(sink,side_effect=AssertionError("effect sink"))))
                    plugin=module.Plugin()
                    await plugin._main()
                    for name, method in inspect.getmembers(module.Plugin,inspect.iscoroutinefunction):
                        if name.startswith("_") or name in PASSIVE_RPCS:continue
                        result=await getattr(plugin,name)()
                        self.assertFalse(result.get("accepted",False),name)
                        self.assertFalse(result.get("ready",False),name)
                        self.assertFalse(result.get("approval_token",""),name)
                    self.assertEqual(write_attempts,[])
                    for sink in effect_sinks:sink.assert_not_called()
                root.assert_not_called();observer.assert_not_called();tasks.assert_not_called()

    async def test_uninitialized_and_unloaded_runtime_cannot_create_facade(self):
        guarded, plugin, _, factory=self.wrapper()
        uninitialized=guarded.__new__(guarded)
        uninitialized._observation_only=False
        self.assertFalse((await uninitialized.preview_supervised_tv_switch())["accepted"])
        plugin._unloading=True
        self.assertFalse((await plugin.preview_supervised_tv_switch())["accepted"])
        factory.assert_not_called()


class FacadeContractTests(unittest.TestCase):
    def setup_facade(self, readings=None, gate=True):
        self.events=[];self.approvals=HandoffApprovalStore();self.current=context()
        values=iter(readings) if readings is not None else None
        def read(target):
            self.events.append("read")
            return next(values) if values is not None else self.current
        @contextmanager
        def admit():
            self.events.append("admit");yield
        def factory():
            self.events.append("gate_factory");return NS(admit=admit)
        self.facade=ExperimentalHandoffRuntime(read_context=read,approvals=self.approvals,
                                             gate_factory=factory if gate else None)
        self.token=self.approvals.issue(plan_id="fixture-plan-0001",context=self.current,user_confirmed=True)

    def test_preview_status_and_approval_do_not_consume_or_issue_authority(self):
        self.setup_facade()
        for name in ("preview_supervised_tv_switch","approve_supervised_tv_switch","get_transition_journal_status"):
            result=self.facade.handle(name,(),{})
            self.assertFalse(result.get("ready",False));self.assertFalse(result.get("approval_token",""))
        self.assertNotIn("gate_factory",self.events)
        self.approvals.consume(self.token,current=self.current)

    def test_consumption_precedes_gate_and_executor_stays_absent(self):
        self.setup_facade()
        result=self.facade.handle("execute_supervised_tv_switch",(self.token,),{})
        self.assertFalse(result["accepted"])
        self.assertEqual(result["code"],"experimental_handoff.executor_unavailable")
        self.assertEqual(self.events,["read","gate_factory","admit","read"])
        self.events.clear()
        self.facade.handle("execute_supervised_tv_switch",(self.token,),{})
        self.assertNotIn("gate_factory",self.events)

    def test_post_consumption_change_burns_token_and_no_gate_default(self):
        self.setup_facade(readings=[context(),replace(context(),boot_id="changed-boot-0001"),context()])
        result=self.facade.handle("execute_supervised_tv_switch",(self.token,),{})
        self.assertEqual(result["code"],"experimental_handoff.evidence_changed")
        self.events.clear();self.facade.handle("execute_supervised_tv_switch",(self.token,),{})
        self.assertNotIn("gate_factory",self.events)
        self.setup_facade(gate=False)
        self.assertFalse(self.facade.handle("execute_supervised_tv_switch",(self.token,),{})["accepted"])
        self.assertEqual(self.events,["read"])

    def test_concurrent_attempts_enter_gate_at_most_once(self):
        self.setup_facade()
        def attempt(_):return self.facade.handle("execute_supervised_tv_switch",(self.token,),{})
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(attempt,range(16)))
        self.assertTrue(all(result["accepted"] is False for result in results))
        self.assertEqual(self.events.count("gate_factory"),1)
        self.assertEqual(self.events.count("admit"),1)

    def test_failed_gate_never_restores_consumed_authority(self):
        self.setup_facade()
        def failed():raise ValueError("fixture failure")
        self.facade._gate_factory=failed
        result=self.facade.handle("execute_supervised_tv_switch",(self.token,),{})
        self.assertEqual(result["code"],"experimental_handoff.admission_unavailable")
        with self.assertRaises(ValueError):self.approvals.consume(self.token,current=self.current)


class SharedEngineCompositionTests(unittest.TestCase):
    """Real engine/mechanism; Linux uses real pinned journal/gate on temp files.

    Windows substitutes only the unsupported filesystem/lease boundary. Commands,
    config, sessions and discovery are inert everywhere; no native commands run.
    """
    def setUp(self):
        import tempfile
        from pathlib import Path
        from test_presentation_transition import observed,FakeIntegration,FakeConfig,USER,BOOT_ID
        from test_transition_orchestrator import FakeClockWaiter
        from regear.adapters.transition_runtime import versioned_snapshot_observation
        from regear.domain.models import SupportTier
        from regear.delivery.experimental_handoff_runtime import SharedHandoffComposition
        from regear.delivery.transition_journal_store import handoff_operation_id,FileTransitionJournalStore
        self.events=[];self.clock=FakeClockWaiter();self.config=FakeConfig(self.events)
        self.initial=replace(observed(),host_profile="gpd-win-mini-experimental",support_tier=SupportTier.EXPERIMENTAL)
        self.target=replace(observed("tv-docked.json"),host_profile="gpd-win-mini-experimental",support_tier=SupportTier.EXPERIMENTAL)
        self.state=self.initial;self.samples=0;self.invocation="a"*32;self.pid=self.initial.gamescope.pid;self.start=100
        self.change_invocation=True;self.fail_restart=False;self.fail_persist=False;self.correlate_snapshot=True
        generation=versioned_snapshot_observation(self.initial).generation
        self.context=replace(context(),host_profile_id="gpd-win-mini-experimental",
            egpu_profile_id="gpd-g1-rx7600mxt-titan-ridge",egpu_stable_id="gpd-g1:0123456789abcdef",
            snapshot_generation=generation,internal_gpu_id="internal-gpu",internal_display_id="internal-panel",
            external_display_id="external-tv",boot_id=BOOT_ID,session_unit="gamescope-session.service",
            session_target="gamescope-session.target",source_invocation_id=self.invocation,source_main_pid=self.pid,
            allowed_operations=tuple(__import__("regear.ports.presentation_activation",fromlist=["UserServiceOperation"]).UserServiceOperation(x)
                for x in ("daemon_reload","verify_gamescope_unit","restart_gamescope_session","observe_filter_gamescope")))
        self.approvals=HandoffApprovalStore()
        plan=handoff_operation_id("fixture-request",BOOT_ID,generation)
        self.token=self.approvals.issue(plan_id=plan,request_id="fixture-request",context=self.context,user_confirmed=True)
        fixture=self
        class Observations:
            def observe(self):
                fixture.samples+=1
                value=replace(fixture.state,observed_at=f"2026-10-18T00:00:{fixture.samples:02d}Z")
                return versioned_snapshot_observation(value)
        class Commands:
            def run(self,operation,**kwargs):
                from regear.ports.presentation_activation import UserServiceOperation
                fixture.events.append("command."+operation.value)
                fixture.assertGreater(kwargs["timeout_seconds"],0)
                if operation is UserServiceOperation.RESTART_GAMESCOPE_SESSION:
                    if fixture.fail_restart:
                        fixture.fail_restart=False
                        return NS(ok=False)
                    if fixture.change_invocation:
                        fixture.invocation="b"*32 if fixture.invocation=="a"*32 else "c"*32
                        fixture.pid+=1;fixture.start+=1
                    fixture.state=fixture.target if fixture.config.targets[-1] is PlacementState.DOCKED_EGPU else fixture.initial
                    if fixture.correlate_snapshot:
                        fixture.state=replace(fixture.state,gamescope=replace(fixture.state.gamescope,pid=fixture.pid))
                return NS(ok=True,output=f"MainPID={fixture.pid}\nInvocationID={fixture.invocation}\nActiveState=active\nControlGroup=/fixture-gamescope\n")
        def session(*,timeout_seconds):
            from regear.application.experimental_session_qualification import SessionEvidence
            fixture.assertGreater(timeout_seconds,0)
            c=fixture.context;t=fixture.clock.now_ms()/1000
            return SessionEvidence(c.boot_id,c.user_uid,c.user_context_sha256,fixture.pid,fixture.start,fixture.start,
                c.session_unit,(c.session_unit,),c.session_target,(c.session_unit,),fixture.pid,fixture.invocation,
                True,True,c.session_definition_sha256,c.integration_sha256,True,t,t)
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.fd=None
        if os.name=="posix":
            from regear.delivery.dock_mutation_gate import DockMutationGate
            self.fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
            self.gate=DockMutationGate(self.root,owner_uid=os.geteuid(),trusted_directory_fd=self.fd)
            self.store=FileTransitionJournalStore(self.root)
        else:
            class Lease:
                active=True
                @contextmanager
                def borrow(self,root):
                    if not self.active:raise ValueError("fixture stale lease")
                    yield None
            class Gate:
                @contextmanager
                def admit(self):
                    lease=Lease()
                    try:yield lease
                    finally:lease.active=False
            class Store:
                _root=fixture.root
                current=None
                def load_current(self):return self.current
                def persist_admitted(self,journal,*,admission,generation):
                    self.current=journal;store=self
                    return NS(is_current=lambda:admission.active and store.current==journal)
            self.gate=Gate();self.store=Store()
        original=self.store.persist_admitted
        def persist(*args,**kwargs):
            if fixture.fail_persist:raise OSError("fixture uncertain persistence")
            receipt=original(*args,**kwargs);fixture.events.append("durable."+args[0].entries[-1].kind.value)
            return receipt
        self.store.persist_admitted=persist
        self.composition=SharedHandoffComposition(observations=Observations(),journal_store=self.store,
            integration=FakeIntegration(events=self.events),config=self.config,commands=Commands(),
            resolve_user=lambda:NS(ok=True,context=USER),read_session=session,clock=self.clock,waiter=self.clock)

    def tearDown(self):
        if self.fd is not None:os.close(self.fd)
        self.temp.cleanup()

    def execute(self,read_context=None):
        approved=self.approvals.consume(self.token,current=self.context)
        self.events.append("approval.consumed")
        with self.gate.admit() as lease:
            self.events.append("gate.enter")
            result=self.composition.run(approved,lease,read_context=read_context or (lambda target:replace(self.context,
                source_invocation_id=self.invocation,source_main_pid=self.pid,
                snapshot_generation=__import__("regear.adapters.transition_runtime",fromlist=["versioned_snapshot_observation"])
                    .versioned_snapshot_observation(self.state).generation)))
        return result

    def test_real_shared_engine_commits_with_durable_order_and_exact_ids(self):
        from regear.domain.control_plane import TransitionOutcomeKind
        result=self.execute()
        self.assertEqual(result.outcome.kind,TransitionOutcomeKind.SUCCEEDED)
        self.assertTrue(result.durable)
        self.assertEqual(result.journal.request_id,"fixture-request")
        self.assertEqual(result.journal.origin_boot_id,self.context.boot_id)
        self.assertLess(self.events.index("approval.consumed"),self.events.index("gate.enter"))
        self.assertLess(self.events.index("durable.step_started"),self.events.index("command.daemon_reload"))
        self.assertEqual(self.events.count("command.restart_gamescope_session"),1)
        self.assertIn("durable.committed",self.events)
        with self.assertRaises(ValueError):self.approvals.consume(self.token,current=self.context)

    def test_unchanged_invocation_cannot_be_restart_success(self):
        from regear.domain.control_plane import TransitionOutcomeKind
        self.change_invocation=False
        result=self.execute()
        self.assertIsNot(result.outcome.kind,TransitionOutcomeKind.SUCCEEDED)
        self.assertLessEqual(self.events.count("command.restart_gamescope_session"),2)

    def test_uncertain_persistence_and_changed_context_have_zero_commands(self):
        self.fail_persist=True
        result=self.execute()
        self.assertFalse(result.durable)
        self.assertFalse(any(e.startswith("command.") for e in self.events))

    def test_changed_context_consumes_consent_and_refuses_before_effect(self):
        with self.assertRaises(ValueError):self.execute(lambda target:None)
        self.assertFalse(any(e.startswith("command.") for e in self.events))
        with self.assertRaises(ValueError):self.approvals.consume(self.token,current=self.context)

    def test_same_request_recovery_uses_durable_intent_and_bounded_restarts(self):
        from regear.domain.control_plane import TransitionOutcomeKind
        self.fail_restart=True
        result=self.execute()
        self.assertEqual(result.outcome.kind,TransitionOutcomeKind.RECOVERED)
        self.assertEqual(self.events.count("command.restart_gamescope_session"),2)
        second=self.events.index("command.restart_gamescope_session",self.events.index("command.restart_gamescope_session")+1)
        self.assertLess(self.events.index("durable.recovery_started"),second)

    def test_unknown_game_profile_or_changed_gpu_has_zero_native_commands(self):
        from regear.domain.models import GameState
        self.state=replace(self.initial,game_state=GameState.RUNNING)
        from regear.adapters.transition_runtime import versioned_snapshot_observation
        from regear.delivery.transition_journal_store import handoff_operation_id
        self.context=replace(self.context,snapshot_generation=versioned_snapshot_observation(self.state).generation)
        self.token=self.approvals.issue(plan_id=handoff_operation_id("fixture-request",self.context.boot_id,
            self.context.snapshot_generation),request_id="fixture-request",context=self.context,user_confirmed=True)
        with self.assertRaises(ValueError):self.execute()
        self.assertFalse(any(e.startswith("command.") for e in self.events))

    def test_unrelated_context_change_after_restart_cannot_commit(self):
        from regear.domain.control_plane import TransitionOutcomeKind
        from regear.adapters.transition_runtime import versioned_snapshot_observation
        def fresh(target):
            return replace(self.context,source_invocation_id=self.invocation,source_main_pid=self.pid,
                snapshot_generation=versioned_snapshot_observation(self.state).generation,
                integration_sha256="9"*64 if self.invocation!="a"*32 else self.context.integration_sha256)
        result=self.execute(fresh)
        self.assertIsNot(result.outcome.kind,TransitionOutcomeKind.SUCCEEDED)

    def test_process_lifetime_change_during_observation_refuses_before_effect(self):
        original=self.composition.observations.observe
        def changed():
            value=original();self.start+=1;return value
        self.composition.observations.observe=changed
        with self.assertRaises(ValueError):self.execute()
        self.assertFalse(any(e.startswith("command.") for e in self.events))

    def test_forward_render_from_different_gamescope_cannot_commit(self):
        from regear.domain.control_plane import TransitionOutcomeKind
        self.correlate_snapshot=False
        result=self.execute()
        self.assertIsNot(result.outcome.kind,TransitionOutcomeKind.SUCCEEDED)

    def test_recovery_render_from_different_gamescope_is_not_verified(self):
        from regear.domain.control_plane import TransitionOutcomeKind
        self.fail_restart=True;self.correlate_snapshot=False
        result=self.execute()
        self.assertIsNot(result.outcome.kind,TransitionOutcomeKind.RECOVERED)

    def test_unsupported_snapshot_does_not_fall_back_to_ally(self):
        from regear.delivery.experimental_handoff_runtime import feature_handoff_profiles
        from regear.domain.models import SupportTier
        result=feature_handoff_profiles(self.context,replace(self.initial,host_profile="asus-rog-ally-x",
                                                            support_tier=SupportTier.CERTIFIED))
        self.assertFalse(result.exact_host)
        self.assertFalse(result.exact_egpu)
        other=replace(self.context,host_profile_id="unknown-handheld")
        self.assertFalse(feature_handoff_profiles(other,replace(self.initial,host_profile=other.host_profile_id)).exact_host)
        self.assertFalse(feature_handoff_profiles(replace(self.context,egpu_profile_id="unknown-egpu"),self.initial).exact_egpu)
        feature=feature_handoff_profiles(self.context,self.initial)
        from regear.domain.control_plane import CapabilitySupport,RemovalBehavior,SleepBehavior
        self.assertEqual(feature.capabilities.display_handoff,CapabilitySupport.EXPERIMENTAL)
        self.assertEqual(feature.capabilities.power_button_interception,CapabilitySupport.UNKNOWN)
        self.assertEqual(feature.capabilities.removal_behavior,RemovalBehavior.UNKNOWN)
        self.assertEqual(feature.capabilities.sleep_behavior,SleepBehavior.UNTESTED)

    def test_expired_admission_and_consumed_composition_cannot_replay(self):
        approved=self.approvals.consume(self.token,current=self.context)
        with self.gate.admit() as lease:pass
        with self.assertRaises(Exception):self.composition.run(approved,lease,read_context=lambda target:self.context)
        with self.gate.admit() as lease:
            with self.assertRaises(ValueError):self.composition.run(approved,lease,read_context=lambda target:self.context)
        self.assertFalse(any(e.startswith("command.") for e in self.events))


if __name__ == "__main__":unittest.main()
