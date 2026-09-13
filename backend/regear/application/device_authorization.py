"""Offer to trust a new dock once, and enrol it when the player says yes.

Holds the two things the pure decision deliberately does not: the latch that
keeps one attachment to one prompt, and the call to `boltd`.

**The prompt is the authorization.**  Nothing here enrols on its own, and the
confirmation is checked by identity rather than truthiness -- `"yes"`, `1` and
a stray dict are all truthy and none of them are a player pressing a button.
That mirrors the guard on `execute_automatic`, for the same reason: this grants
a device direct access to system memory, and on this profile
`iommu_dma_protection` reads `0`, so nothing stands behind it.

**Re-checked at the moment of acting, never on the panel's word.**  A dialog
can sit on screen while the dock is unplugged, replaced, or trusted by
something else.  So the caller's fresh reading is assessed again immediately
before enrolling, and a state that has moved refuses rather than enrolling
whatever happens to be attached now.

**A zero exit is not proof.**  `boltctl` accepting the request says it was
taken, not that the device became trusted, so the outcome carries what the
executor reported and the caller re-reads state to learn what actually
happened.

The latch belongs to the attachment, so declining does not blacklist: unplug
and plug back in and the offer returns.  A player who said "not now" and
changed their mind should not have to find a settings screen.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.device_authorization import (
    DeviceAuthorizationAssessment,
    assess_device_authorization,
)
from ..ports.device_authorization import (
    DeviceAuthorizationPort,
    DeviceEnrollmentResult,
)


@dataclass(frozen=True, slots=True)
class DeviceAuthorizationOutcome:
    #: True only when the executor accepted the request. Never a claim that the
    #: device is now trusted -- the caller re-reads for that.
    requested: bool
    code: str
    #: The device the request named, so a result is never ambiguous about which
    #: dock it belongs to.
    uuid: str = ""


class DeviceAuthorizationService:
    """One offer per attachment, and one enrolment behind an explicit yes."""

    def __init__(self, commands: DeviceAuthorizationPort) -> None:
        self._commands = commands
        self._offered = False

    # -- the latch -----------------------------------------------------------

    def observe_device(self, present: bool) -> None:
        """Re-arm when the dock goes away, so a replug asks again."""
        if not present:
            self._offered = False

    @property
    def offered(self) -> bool:
        return self._offered

    def assess(
        self,
        *,
        device_present: bool,
        identity_resolved: bool,
        authorized: bool | None,
        already_enrolled: bool,
    ) -> DeviceAuthorizationAssessment:
        return assess_device_authorization(
            device_present=device_present,
            identity_resolved=identity_resolved,
            authorized=authorized,
            already_enrolled=already_enrolled,
            already_offered=self._offered,
        )

    def note_offered(self) -> None:
        """Spend this attachment's one prompt.

        Separate from `enroll` on purpose: the prompt is spent by being *shown*,
        so declining does not leave it able to reappear on the next poll.
        """
        self._offered = True

    # -- the act -------------------------------------------------------------

    def enroll(
        self,
        uuid: str,
        *,
        confirmed: bool,
        device_present: bool,
        identity_resolved: bool,
        authorized: bool | None,
        already_enrolled: bool,
    ) -> DeviceAuthorizationOutcome:
        """Trust one named device, after re-checking that it still needs it.

        `confirmed` must be exactly `True`. The remaining arguments are the
        caller's *fresh* reading, not the one the prompt was drawn from.
        """
        if confirmed is not True:
            return DeviceAuthorizationOutcome(
                False, "device_authorization.confirmation_required", uuid
            )
        if type(uuid) is not str or not uuid:
            return DeviceAuthorizationOutcome(
                False, "device_authorization.uuid_invalid", ""
            )
        # Re-assessed with the latch ignored: the offer being spent is what got
        # us here, and must not be the reason the act is refused.
        fresh = assess_device_authorization(
            device_present=device_present,
            identity_resolved=identity_resolved,
            authorized=authorized,
            already_enrolled=already_enrolled,
            already_offered=False,
        )
        if not fresh.offered:
            return DeviceAuthorizationOutcome(False, fresh.code, uuid)
        self._offered = True
        result: DeviceEnrollmentResult = self._run(uuid)
        return DeviceAuthorizationOutcome(result.enrolled, result.code, uuid)

    def _run(self, uuid: str) -> DeviceEnrollmentResult:
        try:
            return self._commands.enroll(uuid)
        except Exception:
            return DeviceEnrollmentResult(
                False, "device_authorization.enroll_unavailable"
            )
