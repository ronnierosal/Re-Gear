"""Inert runner accounting only: no native ports or qualification collector."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import unittest

from test_experimental_handoff_approval import context
from regear.application.experimental_handoff_approval import HandoffApprovalStore, ApprovedHandoff, HandoffAudioPermission, HandoffAudioOperation
from regear.domain.control_plane import PlacementState
from regear.adapters.experimental_handoff_runner import (
    HandoffRunnerContract, RunnerOperation as Op, RecoveryIntent,
)
from regear.ports.presentation_activation import UserServiceOperation


class RunnerContractTests(unittest.TestCase):
    def make(self, qualified=True):
        self.now=0.0; self.calls=[];self.intent=None
        self.context=replace(context(),allowed_operations=tuple(UserServiceOperation(value) for value in (
            "daemon_reload", "verify_gamescope_unit", "restart_gamescope_session", "observe_filter_gamescope")))
        store=HandoffApprovalStore()
        token=store.issue(plan_id="fixture-request-001",context=self.context,user_confirmed=True)
        self.approved=store.consume(token,current=self.context)
        self.claim=(self.approved.permit.plan_id,"fixture-claim-001")
        self.runner=HandoffRunnerContract(approved=self.approved,claim_id=self.claim[1],
            qualified_context=self.context if qualified else None, clock=lambda:self.now,
            read_claim=lambda:self.claim, read_recovery_intent=lambda:self.intent)

    def port(self,timeout):self.calls.append(timeout);return True

    def recover(self):
        self.intent=RecoveryIntent(*self.claim,self.context.boot_id,True,True)
        return self.runner.begin_recovery()

    def test_unknown_qualification_or_changed_claim_denies_before_port(self):
        self.make(False)
        self.assertFalse(self.runner.attempt(Op.PREFLIGHT_SNAPSHOT,self.port).accepted)
        self.assertEqual(self.calls,[])
        self.make();self.claim=("other-request","fixture-claim-001")
        self.assertFalse(self.runner.begin_forward())
        self.assertFalse(self.runner.attempt(Op.RESTART,self.port).accepted)
        self.assertEqual(self.calls,[])

    def test_each_operation_counts_before_delegate_and_cannot_retry_in_phase(self):
        for operation in (Op.RELOAD,Op.VERIFY_UNIT,Op.RESTART):
            self.make();self.assertTrue(self.runner.begin_forward())
            def failed(timeout):self.calls.append(timeout);raise TimeoutError()
            self.assertFalse(self.runner.attempt(operation,failed).accepted)
            self.assertFalse(self.runner.attempt(operation,self.port).accepted)
            self.assertEqual(len(self.calls),1)
            self.assertTrue(self.recover())
            self.assertTrue(self.runner.attempt(operation,self.port).accepted)
            self.assertFalse(self.runner.attempt(operation,self.port).accepted)
            self.assertEqual(len(self.calls),2)

    def test_read_caps_and_phase_allowlist(self):
        self.make()
        for _ in range(4):self.assertTrue(self.runner.attempt(Op.PREFLIGHT_SNAPSHOT,self.port).accepted)
        self.assertFalse(self.runner.attempt(Op.PREFLIGHT_SNAPSHOT,self.port).accepted)
        self.make();self.runner.begin_forward()
        self.assertFalse(self.runner.attempt(Op.OBSERVE_INVOCATION,self.port).accepted)
        for _ in range(64):self.assertTrue(self.runner.attempt(Op.SNAPSHOT,self.port).accepted)
        self.assertFalse(self.runner.attempt(Op.SNAPSHOT,self.port).accepted)
        self.make();self.runner.begin_forward();self.assertTrue(self.recover())
        for _ in range(62):self.assertTrue(self.runner.attempt(Op.OBSERVE_INVOCATION,self.port).accepted)
        self.assertFalse(self.runner.attempt(Op.OBSERVE_INVOCATION,self.port).accepted)
        self.assertTrue(all(timeout<=.25 for timeout in self.calls))

    def test_one_global_deadline_and_phase_remaining_are_not_reset(self):
        self.make();self.now=4;self.assertTrue(self.runner.begin_forward())
        self.now=18;self.assertTrue(self.runner.attempt(Op.RELOAD,self.port).accepted)
        self.assertEqual(self.calls[-1],1)
        self.now=19;self.assertTrue(self.recover())
        self.now=33.5;self.assertTrue(self.runner.attempt(Op.RELOAD,self.port).accepted)
        self.assertEqual(self.calls[-1],.5)
        self.now=34;self.assertFalse(self.runner.attempt(Op.VERIFY_UNIT,self.port).accepted)
        self.assertFalse(self.recover())

    def test_recovery_requires_same_durable_revalidated_intent_and_only_once(self):
        for change in (dict(request_id="wrong"),dict(claim_id="wrong"),dict(boot_id="wrong"),
                       dict(durable=False),dict(source_revalidated=False)):
            self.make();self.runner.begin_forward()
            self.intent=replace(RecoveryIntent(*self.claim,self.context.boot_id,True,True),**change)
            self.assertFalse(self.runner.begin_recovery())
            self.assertEqual(self.calls,[])
        self.make();self.runner.begin_forward();self.assertTrue(self.recover());self.assertFalse(self.recover())

    def test_unsupported_operations_and_nonfinite_or_backward_time_deny(self):
        for bad in ("restart",None,object()):
            self.make();self.assertFalse(self.runner.attempt(bad,self.port).accepted)
        for bad in (float("nan"),float("inf"),-1,True):
            self.make();self.now=bad
            self.assertFalse(self.runner.begin_forward());self.assertEqual(self.calls,[])

    def test_concurrent_restart_budget_and_cancellation_cannot_escape(self):
        self.make();self.runner.begin_forward()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:self.runner.attempt(Op.RESTART,self.port),range(16)))
        self.assertEqual(sum(result.accepted for result in results),1)
        self.assertEqual(len(self.calls),1)
        self.make();self.runner.begin_forward()
        def cancelled(timeout):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.runner.attempt(Op.RESTART,cancelled)
        self.assertFalse(self.recover());self.assertFalse(self.runner.attempt(Op.RESTART,self.port).accepted)

    def test_recovery_probe_time_and_attempt_are_not_free(self):
        self.make();self.runner.begin_forward()
        self.intent=RecoveryIntent(*self.claim,self.context.boot_id,True,True)
        def late_intent():self.now=36;return self.intent
        self.runner._read_recovery_intent=late_intent
        self.assertFalse(self.runner.begin_recovery())
        self.make();self.runner.begin_forward()
        self.assertFalse(self.runner.begin_recovery())
        self.assertFalse(self.recover())  # A failed intent read cannot be retried.

    def test_uncertain_reply_and_cancelled_claim_check_cannot_resume(self):
        self.make();self.runner.begin_forward()
        class BadReply:
            @property
            def ok(self):raise ValueError("uncertain reply")
        self.assertFalse(self.runner.attempt(Op.RESTART,lambda timeout:BadReply()).accepted)
        self.assertFalse(self.runner.attempt(Op.VERIFY_UNIT,self.port).accepted)
        self.make();self.runner.begin_forward()
        def cancelled_claim():raise KeyboardInterrupt()
        self.runner._read_claim=cancelled_claim
        with self.assertRaises(KeyboardInterrupt):self.runner.attempt(Op.RESTART,self.port)
        self.runner._read_claim=lambda:self.claim
        self.assertFalse(self.recover())

    def test_per_call_deadline_is_checked_even_when_phase_has_time(self):
        self.make();self.runner.begin_forward();self.assertTrue(self.recover())
        def late_success(timeout):
            self.assertEqual(timeout,.25);self.now+=1;return True
        self.assertFalse(self.runner.attempt(Op.OBSERVE_INVOCATION,late_success).accepted)
        self.assertFalse(self.runner.attempt(Op.RESTART,self.port).accepted)

    def test_invalid_or_failed_recovery_probe_cannot_resume_forward(self):
        for invalid in (None,RecoveryIntent("wrong", "wrong", "wrong",True,True)):
            self.make();self.runner.begin_forward();self.intent=invalid
            self.assertFalse(self.runner.begin_recovery())
            self.assertFalse(self.runner.attempt(Op.RESTART,self.port).accepted)
            self.assertEqual(self.calls,[])
        self.make();self.runner.begin_forward()
        def failed_intent():raise ValueError("fixture failure")
        self.runner._read_recovery_intent=failed_intent
        self.assertFalse(self.runner.begin_recovery())
        self.assertFalse(self.runner.attempt(Op.RESTART,self.port).accepted)


    def test_contradictory_permit_denies_before_claim_or_delegate(self):
        changes = (
            dict(observed_generation="f" * 64),
            dict(target_placement=PlacementState.PORTABLE),
            dict(host_profile_id="different-host"),
            dict(egpu_profile_id="different-egpu"),
            dict(egpu_stable_id="different-stable-id"),
            dict(target_placement=PlacementState.PORTABLE, portable_vulkan_trial=True),
        )
        for change in changes:
            with self.subTest(change=change):
                self.make()
                probes=[]
                approved=ApprovedHandoff(replace(self.approved.permit,**change),self.context)
                runner=HandoffRunnerContract(approved=approved,claim_id=self.claim[1],
                    qualified_context=self.context,clock=lambda:self.now,
                    read_claim=lambda:probes.append(True) or self.claim,
                    read_recovery_intent=lambda:None)
                self.assertFalse(runner.begin_forward())
                self.assertFalse(runner.attempt(Op.RESTART,self.port).accepted)
                self.assertEqual(probes,[])
                self.assertEqual(self.calls,[])
        self.make()
        runner=HandoffRunnerContract(approved=ApprovedHandoff(None,self.context),
            claim_id=self.claim[1],qualified_context=self.context,clock=lambda:self.now,
            read_claim=lambda:self.fail("unqualified claim probe"),read_recovery_intent=lambda:None)
        self.assertFalse(runner.begin_forward())

    def test_unqualified_audio_and_storage_operations_refuse_before_delegate(self):
        self.make();self.runner.begin_forward()
        for op in (Op.AUDIO_DUMP,Op.AUDIO_SET_DEFAULT,Op.SAFETY_STATE_WRITE):
            self.assertFalse(self.runner.attempt(op,self.port).accepted)
        self.assertEqual(self.calls,[])

    def test_approved_audio_requires_fresh_validation_and_spends_phase_budget(self):
        from regear.adapters.experimental_handoff_runner import AudioValidation
        self.make()
        permission=HandoffAudioPermission("a"*64,"b"*64,"c"*64,tuple(HandoffAudioOperation))
        self.context=replace(self.context,audio=permission)
        store=HandoffApprovalStore();token=store.issue(plan_id=self.claim[0],context=self.context,user_confirmed=True)
        approved=store.consume(token,current=self.context)
        targets=[]
        def validate(operation,target,timeout):
            targets.append(target)
            return AudioValidation(permission,self.claim[0],self.claim[1],self.context.boot_id,
                self.context.user_context_sha256,self.context.snapshot_generation,target,True,self.now)
        runner=HandoffRunnerContract(approved=approved,claim_id=self.claim[1],qualified_context=self.context,
            read_claim=lambda:self.claim,read_recovery_intent=lambda:RecoveryIntent(
                *self.claim,self.context.boot_id,True,True),read_audio=validate,clock=lambda:self.now)
        self.assertTrue(runner.begin_forward())
        self.assertTrue(runner.attempt(Op.AUDIO_SET_DEFAULT,self.port).accepted)
        self.assertFalse(runner.attempt(Op.AUDIO_SET_DEFAULT,self.port).accepted)
        self.assertTrue(runner.begin_recovery())
        self.assertTrue(runner.attempt(Op.AUDIO_SET_DEFAULT,self.port).accepted)
        self.assertFalse(runner.attempt(Op.AUDIO_SET_DEFAULT,self.port).accepted)
        self.assertEqual(targets,[permission.target_sink_sha256,permission.rollback_sink_sha256])
        self.assertEqual(len(self.calls),2)

    def audio_fixture(self, transform=lambda e:e, validation_delay=0):
        from regear.adapters.experimental_handoff_runner import AudioValidation
        self.make()
        permission=HandoffAudioPermission("a"*64,"b"*64,"c"*64,tuple(HandoffAudioOperation))
        self.context=replace(self.context,audio=permission)
        store=HandoffApprovalStore();token=store.issue(plan_id=self.claim[0],context=self.context,user_confirmed=True)
        approved=store.consume(token,current=self.context)
        def validate(op,target,timeout):
            self.now+=validation_delay
            return transform(AudioValidation(permission,*self.claim,self.context.boot_id,
                self.context.user_context_sha256,self.context.snapshot_generation,target,True,self.now))
        runner=HandoffRunnerContract(approved=approved,claim_id=self.claim[1],qualified_context=self.context,
            read_claim=lambda:self.claim,read_recovery_intent=lambda:RecoveryIntent(
                *self.claim,self.context.boot_id,True,True),read_audio=validate,clock=lambda:self.now)
        self.assertTrue(runner.begin_forward())
        return runner

    def test_audio_validation_mismatch_stale_unknown_and_failure_never_delegate(self):
        changes=(dict(request_id="wrong"),dict(claim_id="wrong"),dict(boot_id="wrong"),
            dict(user_context_sha256="d"*64),dict(snapshot_generation="d"*64),
            dict(target_sink_sha256="d"*64),dict(available=1),dict(available=False),
            dict(permission=None),dict(observed_at=-2),dict(observed_at=1),
            dict(observed_at=float("nan")),dict(observed_at=10**1000))
        for change in changes:
            with self.subTest(fields=tuple(change)):
                runner=self.audio_fixture(lambda e:replace(e,**change))
                self.assertFalse(runner.attempt(Op.AUDIO_SET_DEFAULT,self.port).accepted)
                self.assertFalse(runner.attempt(Op.AUDIO_DUMP,self.port).accepted)
                self.assertEqual(self.calls,[])
        runner=self.audio_fixture(lambda e:None)
        self.assertFalse(runner.attempt(Op.AUDIO_SET_DEFAULT,self.port).accepted)
        self.assertEqual(self.calls,[])

    def test_audio_time_is_spent_and_failed_calls_cannot_retry(self):
        runner=self.audio_fixture(validation_delay=.25)
        self.assertTrue(runner.attempt(Op.AUDIO_DUMP,self.port).accepted)
        self.assertEqual(self.calls,[.75])
        runner=self.audio_fixture(validation_delay=1.1)
        self.assertFalse(runner.attempt(Op.AUDIO_DUMP,self.port).accepted)
        self.assertEqual(self.calls,[])
        runner=self.audio_fixture()
        def failed(timeout):self.calls.append(timeout);raise TimeoutError()
        self.assertFalse(runner.attempt(Op.AUDIO_SET_DEFAULT,failed).accepted)
        self.assertFalse(runner.attempt(Op.AUDIO_SET_DEFAULT,self.port).accepted)
        self.assertEqual(len(self.calls),1)

    def test_audio_dump_cumulative_caps_and_storage_stays_unavailable(self):
        runner=self.audio_fixture()
        for _ in range(16):self.assertTrue(runner.attempt(Op.AUDIO_DUMP,self.port).accepted)
        self.assertFalse(runner.attempt(Op.AUDIO_DUMP,self.port).accepted)
        self.assertTrue(runner.begin_recovery())
        for _ in range(16):self.assertTrue(runner.attempt(Op.AUDIO_DUMP,self.port).accepted)
        self.assertFalse(runner.attempt(Op.AUDIO_DUMP,self.port).accepted)
        self.assertEqual(len(self.calls),32)
        self.assertFalse(runner.attempt(Op.SAFETY_STATE_WRITE,self.port).accepted)
        self.assertEqual(len(self.calls),32)

if __name__=="__main__":unittest.main()
