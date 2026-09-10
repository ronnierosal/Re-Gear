"""Sequence the supervised arming of an eGPU device filter.

`docs/FILTER_PRIMITIVES_INTEGRATION.md` sets out what a service at this level
owes: fresh exact attachment and complete device evidence, an authorized target
cgroup, verified enforcement *before* any approved restart, re-checked holders
after the restarts, and recovery preserved on cancellation, timeout or owner
failure. This coordinator is that sequence, and it is written so each of those
is a step that can fail rather than an assumption.

The order matters and is not arbitrary:

1. Authorize the cgroup. A grant is refused for anything but the exact user
   manager of the observed session user (`hdm.domain.filter_authorization`).
2. Arm, then **verify enforcement**. `attach` returning without error means the
   kernel accepted a link, not that the program now decides opens on that
   cgroup. Restarting the player's session on the strength of an unverified
   attachment would disrupt them for nothing.
3. Restart only the approved units the plan names
   (`hdm.domain.filter_arm_sequence`).
4. Re-observe holders. A composed plan is not evidence that the device was
   cleared; only a fresh scan is.

Every failure after arming disarms before returning. An unpinned link vanishing
with its owner is not durable recovery, so recovery here is explicit: the
caller is told what state it was left in, and the filter is taken down rather
than left attached behind a failed transaction.

This never removes a device. Reaching `armed_and_clear` means the holders let
go; removal is a separate transaction with its own approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from ..domain.disconnect_sequence import ReleaseOutcome
from ..domain.filter_arm_sequence import (
    ArmSequenceState,
    compose_restart_plan,
)
from ..domain.filter_authorization import (
    ParentScopeAuthorization,
    authorization_is_current,
)
from ..ports.device_filter import ArmedFilter, DeviceFilterPort


@dataclass(frozen=True, slots=True)
class HolderObservation:
    """Holders seen, and whether the scan managed to look everywhere.

    A bare tuple cannot say the difference between nothing holding the
    device and a scan that could not finish, so an empty one read as a
    clear device. That is the fail-open removed from the operator scan in
    #137, and it returned here because this layer took only names.
    """

    units: tuple[str, ...]
    complete: bool

    @property
    def clear(self) -> bool:
        return self.complete and not self.units


class ArmStage(StrEnum):
    """How far the sequence reached, so a caller knows what was disturbed."""

    NOT_AUTHORIZED = "not_authorized"
    AUTHORIZATION_STALE = "authorization_stale"
    ARM_FAILED = "arm_failed"
    ENFORCEMENT_UNVERIFIED = "enforcement_unverified"
    PLAN_BLOCKED = "plan_blocked"
    RESTART_FAILED = "restart_failed"
    HOLDERS_REMAIN = "holders_remain"
    #: The device may be clear; the scan could not establish it.
    SCAN_INCOMPLETE = "scan_incomplete"
    ARMED_AND_CLEAR = "armed_and_clear"


#: Stages reached before anything was attached or restarted. A caller seeing
#: one of these knows the session was not disturbed.
UNDISTURBED_STAGES: frozenset[ArmStage] = frozenset(
    {
        ArmStage.NOT_AUTHORIZED,
        ArmStage.AUTHORIZATION_STALE,
        ArmStage.ARM_FAILED,
    }
)


@dataclass(frozen=True, slots=True)
class ArmSequenceResult:
    stage: ArmStage
    code: str
    filter: ArmedFilter | None = None
    restarted: tuple[str, ...] = ()
    remaining_holders: tuple[str, ...] = ()
    disarmed: bool = False

    def __post_init__(self) -> None:
        if self.stage is ArmStage.ARMED_AND_CLEAR:
            if self.filter is None:
                raise ValueError("a successful arm exposes its filter identity")
            if self.disarmed:
                raise ValueError("a successful arm is not disarmed")

    @property
    def ok(self) -> bool:
        return self.stage is ArmStage.ARMED_AND_CLEAR

    @property
    def session_disturbed(self) -> bool:
        """Whether the player's session was restarted before this returned."""
        return bool(self.restarted)


class FilterArmCoordinator:
    """Drive one supervised arm attempt, disarming on any failure after arming."""

    def __init__(
        self,
        *,
        device_filter: DeviceFilterPort,
        restart: Callable[[str], bool],
        observe_holders: Callable[[], HolderObservation],
        observe_cgroup,
        monotonic: Callable[[], float],
    ) -> None:
        self._filter = device_filter
        self._restart = restart
        self._observe_holders = observe_holders
        self._observe_cgroup = observe_cgroup
        self._monotonic = monotonic

    def arm(
        self,
        authorization: ParentScopeAuthorization,
        program: bytes,
        *,
        boot_hash: str,
    ) -> ArmSequenceResult:
        if not authorization.granted or authorization.cgroup is None:
            return ArmSequenceResult(ArmStage.NOT_AUTHORIZED, authorization.code)

        # Revalidate immediately before acting. A grant describes the scope it
        # was taken over, which may no longer be the scope in front of us.
        observed = self._observe_cgroup()
        if observed is None or not authorization_is_current(
            authorization,
            boot_hash=boot_hash,
            cgroup=observed,
            now=self._monotonic(),
        ):
            return ArmSequenceResult(
                ArmStage.AUTHORIZATION_STALE, "filter_arm.authorization_stale"
            )

        armed = self._filter.arm(program, authorization.cgroup)
        if not armed.ok or armed.filter is None:
            return ArmSequenceResult(
                ArmStage.ARM_FAILED, armed.code or armed.outcome.value
            )

        # Enforcement before disruption: a link the kernel accepted is not yet
        # proof that this program decides opens on that cgroup.
        if not self._filter.enforced(
            authorization.cgroup, armed.filter.program_id
        ):
            return self._recover(
                ArmStage.ENFORCEMENT_UNVERIFIED, "filter_arm.enforcement_unverified"
            )

        # Completeness travels with the units. Passing only the names is how
        # a scan that could not finish became indistinguishable from a device
        # nothing holds, and the two need opposite answers.
        before = self._observe_holders()
        plan = compose_restart_plan(before.units, scan_complete=before.complete)
        if not plan.usable:
            return self._recover(ArmStage.PLAN_BLOCKED, plan.code)

        restarted: list[str] = []
        try:
            for unit in plan.units:
                # Authorization is rechecked before every disruption, not
                # once before the first. A grant that expired partway
                # through the restarts previously allowed the remaining
                # ones and still reported a clear device.
                if not self._still_authorized(authorization, boot_hash):
                    return self._recover(
                        ArmStage.AUTHORIZATION_STALE,
                        "filter_arm.authorization_expired_mid_restart",
                        tuple(restarted),
                    )
                if not self._filter.enforced(
                    authorization.cgroup, armed.filter.program_id
                ):
                    return self._recover(
                        ArmStage.ENFORCEMENT_UNVERIFIED,
                        "filter_arm.enforcement_lost_mid_restart",
                        tuple(restarted),
                    )
                if not self._restart(unit):
                    return self._recover(
                        ArmStage.RESTART_FAILED,
                        f"filter_arm.restart_failed:{unit}",
                        tuple(restarted),
                    )
                restarted.append(unit)

            # A composed plan is not evidence the device was cleared, and an
            # empty result is not evidence either unless the scan finished.
            observed = self._observe_holders()
        except Exception:
            # Anything raised after the filter is attached must still take
            # it down. Previously an OSError from a restart escaped and
            # left the filter armed with no disarm attempted at all.
            return self._recover(
                ArmStage.RESTART_FAILED,
                "filter_arm.disruption_raised",
                tuple(restarted),
            )
        if observed.units:
            return self._recover(
                ArmStage.HOLDERS_REMAIN,
                "filter_arm.holders_remain",
                tuple(restarted),
                observed.units,
            )
        if not observed.complete:
            return self._recover(
                ArmStage.SCAN_INCOMPLETE,
                "filter_arm.scan_incomplete",
                tuple(restarted),
            )
        return ArmSequenceResult(
            ArmStage.ARMED_AND_CLEAR,
            "filter_arm.armed_and_clear",
            armed.filter,
            tuple(restarted),
        )

    def _still_authorized(
        self, authorization: ParentScopeAuthorization, boot_hash: str
    ) -> bool:
        """Whether the grant still describes the scope in front of us."""
        observed = self._observe_cgroup()
        return observed is not None and authorization_is_current(
            authorization,
            boot_hash=boot_hash,
            cgroup=observed,
            now=self._monotonic(),
        )

    def _recover(
        self,
        stage: ArmStage,
        code: str,
        restarted: tuple[str, ...] = (),
        remaining: tuple[str, ...] = (),
    ) -> ArmSequenceResult:
        """Take the filter down and report what the attempt disturbed."""
        disarmed = self._filter.disarm().ok
        return ArmSequenceResult(stage, code, None, restarted, remaining, disarmed)


def release_outcome(result: ArmSequenceResult) -> ReleaseOutcome:
    """Project an arm attempt onto what the disconnect sequence needs to know.

    `hdm.domain.disconnect_sequence` decides whether a removal may proceed, and
    the only thing it needs from the release is how far it got. Eight stages
    collapse to three outcomes, because the difference between failing to
    authorise and failing to restart matters to whoever fixes the release and
    not at all to whether a device may now be detached.

    The collapse is deliberately lossy in one direction only. Every stage short
    of a clear device maps to something that refuses removal, so a stage added
    later cannot accidentally read as permission: the mapping names the two
    permissive cases and treats everything else as refused.
    """
    if result.stage is ArmStage.ARMED_AND_CLEAR:
        return ReleaseOutcome.CLEAR
    if result.stage is ArmStage.HOLDERS_REMAIN:
        return ReleaseOutcome.HOLDERS_REMAIN
    return ReleaseOutcome.REFUSED
