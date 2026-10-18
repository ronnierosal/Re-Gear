"""Local request-boundary tests; executor is deliberately absent."""
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


if __name__ == "__main__":unittest.main()
