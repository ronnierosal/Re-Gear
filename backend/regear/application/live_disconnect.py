"""Execute one live eGPU disconnect, with the handheld and the eGPU still on.

Every part of this existed and nothing ran it. `FilterArmCoordinator` arms the
filter and clears the holders. `decide_disconnect` says whether a removal may
follow. `compose_removal_plan` says what removing consists of, `reconcile` says
what to do about one that was interrupted, and `RemovalTransactionStore` says
how the record survives a crash. A review of the composed result found no
runtime caller of any of them outside their own definitions: it was type
composition, not an executable transaction. This is the transaction.

    recover -> release -> observe afresh -> decide -> revalidate -> record
            -> remove -> verify -> disarm

Four properties are the reason this is a service and not a function, and each
one is a step that can fail rather than an assumption:

**The same device throughout.** A release outcome carries no device identity,
so `decide_disconnect` is told which attachment was released and refuses a
mismatch. Immediately before the first write, `plan_is_current` re-checks that
identity against a fresh reading, because a plan composed for one eGPU must
never execute against another.

**Evidence taken after the release, and again before the write.** Removal
safety assessed before a release always declines -- the holders are still
there -- so the assessment that decides is taken afterwards. That verdict then
describes the moment it was taken and not the moment of the write, so a second
fresh assessment runs immediately before the first detach and anything short
of ready stops the sequence.

**Enforcement held across the whole thing.** The holders let go because the
filter is attached. If it stops being enforced between the assessment and the
write, the clear device the assessment saw can refill before the detach lands,
so enforcement is re-checked immediately before writing and the filter is
disarmed only after the removal has finished either way.

**A durable record before the first write.** The dangerous state is not a
failed removal, it is a half-finished one: audio detached, GPU still bound, and
the process that knew about it gone. The record goes to stable storage before
the first detach and after each function, and the response to finding one is
always restore, never continue.

Nothing here is a claim that any device is safe to unplug. This removes a
device in software while the cable stays attached; whether an unplug may follow
is a separate question, and safety invariant 10 is untouched. On the tested
hardware this service stops at `removal_safety.external_display_still_active`
(#168), which is the correct answer while the kernel console holds the eGPU
CRTC -- it refuses, having disturbed nothing that it did not put back.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Callable

from ..domain.device_removal import RemovalFunction, RemovalPlan, plan_is_current
from ..domain.display_release import DisplayReleaseEvidence, decide_display_release
from ..domain.disconnect_sequence import (
    DisconnectStage,
    ReleaseOutcome,
    decide_disconnect,
)
from ..domain.filter_authorization import ParentScopeAuthorization
from ..domain.removal_safety import RemovalSafety, RemovalSafetyState
from ..domain.removal_transaction import (
    FunctionProgress,
    RecoveryState,
    RemovalTransaction,
    reconcile,
    record_progress,
    record_restored,
)
from ..domain.removal_transaction import plan as plan_transaction
from ..ports.device_filter import DeviceFilterPort
from ..ports.device_removal import DeviceRemovalPort
from ..ports.display_release import DisplayReleasePort
from ..ports.removal_transaction import RemovalTransactionStore
from .filter_arm import ArmSequenceResult, FilterArmCoordinator, release_outcome


@dataclass(frozen=True, slots=True)
class FreshRemovalObservation:
    """One removal-safety verdict and the device identity it was taken over.

    The identity travels with the verdict deliberately. Assessing one device
    and removing another is the failure this exists to make impossible, and a
    bare verdict cannot say which device it describes.
    """

    readiness: RemovalSafety
    attachment_binding: str
    generation: str
    #: Which observation this verdict came from. Recorded for audit and for
    #: binding a filter grant to the reading that justified it; deliberately
    #: not a staleness signal, for the reason `plan_is_current` gives.
    sample_id: str = ""


class LiveDisconnectStage(StrEnum):
    """How far the transaction reached, and what state it left behind."""

    #: A prior interrupted removal was found and its functions were restored.
    #: Nothing new was attempted: the sequence must start from a fresh
    #: observation, because the gap since that record cannot be measured.
    RECOVERED_PRIOR_REMOVAL = "recovered_prior_removal"
    #: A prior interrupted removal was found and could not be restored. The
    #: device is still half attached and the record is deliberately kept.
    RECOVERY_FAILED = "recovery_failed"
    #: A prior removal had already completed. Nothing to disconnect.
    PRIOR_REMOVAL_COMPLETE = "prior_removal_complete"
    #: The stored record could not be read. Refusing is the only safe answer:
    #: an unreadable record may describe a half-detached device.
    RECORD_UNREADABLE = "record_unreadable"

    #: The release refused or failed. Nothing was assessed and, depending on
    #: the stage it reached, the session may not have been disturbed at all.
    RELEASE_REFUSED = "release_refused"
    #: The release ran and the device is still held.
    HOLDERS_REMAIN = "holders_remain"
    #: Released, and still not safe to remove. The readiness code says which
    #: fact blocked it. This is where the tested hardware currently stops.
    NOT_SAFE_AFTER_RELEASE = "not_safe_after_release"

    #: The device in front of the executor is not the one the plan was
    #: composed for.
    IDENTITY_CHANGED = "identity_changed"
    #: Readiness held when the plan was composed and not at the write.
    READINESS_LAPSED = "readiness_lapsed"
    #: The filter stopped being enforced before the first detach.
    ENFORCEMENT_LOST = "enforcement_lost"
    #: The record could not be stored, so no detach was issued.
    RECORD_FAILED = "record_failed"

    #: A function did not detach and the device was restored by rescan.
    REMOVAL_INCOMPLETE = "removal_incomplete"
    #: A function did not detach and the restore failed. The device is
    #: somewhere it has never been.
    REMOVAL_UNRECOVERABLE = "removal_unrecoverable"
    #: Every intended function is confirmed absent from the bus.
    REMOVED = "removed"

    INVALID = "invalid"


#: Stages that leave the device half attached. A caller showing any of these to
#: a player is reporting a system that needs attention, not a failed action.
DEVICE_DISTURBED_STAGES: frozenset[LiveDisconnectStage] = frozenset(
    {LiveDisconnectStage.RECOVERY_FAILED, LiveDisconnectStage.REMOVAL_UNRECOVERABLE}
)

_REFUSAL_STAGES: dict[DisconnectStage, LiveDisconnectStage] = {
    DisconnectStage.RELEASE_REFUSED: LiveDisconnectStage.RELEASE_REFUSED,
    DisconnectStage.HOLDERS_REMAIN: LiveDisconnectStage.HOLDERS_REMAIN,
    DisconnectStage.NOT_SAFE_AFTER_RELEASE: LiveDisconnectStage.NOT_SAFE_AFTER_RELEASE,
}


@dataclass(frozen=True, slots=True)
class LiveDisconnectResult:
    """What the transaction did, in enough detail to act on and to report."""

    stage: LiveDisconnectStage
    code: str
    released: bool = False
    session_disturbed: bool = False
    removed: tuple[str, ...] = ()
    restored: tuple[str, ...] = ()
    filter_disarmed: bool = False
    #: CRTCs turned off for the duration of the assessment and removal, and
    #: given back before this returned.
    display_released: tuple[int, ...] = ()
    #: Why the display release happened, was not needed, or was refused. A
    #: refusal here is not fatal: a committed mode that is still standing is
    #: reported by the readiness code, not by this.
    display_release_code: str = ""
    # Preserve the arm refusal before the outer decision summarizes it.
    arm_stage: str = ""
    arm_code: str = ""

    def __post_init__(self) -> None:
        if self.stage is LiveDisconnectStage.REMOVED and not self.removed:
            raise ValueError("a completed removal names the functions it detached")
        if self.stage is not LiveDisconnectStage.REMOVED and self.removed:
            # Functions detached by an incomplete removal are reported through
            # `restored`; claiming them as removed would read as success.
            raise ValueError("only a completed removal reports removed functions")

    @property
    def ok(self) -> bool:
        """Whether both functions are confirmed detached.

        One stage says yes. Every other outcome leaves the device attached, or
        needing attention, including the ones where the release worked.
        """
        return self.stage is LiveDisconnectStage.REMOVED

    @property
    def device_disturbed(self) -> bool:
        """Whether the device was left in a state it has never been in."""
        return self.stage in DEVICE_DISTURBED_STAGES


class LiveDisconnectService:
    """Run one live disconnect attempt from recovery through to disarm."""

    def __init__(
        self,
        *,
        coordinator: FilterArmCoordinator,
        device_filter: DeviceFilterPort,
        removal: DeviceRemovalPort,
        display_release: DisplayReleasePort,
        store: RemovalTransactionStore,
        observe: Callable[[], FreshRemovalObservation],
        observe_display: Callable[[], DisplayReleaseEvidence],
        display_node: str,
        present_addresses: Callable[[], tuple[str, ...]],
        removal_functions: Callable[[], tuple[RemovalFunction, ...]],
        now_ns: Callable[[], int],
        owner_id: str,
        device_set: str,
    ) -> None:
        self._coordinator = coordinator
        self._filter = device_filter
        self._removal = removal
        self._display_release = display_release
        self._store = store
        self._observe = observe
        self._observe_display = observe_display
        self._display_node = display_node
        self._present = present_addresses
        self._removal_functions = removal_functions
        self._now_ns = now_ns
        self._owner_id = owner_id
        self._device_set = device_set

    def disconnect(
        self,
        authorization: ParentScopeAuthorization,
        program: bytes,
        *,
        boot_hash: str,
        release_display: bool,
    ) -> LiveDisconnectResult:
        """Attempt the whole sequence, leaving nothing armed behind it.

        `release_display` is a separate authority from the disconnect itself:
        turning an output off is visible to whoever is in front of it, so the
        caller says whether that is approved rather than it following from
        having approved a removal.
        """
        try:
            recovery = self._recover()
        except Exception:
            # An unreadable record may describe a half-detached device, so this
            # refuses rather than starting a removal over an unknown state.
            return LiveDisconnectResult(
                LiveDisconnectStage.RECORD_UNREADABLE,
                "live_disconnect.record_unreadable",
            )
        if recovery is not None:
            return recovery

        arm = self._coordinator.arm(authorization, program, boot_hash=boot_hash)
        if not arm.ok:
            # Every unsuccessful stage disarms inside the coordinator, so there
            # is nothing left attached for this to take down.
            return self._refused(arm)

        # From here the filter is live and must stay live until the removal has
        # finished either way, so every exit runs through the disarm below. The
        # display is given back first, so the system is put back in the order
        # it was taken apart.
        try:
            result = self._with_display_released(arm, authorization, release_display)
        except BaseException:
            self._filter.disarm()
            raise
        return replace(result, filter_disarmed=self._filter.disarm().ok)

    # -- the display ------------------------------------------------------

    def _with_display_released(
        self,
        arm: ArmSequenceResult,
        authorization: ParentScopeAuthorization,
        approved: bool,
    ) -> LiveDisconnectResult:
        """Take the external display down for the assessment and the removal.

        The holders let go, and on the tested hardware the eGPU still had a
        mode committed afterwards, because the kernel's fbdev client restores
        the console's mode when the compositor gives the output back. No
        holder release can clear that; a DRM master turning the CRTC off can,
        and the console's mode returns when the descriptor closes.

        A refusal here is deliberately **not** fatal. If a committed mode is
        still standing, the assessment below declines with the readiness code
        that names it, which is the same answer the sequence gave before this
        step existed. This enables a removal; it does not gate one.
        """
        decision = decide_display_release(self._observe_display(), approved=approved)
        if not decision.permitted:
            return replace(
                self._after_release(arm, authorization),
                display_release_code=decision.code,
            )

        outcome, held = self._display_release.release(
            self._display_node, decision.crtcs
        )
        if held is None:
            return replace(
                self._after_release(arm, authorization),
                display_release_code=outcome.code,
            )
        try:
            # Held across both the assessment and the removal. An assessment
            # taken while the display is down, acted on after it came back,
            # would describe a moment that no longer exists.
            result = self._after_release(arm, authorization)
        finally:
            # The removal detaches the device underneath this descriptor.
            # `drm_dev_unplug` is built for exactly that: the node stops
            # answering and closing it is still correct.
            held.restore()
        return replace(
            result,
            display_released=outcome.released,
            display_release_code=outcome.code,
        )

    # -- recovery ---------------------------------------------------------

    def _recover(self) -> LiveDisconnectResult | None:
        """Settle any prior transaction, returning None when the way is clear.

        The device is the authority on what happened; the record only says what
        was meant to happen. A partial removal is always restored and never
        finished, because continuing would act on readiness gathered before a
        gap of unknown length -- during which a game may have launched or a
        display may have come back.
        """
        record = self._store.load()
        if record is None:
            return None

        recovery = reconcile(record, present_addresses=self._present())
        if recovery.device_disturbed:
            return self._restore(
                record,
                recovery.restore,
                LiveDisconnectStage.RECOVERED_PRIOR_REMOVAL,
                recovery.code,
            )
        if recovery.state is RecoveryState.COMPLETE:
            self._store.clear()
            return LiveDisconnectResult(
                LiveDisconnectStage.PRIOR_REMOVAL_COMPLETE, recovery.code
            )
        if recovery.state in (RecoveryState.NOT_STARTED, RecoveryState.RESTORED):
            # Both functions are present, so the device is whole and the record
            # describes an intention that never landed or was already undone.
            # A fresh observation follows regardless, so nothing is inherited
            # from it beyond the fact that it is finished with.
            self._store.clear()
            return None
        return LiveDisconnectResult(LiveDisconnectStage.INVALID, recovery.code)

    # -- release and decision ---------------------------------------------

    def _refused(self, arm: ArmSequenceResult) -> LiveDisconnectResult:
        decision = decide_disconnect(
            release_outcome(arm), None, self._removal_functions()
        )
        return LiveDisconnectResult(
            _REFUSAL_STAGES.get(decision.stage, LiveDisconnectStage.INVALID),
            decision.code,
            released=decision.released,
            session_disturbed=arm.session_disturbed,
            filter_disarmed=arm.disarmed,
            arm_stage=arm.stage.value,
            arm_code=arm.code,
        )

    def _after_release(
        self, arm: ArmSequenceResult, authorization: ParentScopeAuthorization
    ) -> LiveDisconnectResult:
        observation = self._observe()
        decision = decide_disconnect(
            ReleaseOutcome.CLEAR,
            observation.readiness,
            self._removal_functions(),
            released_attachment=observation.attachment_binding,
        )
        if not decision.may_remove or decision.plan is None:
            return LiveDisconnectResult(
                _REFUSAL_STAGES.get(decision.stage, LiveDisconnectStage.INVALID),
                decision.code,
                released=decision.released,
                session_disturbed=arm.session_disturbed,
            )
        return self._execute(decision.plan, arm, authorization)

    # -- revalidation and execution ---------------------------------------

    def _execute(
        self,
        plan: RemovalPlan,
        arm: ArmSequenceResult,
        authorization: ParentScopeAuthorization,
    ) -> LiveDisconnectResult:
        """Revalidate against a second fresh reading, then write.

        The observation that composed the plan described the moment it was
        taken. Three separate things have to still hold at the moment of the
        write, and each is checked here rather than assumed: the device is the
        same one, it is still assessed ready, and the filter that emptied it is
        still enforced.
        """
        disturbed = arm.session_disturbed
        fresh = self._observe()
        if not plan_is_current(
            plan,
            attachment_binding=fresh.attachment_binding,
            generation=fresh.generation,
        ):
            return LiveDisconnectResult(
                LiveDisconnectStage.IDENTITY_CHANGED,
                "live_disconnect.identity_changed",
                released=True,
                session_disturbed=disturbed,
            )
        if fresh.readiness.state is not RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL:
            # The readiness code is passed through rather than translated, so
            # the caller learns which fact lapsed.
            return LiveDisconnectResult(
                LiveDisconnectStage.READINESS_LAPSED,
                fresh.readiness.code,
                released=True,
                session_disturbed=disturbed,
            )
        if arm.filter is None or not self._filter.enforced(
            authorization.cgroup, arm.filter.program_id
        ):
            # Without enforcement the device the assessment saw as clear can
            # refill before the detach lands.
            return LiveDisconnectResult(
                LiveDisconnectStage.ENFORCEMENT_LOST,
                "live_disconnect.enforcement_lost",
                released=True,
                session_disturbed=disturbed,
            )

        record = plan_transaction(
            owner_id=self._owner_id,
            device_set=self._device_set,
            addresses=plan.addresses,
            now_ns=self._now_ns(),
        )
        try:
            self._store.save(record)
        except Exception:
            # Nothing has been written to the bus, so there is nothing to undo.
            return LiveDisconnectResult(
                LiveDisconnectStage.RECORD_FAILED,
                "live_disconnect.record_failed",
                released=True,
                session_disturbed=disturbed,
            )
        return self._detach(plan, record, disturbed)

    def _detach(
        self, plan: RemovalPlan, record: RemovalTransaction, disturbed: bool
    ) -> LiveDisconnectResult:
        """Detach each function in plan order, recording every outcome."""
        for function in plan.functions:
            outcome = self._removal.remove(function.address)
            record = record_progress(
                record,
                function.address,
                FunctionProgress.REMOVED if outcome.ok else FunctionProgress.FAILED,
            )
            try:
                self._store.save(record)
            except Exception:
                # The detach already happened and the record is now behind. The
                # intended function set was stored before the first write, and
                # `reconcile` reads the bus rather than this progress field, so
                # recovery still works; the sequence cannot continue though,
                # because it can no longer record what it does next.
                return self._restore(
                    record,
                    plan.addresses,
                    LiveDisconnectStage.REMOVAL_INCOMPLETE,
                    "live_disconnect.progress_not_recorded",
                    session_disturbed=disturbed,
                )
            if not outcome.ok:
                return self._restore(
                    record,
                    plan.addresses,
                    LiveDisconnectStage.REMOVAL_INCOMPLETE,
                    outcome.code or outcome.outcome.value,
                    session_disturbed=disturbed,
                )

        # The record now claims every function is gone. The bus is asked
        # separately, because a claim recorded by this process is not evidence.
        present = {address.lower() for address in self._present()}
        if any(address.lower() in present for address in plan.addresses):
            return self._restore(
                record,
                plan.addresses,
                LiveDisconnectStage.REMOVAL_INCOMPLETE,
                "live_disconnect.function_still_present",
                session_disturbed=disturbed,
            )
        self._store.clear()
        return LiveDisconnectResult(
            LiveDisconnectStage.REMOVED,
            "live_disconnect.removed",
            released=True,
            session_disturbed=disturbed,
            removed=plan.addresses,
        )

    def _restore(
        self,
        record: RemovalTransaction,
        addresses: tuple[str, ...],
        stage: LiveDisconnectStage,
        code: str,
        *,
        session_disturbed: bool = False,
    ) -> LiveDisconnectResult:
        """Rescan the bus for everything the transaction intended.

        Everything intended, not only what the record believes it detached: the
        belief was written before an interruption of unknown length, and the
        bus is the authority. The record is cleared only once the rescan says
        the device is whole again -- a failed restore keeps it, because it is
        then the only evidence of where the device actually is.
        """
        recovering_prior = stage is LiveDisconnectStage.RECOVERED_PRIOR_REMOVAL
        rescan = self._removal.rescan(addresses)
        if not rescan.ok:
            # Both failures leave the device half attached; they are named
            # apart because one is this transaction's own removal and the
            # other is a record inherited from a process that is gone.
            return LiveDisconnectResult(
                LiveDisconnectStage.RECOVERY_FAILED
                if recovering_prior
                else LiveDisconnectStage.REMOVAL_UNRECOVERABLE,
                rescan.code or rescan.outcome.value,
                released=not recovering_prior,
                session_disturbed=session_disturbed,
            )
        try:
            # Marked restored before being cleared, so a crash in between still
            # reads as a finished recovery rather than as an open removal.
            self._store.save(record_restored(record))
            self._store.clear()
        except Exception:
            # The device is whole; only the bookkeeping failed. A leftover
            # record reconciles as not-started next time, which is accurate.
            pass
        return LiveDisconnectResult(
            stage,
            code,
            released=not recovering_prior,
            session_disturbed=session_disturbed,
            restored=rescan.restored,
        )
