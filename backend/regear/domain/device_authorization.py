"""Whether to ask the player to trust a newly attached Thunderbolt device.

SteamOS requires a Thunderbolt device to be authorized before its tunnel
carries anything, and on this profile that authorization has only ever been
reachable from Desktop Mode: `boltd` is the system's authorization owner, and
the agent that drives it ships with Plasma.  So a player who plugs in a new
dock in Game Mode gets nothing, with no indication that a decision is waiting
for them somewhere else entirely.

This decides whether a Game Mode prompt is honest right now.  It does not
authorize anything, does not talk to `boltd`, and deliberately does not
authorize on the player's behalf -- the prompt *is* the authorization.

**Enrolling, not authorizing once.**  The action behind this prompt stores the
device (`boltctl enroll`), which is what Desktop Mode already did to the dock
that works today.  Authorizing for one session instead would mean prompting on
every single plug, which is not a console.  Because enrolment is remembered,
the prompt has to say so; that honesty lives in the copy rather than in an
extra button.

**What is actually being granted.**  Thunderbolt authorization gates the
device's direct access to system memory, and on this profile
`iommu_dma_protection` reads `0`, so there is no IOMMU standing behind it.
That is not a reason to withhold the feature -- Desktop Mode offers exactly
this decision on the same hardware -- but it is the reason the prompt must
name the device rather than say "a device", and the reason nothing here ever
answers for the player.

**Three unknowns, not two falsehoods.**  Three inputs are tri-state, and each
``None`` is the same admission: the fact was never read.  A failed scan is not
an empty port, an unreadable `authorized` file is not a denial, and an
unreadable enrolment database is not an unenrolled device.  Each declines
under a code that names its own unreadability, because the alternative is a
prompt -- or a silence -- manufactured out of a permissions error, and because
a caller reading the code afterwards needs to know which read failed.

The rules, each of which declines on its own:

- **an unreadable scan is not an absent device.**  ``device_present is None``
  means the walk over sysfs failed, so nothing is known about what is
  attached.  It outranks absence because "nothing is plugged in" is a claim,
  and a failed scan is not in a position to make it;
- **no device, no question.**  Nothing is attached that could be trusted;
- **a deliberate disconnect is not a first plug.**  When Re-Gear itself
  deauthorized a dock that is still cabled, the device reads exactly like a
  brand-new attachment: present, named, unauthorized, unenrolled.  Offering
  there would ask the player to re-trust what we just disowned on their
  behalf, and would ask again at every wake, because a still-cabled dock
  reappears at every resume.  So it is answered immediately after presence,
  ahead of every fact about the device, since none of those facts change what
  the answer has to be.  It is also the one input the hardware cannot supply:
  sysfs can say a device is unauthorized, never why, so the caller carries the
  reason in;
- **an unnamed device is never offered.**  If the identity is unreadable or two
  routers answer to the same name, the player is being asked to trust
  something nobody can point at.  "Do not authorize devices you do not trust"
  is unusable advice when the dialog cannot say which device it means, so an
  ambiguous scan refuses rather than guessing;
- **unreadable authorization state is not "unauthorized".**  `None` means the
  file could not be read, which says nothing at all; treating it as a denial
  would invent a prompt out of a permissions error;
- **an authorized device needs nothing.**  Offering would invent a problem;
- **unreadable enrolment is not "not enrolled".**  If `boltd`'s database could
  not be read, a stored device is indistinguishable from an unknown one, and
  the cheap-looking fallthrough -- call unknown unenrolled -- is the expensive
  one: it offers to enrol a device that may already be enrolled, so the player
  confirms a grant that changes nothing and is told nothing.  It refuses under
  its own code instead of guessing the harmless-sounding answer;
- **an enrolled device is `boltd`'s business.**  Stored-but-unauthorized is a
  real state, and it is not one a second enrolment fixes.  It declines with
  its own code so it stays visible instead of silently doing nothing;
- **once per attachment.**  Declining must not nag, and must not blacklist
  either: the latch belongs to this attachment, so unplugging and plugging
  back in asks again.  A player who said "not now" and changed their mind
  should not have to find a settings screen.

The order is itself a rule.  Each refusal outranks the ones below it because
it is the more informative thing to say about the same device, which leaves
the latch last: it describes us, not the hardware.

Pure.  It holds no state, reads no sysfs, and enrols nothing.  The caller owns
the latch, the caller owns the disconnect flag, and the executor owns `boltd`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DeviceAuthorizationAvailability(StrEnum):
    #: Worth asking the player about, and safe to ask.
    OFFERED = "offered"
    #: It is not. `code` says why, and is the only thing worth showing.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DeviceAuthorizationAssessment:
    availability: DeviceAuthorizationAvailability
    code: str

    @property
    def offered(self) -> bool:
        return self.availability is DeviceAuthorizationAvailability.OFFERED


def _no(code: str) -> DeviceAuthorizationAssessment:
    return DeviceAuthorizationAssessment(
        DeviceAuthorizationAvailability.UNAVAILABLE, code
    )


def assess_device_authorization(
    *,
    device_present: bool | None,
    identity_resolved: bool,
    authorized: bool | None,
    already_enrolled: bool | None,
    already_offered: bool,
    intentional_disconnect: bool,
) -> DeviceAuthorizationAssessment:
    """Decide whether to raise the Game Mode authorization prompt.

    `device_present`, `authorized` and `already_enrolled` are deliberately
    tri-state and mirror the adapter's reading: ``None`` means the fact could
    not be read, which is a different fact from ``False`` and must never be
    collapsed into it.  Each gets its own refusal code, so an unreadable scan,
    an unreadable `authorized` file and an unreadable enrolment database stay
    told apart by whoever reads the outcome.

    `intentional_disconnect` is the caller stating that Re-Gear deauthorized
    this still-cabled dock on purpose.  The hardware cannot report that, so it
    is carried in, and it is answered before any hardware fact -- identity
    included -- because no reading of the device can change it.

    `already_offered` is the caller's latch for this attachment.
    """
    if device_present is None:
        return _no("device_authorization.scan_unreadable")
    if not device_present:
        return _no("device_authorization.no_device")
    if intentional_disconnect:
        return _no("device_authorization.intentional_disconnect")
    if not identity_resolved:
        return _no("device_authorization.identity_unresolved")
    if authorized is None:
        return _no("device_authorization.state_unreadable")
    if authorized:
        return _no("device_authorization.already_authorized")
    if already_enrolled is None:
        return _no("device_authorization.enrollment_unreadable")
    if already_enrolled:
        return _no("device_authorization.already_enrolled")
    if already_offered:
        return _no("device_authorization.already_offered")
    return DeviceAuthorizationAssessment(
        DeviceAuthorizationAvailability.OFFERED, "device_authorization.available"
    )
