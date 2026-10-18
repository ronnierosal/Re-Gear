"""Experimental request boundary and shared-engine source fixture composition.

Read/gate ports are server-owned constructor dependencies, never RPC inputs.
The shipped composition supplies no qualified session context and no gate.
"""
import threading
from typing import Callable

from ..application.experimental_handoff_approval import HandoffApprovalStore, HandoffContext
from ..domain.control_plane import PlacementState


HANDOFF_METHODS = frozenset({
    "preview_supervised_tv_switch", "approve_supervised_tv_switch", "execute_supervised_tv_switch",
    "approve_supervised_portable_switch", "execute_supervised_portable_switch",
    "get_transition_journal_status",
})


def unavailable(code="experimental_handoff.unavailable"):
    return {"schema_version":1, "code":code, "accepted":False, "ready":False,
            "requested":False, "operation_started":False, "safe_to_unplug":False,
            "approval_token":"", "action_required":False}


class ExperimentalHandoffRuntime:
    def __init__(self, *, read_context: Callable[[PlacementState], HandoffContext | None],
                 approvals: HandoffApprovalStore | None = None, gate_factory: Callable | None = None):
        self._read_context = read_context
        self._approvals = approvals or HandoffApprovalStore()
        self._gate_factory = gate_factory
        self._lock = threading.Lock()

    def _context(self, target):
        try:
            current = self._read_context(target)
            return current if type(current) is HandoffContext and current.target_placement is target else None
        except Exception:
            return None

    def handle(self, method, args, kwargs):
        if method not in HANDOFF_METHODS:
            return unavailable()
        target = PlacementState.PORTABLE if "portable" in method else PlacementState.DOCKED_EGPU
        if not method.startswith("execute_"):
            # No engine, journal repair, acknowledgement, approval consumption or
            # token issuance is reachable through this read-only boundary slice.
            current = self._context(target)
            return unavailable("experimental_handoff.executor_unavailable" if current is not None
                               else "experimental_handoff.session_unqualified")
        if len(args) == 1 and not kwargs:
            token = args[0]
        elif not args and set(kwargs) == {"approval_token"}:
            token = kwargs["approval_token"]
        else:
            return unavailable("experimental_handoff.request_invalid")
        if not self._lock.acquire(blocking=False):
            return unavailable("experimental_handoff.busy")
        try:
            current = self._context(target)
            try:
                approved = self._approvals.consume(token, current=current)
            except ValueError:
                return unavailable("experimental_handoff.approval_unavailable")
            # No production gate/executor is wired in this slice. Inert injected
            # gates exercise consume/admission/recheck ordering in software only.
            if self._gate_factory is None:
                return unavailable("experimental_handoff.executor_unavailable")
            try:
                with self._gate_factory().admit():
                    if self._context(target) != approved.context:
                        return unavailable("experimental_handoff.evidence_changed")
                    return unavailable("experimental_handoff.executor_unavailable")
            except Exception:
                return unavailable("experimental_handoff.admission_unavailable")
        finally:
            self._lock.release()


class AdmissionBoundHandoffJournal:
    """Shared engine port; every save requires the same live normal admission."""
    def __init__(self, store, admission, approved):
        from .transition_journal_store import handoff_operation_id
        c=approved.context
        if (not approved.request_id or approved.permit.plan_id != handoff_operation_id(
                approved.request_id,c.boot_id,c.snapshot_generation)):
            raise ValueError("handoff request/plan binding is unavailable")
        self.store,self.admission,self.approved=store,admission,approved
        self.current=None
        self.receipt=None

    def load_current(self):
        # This initial advisory read never grants effect authority. The pinned
        # save independently checks existing state before issuing any receipt.
        with self.admission.borrow(self.store._root):
            return self.store.load_current()

    def save(self,journal):
        c=self.approved.context
        # Invalidate first: failed/uncertain saves cannot reuse an older proof.
        self.receipt=None
        if (journal.operation_id != self.approved.permit.plan_id
                or journal.request_id != self.approved.request_id
                or journal.origin_boot_id != c.boot_id):
            raise ValueError("handoff journal continuity changed")
        receipt=self.store.persist_admitted(journal,admission=self.admission,
                                            generation=c.snapshot_generation)
        self.current,self.receipt=journal,receipt

    def require_effect(self,recovery=False):
        from ..domain.transition_journal import JournalEventKind
        expected=JournalEventKind.RECOVERY_STARTED if recovery else JournalEventKind.STEP_STARTED
        if (self.receipt is None or not self.receipt.is_current() or self.current is None
                or not self.current.entries or self.current.entries[-1].kind is not expected):
            raise ValueError("handoff durable intent unavailable")


def feature_handoff_profiles(context,snapshot):
    """Feature-only resolution; never registers a host or certifies a snapshot.

    A caller must authenticate context before construction. This compares exact
    identities only; it is not a collector and cannot qualify a real machine.
    """
    from ..domain.control_plane import (HostCapabilities,EgpuCapabilities,CapabilitySupport,
        EgpuTransport,compose_capabilities,UNKNOWN_HOST_CAPABILITIES,UNKNOWN_EGPU_CAPABILITIES)
    from ..domain.models import Confidence,GpuRole,SupportTier
    from ..profiles.win_mini import PROFILE_ID as MINI_PROFILE
    from ..profiles.gpd_g1 import PROFILE_ID as G1_PROFILE, STABLE_ID_PATTERN
    from ..profiles.registry import ResolvedRuntimeProfiles,ProfileResolutionStatus
    unknown=ResolvedRuntimeProfiles(compose_capabilities(UNKNOWN_HOST_CAPABILITIES,
        UNKNOWN_EGPU_CAPABILITIES),False,False,ProfileResolutionStatus.UNKNOWN,ProfileResolutionStatus.UNKNOWN)
    if (type(context) is not HandoffContext or context.host_profile_id!=MINI_PROFILE
            or context.egpu_profile_id!=G1_PROFILE
            or STABLE_ID_PATTERN.fullmatch(context.egpu_stable_id) is None
            or snapshot.host_profile != context.host_profile_id):
        return unknown
    if snapshot.support_tier is not SupportTier.EXPERIMENTAL:
        return unknown
    external=tuple(g for g in snapshot.gpus if g.role is GpuRole.EXTERNAL and g.present
                   and g.confidence is Confidence.VERIFIED)
    if (len(external)!=1 or external[0].stable_id!=context.egpu_stable_id
            or snapshot.disconnect_readiness.egpu_stable_id!=context.egpu_stable_id
            or not snapshot.disconnect_readiness.applicable
            or any(b.code=="egpu_identity_unverified" for b in snapshot.blockers)):
        return unknown
    host=HostCapabilities(context.host_profile_id,egpu_support=CapabilitySupport.EXPERIMENTAL,
        egpu_transport=EgpuTransport.USB4,display_handoff=CapabilitySupport.EXPERIMENTAL)
    egpu=EgpuCapabilities(context.egpu_profile_id,display_output=CapabilitySupport.EXPERIMENTAL)
    return ResolvedRuntimeProfiles(compose_capabilities(host,egpu),True,True,
        ProfileResolutionStatus.EXACT,ProfileResolutionStatus.EXACT,context.egpu_stable_id,egpu)


class SharedHandoffComposition:
    """Actual shared engine composition for injected, inert source fixtures.

    No shipped caller constructs this class. It does not authenticate evidence,
    discover hardware, build native ports, or grant device eligibility. Main's
    context remains unavailable. Audio mutation is deliberately unsupported here:
    the native audio/config store composition remains a separate package gate.
    """
    def __init__(self,*,observations,journal_store,integration,config,commands,
                 resolve_user,read_session,clock,waiter):
        self.observations,self.store=observations,journal_store
        self.integration,self.config,self.commands=integration,config,commands
        self.resolve_user,self.read_session=resolve_user,read_session
        self.clock,self.waiter=clock,waiter
        self._used=False
        self._execution_lock=threading.Lock()

    def run(self,approved,admission,*,read_context):
        if not self._execution_lock.acquire(blocking=False):
            raise ValueError("handoff composition busy")
        try:
            if self._used:raise ValueError("handoff composition already consumed")
            self._used=True
            return self._run(approved,admission,read_context=read_context)
        finally:
            self._execution_lock.release()

    def _run(self,approved,admission,*,read_context):
        from dataclasses import replace
        import secrets
        from types import SimpleNamespace
        from ..application.experimental_handoff_approval import ApprovedHandoff
        from ..application.experimental_session_qualification import qualify_session,SessionEvidence
        from ..application.transition_orchestrator import TransitionOrchestrator
        from ..application.transition_runtime_policy import StrictRuntimeTransitionPolicy
        from ..adapters.experimental_handoff_runner import HandoffRunnerContract,RunnerOperation,RecoveryIntent
        from ..adapters.presentation_transition import PresentationTransitionMechanism
        from ..domain.manual_transition import evidence_from_snapshot,plan_manual_transition
        from ..domain.inference import infer_placement
        from ..domain.transition_journal import JournalEventKind
        from ..ports.presentation_activation import UserServiceOperation
        from ..ports.transition import VersionedObservation
        if type(approved) is not ApprovedHandoff or approved.context.audio is not None:
            raise ValueError("shared handoff composition is display-fixture only")
        c=approved.context
        journal=AdmissionBoundHandoffJournal(self.store,admission,approved)
        session=[None]
        restart_verified=[False]
        last_generation=[c.snapshot_generation]
        def context_current():
            value=read_context(c.target_placement)
            if type(value) is not HandoffContext:return False
            expected=c
            if restart_verified[0]:
                # Only a replacement verified after this request's bounded
                # restart may change invocation/PID. GPU generation must match
                # the actual latest shared-engine observation, not arbitrary
                # caller data; every other immutable field stays exact.
                expected=replace(c,source_invocation_id=session[0].invocation_id,
                    source_main_pid=session[0].pid,snapshot_generation=last_generation[0])
            return value==expected
        if not context_current():
            raise ValueError("handoff context changed")
        claim=secrets.token_hex(16)
        recovery=[False]
        now=lambda:self.clock.now_ms()/1000

        def read_claim():
            with admission.borrow(self.store._root):
                return approved.permit.plan_id,claim

        def session_valid(e,expected):
            if type(e) is not SessionEvidence:
                return False
            if any(type(getattr(e,name)) is not str for name in (
                    "boot_id","user_context_sha256","unit","target","invocation_id",
                    "definition_sha256","integration_sha256")):
                return False
            if expected is not None and (e.pid,e.start_before,e.invocation_id)!=(
                    expected.pid,expected.start_before,expected.invocation_id):
                return False
            expected_context=replace(c,source_invocation_id=expected.invocation_id,
                                     source_main_pid=expected.pid) if expected is not None else c
            return qualify_session(expected_context,e,now=now())

        def recovery_intent():
            journal.require_effect(True)
            fresh=self.read_session(timeout_seconds=.25)
            if not session_valid(fresh,session[0]):
                raise ValueError("recovery source changed")
            return RecoveryIntent(approved.permit.plan_id,claim,c.boot_id,True,True)

        runner=HandoffRunnerContract(approved=approved,qualified_context=c,claim_id=claim,
            read_claim=read_claim,read_recovery_intent=recovery_intent,clock=now)

        def collect_session(preflight=False):
            box=[]
            def collect(timeout):
                e=self.read_session(timeout_seconds=timeout)
                if not session_valid(e,session[0]):return False
                box.append(e);return True
            op=RunnerOperation.PREFLIGHT_SNAPSHOT if preflight else RunnerOperation.SNAPSHOT
            if not runner.attempt(op,collect).accepted:
                raise ValueError("handoff fresh session unavailable")
            if session[0] is None:session[0]=box[0]
            return box[0]

        collect_session(True)
        if not runner.begin_forward():raise ValueError("handoff budget unavailable")

        def enter_recovery():
            if not recovery[0] and journal.current is not None and journal.current.entries[-1].kind is JournalEventKind.RECOVERY_STARTED:
                if not runner.begin_recovery():raise ValueError("handoff recovery unavailable")
                recovery[0]=True

        def guard(*,fresh=True):
            enter_recovery()
            journal.require_effect(recovery[0])
            if not context_current():
                raise ValueError("handoff immutable context changed")
            if fresh:collect_session()

        composition=self
        class Observations:
            def observe(self):
                enter_recovery()
                box=[]
                def collect(timeout):
                    from ..domain.models import Confidence
                    started=now()
                    before=composition.read_session(timeout_seconds=timeout)
                    if not session_valid(before,session[0]):return False
                    value=composition.observations.observe()
                    remaining=timeout-(now()-started)
                    if remaining<=0:return False
                    after=composition.read_session(timeout_seconds=remaining)
                    if (type(value) is not VersionedObservation or not session_valid(after,session[0])
                            or (before.pid,before.start_before,before.invocation_id)!=(
                                after.pid,after.start_before,after.invocation_id)
                            or value.snapshot.gamescope.running is not True
                            or value.snapshot.gamescope.confidence is not Confidence.VERIFIED
                            or value.snapshot.gamescope.pid!=after.main_pid):
                        return False
                    box.append(value);return True
                if not runner.attempt(RunnerOperation.SNAPSHOT,collect).accepted:return None
                last_generation[0]=box[0].generation
                # Verification must retain all unrelated immutable identities,
                # even when no further mechanism call occurs before commit.
                if not context_current():return None
                return box[0]

        operations={UserServiceOperation.DAEMON_RELOAD:RunnerOperation.RELOAD,
                    UserServiceOperation.VERIFY_GAMESCOPE_UNIT:RunnerOperation.VERIFY_UNIT,
                    UserServiceOperation.RESTART_GAMESCOPE_SESSION:RunnerOperation.RESTART,
                    UserServiceOperation.OBSERVE_FILTER_GAMESCOPE:RunnerOperation.OBSERVE_INVOCATION}
        class Commands:
            def run(self,operation,*,uid,username,timeout_seconds=None):
                guard()
                if uid!=c.user_uid or operation not in operations:
                    return SimpleNamespace(ok=False)
                box=[]
                def delegate(timeout):
                    started=now()
                    if timeout_seconds is not None:timeout=min(timeout,timeout_seconds)
                    result=composition.commands.run(operation,uid=uid,username=username,timeout_seconds=timeout)
                    if not result.ok:return False
                    if operation is UserServiceOperation.RESTART_GAMESCOPE_SESSION:
                        remaining=timeout-(now()-started)
                        if remaining<=0:return False
                        e=composition.read_session(timeout_seconds=remaining)
                        before=session[0]
                        if (type(e) is not SessionEvidence or e.invocation_id==before.invocation_id
                                or (e.pid,e.start_before)==(before.pid,before.start_before)
                                or not session_valid(e,e)):
                            return False
                        session[0]=e
                        restart_verified[0]=True
                    box.append(result);return True
                outcome=runner.attempt(operations[operation],delegate)
                return box[0] if outcome.accepted else SimpleNamespace(ok=False)

        class Config:
            def write_target(self,**values):
                # Mandatory owned safety/config restoration remains possible
                # after a command budget expires, under the same durable intent
                # and lease. No filesystem deadline/cancellation promise exists.
                guard(fresh=False)
                if values.get("boot_id")!=c.boot_id:
                    raise ValueError("handoff config boot changed")
                return composition.config.write_target(**values)

        base=PresentationTransitionMechanism(integration=self.integration,config=Config(),
            commands=Commands(),resolve_user=self.resolve_user,read_boot_id=lambda:c.boot_id,
            resolve_profiles=lambda s:feature_handoff_profiles(c,s))
        class Mechanism:
            def apply(self,*args):
                guard();return base.apply(*args)
            def recover(self,*args):
                guard();return base.recover(*args)
            def recovery_restart_completed(self,*args,**kwargs):
                guard();return base.recovery_restart_completed(*args,**kwargs)

        observed=Observations()
        first=observed.observe()
        if first is None or first.generation!=c.snapshot_generation:
            raise ValueError("handoff source generation changed")
        resolution=feature_handoff_profiles(c,first.snapshot)
        evidence=evidence_from_snapshot(first.snapshot,observed_generation=first.generation,
                                        capabilities=resolution.capabilities)
        if (evidence.internal_gpu_stable_id!=c.internal_gpu_id
                or evidence.internal_display_stable_id!=c.internal_display_id
                or evidence.external_display_stable_id!=c.external_display_id
                or infer_placement(first.snapshot) is not c.source_placement):
            raise ValueError("handoff source identities changed")
        decision=plan_manual_transition(plan_id=approved.permit.plan_id,request_id=approved.request_id,
            current=c.source_placement,target=c.target_placement,capabilities=resolution.capabilities,
            evidence=evidence,experimental_permit=approved.permit)
        if decision.plan is None:raise ValueError("handoff plan refused")
        policy=StrictRuntimeTransitionPolicy(resolve_profiles=lambda s:feature_handoff_profiles(c,s))
        engine=TransitionOrchestrator(observations=observed,mechanism=Mechanism(),journal_store=journal,
            clock=self.clock,waiter=self.waiter,policy=policy,read_boot_id=lambda:c.boot_id)
        return engine.run(decision.plan)
