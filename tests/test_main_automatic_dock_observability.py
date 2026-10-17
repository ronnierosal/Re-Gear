"""Actual automatic-dock loop with fake IO; no device or compositor commands."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock,Mock,patch

from tests.test_main_process_delivery import load_main_module
from tests.test_automatic_dock import current
from regear.application.connection_readiness import ConnectionReadinessStage as Stage,ConnectionReadinessStatus
from regear.application.presentation_completion import PresentationCompletion
from regear.domain.control_plane import TransitionOutcomeKind
from regear.domain.models import Confidence,GameState,GpuRole


class AutomaticDockObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def journey(self,snapshots,*,enabled=True,ready_stage=Stage.READY_IDLE,failures=None,suppressed=False,logging_fails=False,result_code='transition.succeeded'):
        module=load_main_module();plugin=module.Plugin();index=0;dispatches=[];journey=[];log_attempts=[]
        base=current('connected-internal.json')
        def observation():
            if (failures or {}).get(index)=='snapshot':raise ValueError('/private/identity secret')
            return replace(base,snapshot=snapshots[index],observation_id='private-sample-'+str(index))
        def observer_factory(_):
            if (failures or {}).get(index)=='observer_factory':raise ValueError('/private/observer secret')
            return NS(observe=observation)
        def preference():
            if (failures or {}).get(index)=='preferences':raise ValueError('/private/preference secret')
            return enabled
        async def connection(_):
            if (failures or {}).get(index)=='connection_readiness':raise ValueError('/private/topology secret')
            stage=ready_stage[index] if isinstance(ready_stage,list) else ready_stage
            return ConnectionReadinessStatus(stage,'connection.ready_idle' if stage is Stage.READY_IDLE else 'connection.fixture_wait',1000)
        def completion(_):
            if (failures or {}).get(index)=='completion':raise ValueError('/private/completion secret')
            return PresentationCompletion('completion.fixture')
        def execute(*args):
            dispatches.append(index)
            return NS(accepted=True,code=result_code,outcome=NS(kind=TransitionOutcomeKind.SUCCEEDED) if result_code=='transition.succeeded' else None)
        async def wait(_):
            nonlocal index
            index+=1
            if index>=len(snapshots):raise asyncio.CancelledError
        def append(**event):
            if event['code'].startswith('automatic_dock.decision.'):
                log_attempts.append(event)
                if logging_fails:raise OSError('private sink failure')
            journey.append(event)
        plugin._automatic_dock_preferences=lambda:NS(load=preference)
        plugin._observe_connection_readiness=connection
        plugin._maybe_automatic_link_recovery=AsyncMock(return_value=False)
        plugin._presentation_transition_service=lambda:NS(reconcile_completion=completion)
        plugin._update_saved_tv=AsyncMock()
        plugin._run_automatic_tv_transition=execute
        plugin._wait_for_topology=wait;plugin._append_journey_event=append
        plugin._events=NS(append=lambda **event:None)
        if suppressed:plugin._automatic_dock.suppress_current_attachment_after_portable_return()
        with patch.object(module,'SnapshotTransitionObservationAdapter',side_effect=observer_factory),patch.object(module,'GamescopeDiscovery',return_value=NS(scan=lambda:None)),patch.object(module,'resolve_gamescope_user',return_value=NS(ok=False,context=None)):
            with self.assertRaises(asyncio.CancelledError):await plugin._automatic_dock_loop()
        return plugin,dispatches,journey,log_attempts

    async def test_disabled_and_exact_profile_refusals_are_visible_without_dispatch(self):
        exact=current('connected-internal.json').snapshot
        unknown_host=replace(exact,host_profile='unknown')
        unknown_gpu=replace(exact,gpus=tuple(replace(g,confidence=Confidence.UNKNOWN) if g.role is GpuRole.EXTERNAL else g for g in exact.gpus))
        for snapshot,enabled,category,code in ((exact,False,'disabled','automatic_dock.disabled'),(unknown_host,True,'exact_profile_unverified','automatic_dock.waiting_for_exact_g1'),(unknown_gpu,True,'exact_profile_unverified','automatic_dock.waiting_for_exact_g1')):
            with self.subTest(category=category,enabled=enabled):
                plugin,calls,events,_=await self.journey([snapshot]*3,enabled=enabled)
                decisions=[e for e in events if e['code'].startswith('automatic_dock.decision.')]
                self.assertEqual([],calls);self.assertEqual(1,len(decisions));self.assertEqual('automatic_dock.decision.'+category,decisions[0]['code'])
                self.assertEqual(code,plugin._automatic_dock.status().code)
                self.assertNotIn('private-',repr(decisions));self.assertNotIn('binding',repr(decisions))

    async def test_existing_ready_dispatch_and_one_shot_failure_are_unchanged(self):
        exact=current('connected-internal.json').snapshot
        plugin,calls,events,_=await self.journey([exact]*3,result_code='transition.failed')
        self.assertEqual([0],calls);self.assertEqual('transition.failed',plugin._automatic_dock.status().code)
        codes=[e['code'] for e in events if e['code'].startswith('automatic_dock.decision.')]
        self.assertEqual(['automatic_dock.decision.dispatch_requested','automatic_dock.decision.action_required'],codes)

    async def test_game_and_suppression_guards_remain_non_dispatching(self):
        exact=current('connected-internal.json').snapshot
        _,calls,events,_=await self.journey([replace(exact,game_state=GameState.RUNNING)]*2,ready_stage=Stage.GAME_RUNNING)
        self.assertEqual([],calls);self.assertEqual(1,sum(e['code']=='automatic_dock.decision.waiting' for e in events))
        _,calls,events,_=await self.journey([exact]*2,suppressed=True)
        self.assertEqual([],calls);self.assertEqual(1,sum(e['code']=='automatic_dock.decision.suppressed' for e in events))

    async def test_failure_stage_is_sanitized_deduplicated_and_rearmed_after_success(self):
        exact=current('connected-internal.json').snapshot
        _,calls,events,_=await self.journey([exact]*4,enabled=False,failures={0:'snapshot',1:'snapshot',3:'snapshot'})
        failures=[e for e in events if e['code']=='automatic_dock.observation_failed']
        self.assertEqual([],calls);self.assertEqual(2,len(failures));self.assertTrue(all(e['stage']=='snapshot' for e in failures));self.assertNotIn('secret',repr(failures));self.assertNotIn('/private',repr(failures))
        for stage in ('preferences','connection_readiness','completion'):
            _,_,events,_=await self.journey([exact]*2,enabled=False,failures={0:stage,1:stage})
            failures=[e for e in events if e['code']=='automatic_dock.observation_failed']
            self.assertEqual(1,len(failures));self.assertEqual(stage,failures[0]['stage'])

    async def test_decision_logging_failure_does_not_block_dispatch_or_rearm(self):
        exact=current('connected-internal.json').snapshot
        _,calls,_,attempts=await self.journey([exact]*3,logging_fails=True,result_code='transition.failed')
        self.assertEqual([0],calls);self.assertEqual(2,len(attempts))

    async def test_observer_factory_failure_is_visible_and_recovers_without_dispatch(self):
        exact=current('connected-internal.json').snapshot
        _,calls,events,_=await self.journey([exact]*3,enabled=False,failures={0:'observer_factory',1:'observer_factory'})
        self.assertEqual([],calls)
        self.assertEqual(1,sum(e['code']=='automatic_dock.observation_failed' and e['stage']=='observer_factory' for e in events))
        self.assertEqual(1,sum(e['code']=='automatic_dock.decision.disabled' for e in events))

    def test_shared_normal_event_and_logger_receive_only_finite_decision_data(self):
        module=load_main_module();plugin=module.Plugin();logger=Mock()
        plugin._diagnostic_logging._boot_session_id=lambda:'fixture-boot'
        self.assertFalse(plugin._diagnostic_logging.status().enabled)
        with patch.object(module.decky,'logger',logger):
            for n in range(100):
                plugin._record_automatic_dock_decision(NS(status=NS(stage=module.AutomaticDockStage.ACTION_REQUIRED,code='/private/secret-'+str(n)),should_switch=False))
                plugin._record_automatic_dock_observation_failure('/private/secret-'+str(n))
        events=plugin._events.snapshot()
        self.assertEqual(2,len(events));self.assertEqual(2,logger.info.call_count)
        self.assertNotIn('secret',repr(events)+repr(logger.info.call_args_list))
        self.assertEqual(('action_required','action_required',False,'unavailable'),plugin._last_automatic_dock_decision_event)
        self.assertEqual('unknown',plugin._last_automatic_dock_observation_failure)

    async def test_hot_attach_readiness_changes_remain_visible_under_same_policy_gate(self):
        unknown=replace(current('connected-internal.json').snapshot,host_profile='unknown')
        stages=[Stage.TRANSPORT_DETECTED,Stage.WAITING_FOR_DRIVER,Stage.READY_IDLE,Stage.READY_IDLE]
        _,calls,events,_=await self.journey([unknown]*4,ready_stage=stages)
        decisions=[e for e in events if e['code'].startswith('automatic_dock.decision.')]
        self.assertEqual([],calls);self.assertEqual(3,len(decisions))
        self.assertTrue(all(e['code']=='automatic_dock.decision.exact_profile_unverified' for e in decisions))
        self.assertEqual([s.value for s in stages[:3]],[e['details']['readiness_stage'] for e in decisions])


if __name__=='__main__':unittest.main()
