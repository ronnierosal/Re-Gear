"""The narrow boundary for trusting one Thunderbolt device.

`boltd` owns Thunderbolt authorization on this system: the enrolment database,
the per-device policy, and the decision to re-authorize on a later plug.  Re-Gear
asks it; Re-Gear does not keep its own idea of which devices are trusted, and
must not write `authorized` in sysfs behind its back.  Two stores that disagree
about whether a device is trusted is a worse failure than not having the
feature.

Only enrolment is exposed, deliberately.  `boltctl authorize` would trust the
device for this session alone and prompt again on the next plug, which is not
what a console does.  Enrolling with the `auto` policy is what Desktop Mode
already did to the dock that works today, so this is parity with existing
behaviour minus the trip out of Game Mode -- asked once per device, ever.

Nothing here decides *whether* to enrol.  That is
`regear.domain.device_authorization`, and the player's confirmation is the
authorization itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DeviceEnrollmentResult:
    #: True only when `boltd` accepted and stored the device. A command that
    #: returned success without the device becoming trusted is not enrolment,
    #: and the caller re-reads state rather than believing this alone.
    enrolled: bool
    code: str


class DeviceAuthorizationPort(Protocol):
    def enroll(self, uuid: str) -> DeviceEnrollmentResult:
        """Trust one named device and store it, with the `auto` policy.

        `uuid` is the only caller-supplied value that reaches a command line
        anywhere in this feature, so the implementation validates its exact
        shape and refuses anything else rather than quoting it.
        """
