"""The narrow boundary for trusting one Thunderbolt device.

`boltd` owns Thunderbolt authorization on this system: the enrolment database,
the per-device policy, and the decision to re-authorize on a later plug.  Re-Gear
asks it; Re-Gear does not keep its own idea of which devices are trusted, and
must not write `authorized` in sysfs behind its back.  Two stores that disagree
about whether a device is trusted is a worse failure than not having the
feature.

**Two grants, because they are two different promises.**  `enroll` stores the
device, which is what Desktop Mode already did to the dock that works today:
asked once, remembered, re-authorized on every later plug.  That is the console
behaviour and it stays the default.  `authorize` trusts the device for this
attachment only and leaves `boltd`'s database untouched, so the next plug asks
again.  Offering only enrolment made "trust it this once" unreachable, and the
player who wants a borrowed dock to work for an evening without being recorded
as trusted forever had no way to say so.  The two are kept as separate methods
rather than a flag because the prompt copy differs -- remembering is the part
that has to be said out loud -- and a boolean argument is exactly the kind of
thing a caller gets backwards.

**Accepted is not trusted.**  `DeviceEnrollmentResult.enrolled` reports that
the executor took the request, never that the device ended up trusted.  The
caller re-reads the device's state afterwards; nothing in this package is
evidence of an outcome.

Nothing here decides *whether* to grant anything.  That is
`regear.domain.device_authorization`, and the player's confirmation is the
authorization itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DeviceEnrollmentResult:
    #: True only when the executor accepted the request -- `boltd` took it and
    #: returned success. That is a statement about the command, not about the
    #: device: on an `authorize()` result especially, `enrolled` means "the
    #: request was accepted", never "the device is now trusted" and never "the
    #: device was stored". A command can return success without the device
    #: becoming usable, so the caller re-reads state rather than believing
    #: this alone.
    enrolled: bool
    code: str


class DeviceAuthorizationPort(Protocol):
    def enroll(self, uuid: str) -> DeviceEnrollmentResult:
        """Trust one named device and store it, with the `auto` policy.

        `uuid` is the only caller-supplied value that reaches a command line
        anywhere in this feature, so the implementation validates its exact
        shape and refuses anything else rather than quoting it.
        """

    def authorize(self, uuid: str) -> DeviceEnrollmentResult:
        """Trust one named device for this attachment only, storing nothing.

        The one-shot grant behind "just this once": `boltd`'s enrolment
        database is left alone, so unplugging and plugging the device back in
        asks again.  That repetition is the point of the choice, not a defect
        in it.

        `enrolled` on the returned result keeps its narrow meaning -- the
        executor accepted the request -- and here it is emphatically not a
        claim that anything was enrolled or that the device is now trusted.
        The name is shared with `enroll` because the honesty is shared; the
        caller verifies by re-reading the device either way.

        `uuid` is validated exactly as in `enroll`: the implementation refuses
        anything that is not a device id rather than quoting it onto a command
        line.

        The existing `BoltDeviceAuthorizationRunner` in
        `regear.adapters.steamos.commands` implements `enroll` only; widening
        this Protocol does not change it, and the root of the feature supplies
        `authorize`.  A caller that dispatches on the player's chosen action
        must therefore be prepared for an executor that does not have this
        method yet, and must report that as a refusal rather than as a grant.
        """
