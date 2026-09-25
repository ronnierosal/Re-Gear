"""The delivery surface for the Game Mode trust prompt.

Most of this is about two failures that look like bugs from the player's side
and like nothing at all from the code's side: a prompt that vanishes because
something read it, and an action that quietly runs twice.  So the reads are
tested for spending nothing, the answers are tested for spending exactly once,
and the executor is tested for being called exactly as often as a person
pressed a button.

The rest is the invariant, and it is worth stating exactly, because three
passes overstated it.  **Re-Gear never puts the router uuid into a payload
itself** -- a router UUID is a hardware unique id (SAFETY_INVARIANTS #12) -- so
every payload produced for a *normal* device, one whose product name is not its
own id, is scanned for the fixture UUID rather than eyeballed.  The fixtures are
obviously synthetic for the same reason: a real router id committed as a fixture
would put a maintainer's own dock in the repository.

"Normal" is load-bearing rather than a hedge.  A device that publishes its own
identifier as its `device_name` has that string displayed, because it is the
only name the device has and a prompt that cannot name a device is the thing
this feature exists to avoid.  That is a device-authored disclosure, not a
Re-Gear diagnostic leak, and `TheResidualIsADeviceAuthoredDisclosure` pins it so
that nobody reintroduces a filter to chase it.  Three were tried.  The last one
counted hex-class characters, and it was disqualified by the false positives:
the full vendor and product strings real docks publish carry twenty or more, a
refused name left the identity unresolved, and a named, addressable, unenrolled
dock silently never got its prompt.  `RealHardwareIsStillOffered` keeps those
product strings here as a permanent regression corpus.

**The guard is written out here, and it does not import anything it guards.**
`squashed` / `surviving_id_run` / `leaks_uuid` spell out their own reduction and
their own number.  The suite this replaces had a leak guard that was a copy of
the production predicate -- the same normalization, the same constant, the same
forward-only window scan -- which is a guard that cannot fail on the bug it
exists to catch, and it did not.

**A payload is checked for contradicting itself, under real threads.**  The
fields of one payload used to be sampled at six different instants, and a
sequential test cannot see that at all: it takes a report or a replug landing
between two of the six.  `NoPayloadEverContradictsItself` races them.
"""

from __future__ import annotations

import inspect
import json
import sys
import tempfile
import threading
import unittest
from dataclasses import dataclass, replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.device_authorization_observer import (  # noqa: E402
    DeviceAuthorizationObserver,
)
from regear.application.device_authorization import (  # noqa: E402
    DeviceAuthorizationService,
)
from regear.delivery.device_authorization_facade import (  # noqa: E402
    DeviceAuthorizationFacade,
)
from regear.ports.device_authorization import (  # noqa: E402
    DeviceEnrollmentResult,
)


#: Synthetic, and deliberately so. See the module docstring.
DOCK_A = "aaaaaaaa-1111-2222-3333-444444444444"
DOCK_B = "bbbbbbbb-5555-6666-7777-888888888888"

STATUS_KEYS = {
    "schema_version",
    "state",
    "code",
    "token",
    "vendor",
    "model",
    "already_offered",
    "intentional_disconnect",
    "confirmation_open",
    "generation",
}

OFFERED = "device_authorization.available"
ALREADY_OFFERED = "device_authorization.already_offered"
SCAN_UNREADABLE = "device_authorization.scan_unreadable"
NO_DEVICE = "device_authorization.no_device"
INTENTIONAL = "device_authorization.intentional_disconnect"
IDENTITY_UNRESOLVED = "device_authorization.identity_unresolved"
CONFIRMATION_REQUIRED = "device_authorization.confirmation_required"
ACTION_INVALID = "device_authorization.action_invalid"
#: What the *service* reports when the executor raises. It names the action
#: that failed: an `authorize` whose command is missing from the image says
#: `authorize_unavailable`, not `enroll_unavailable`. It used to collapse both,
#: which on a production build named the one grant that is not even reachable.
UNAVAILABLE = "device_authorization.authorize_unavailable"
REMEMBERED_UNAVAILABLE = "device_authorization.enroll_unavailable"
#: Asked for the remembered grant from a facade that is not permitted to make
#: one. Spelled out here rather than imported, for the reason `squashed` is:
#: a guard that shares its constant with the code under test cannot notice the
#: constant changing.
NOT_OFFERED = "device_authorization.remembered_grant_not_offered"
REFUSALS = {
    "device_authorization.token_stale",
    "device_authorization.attachment_changed",
}

#: Every key a `confirm` payload carries, refusal or not. Written out rather
#: than derived from a returned payload, so a key silently disappearing from
#: one path is a failure here instead of a panel field that quietly went
#: missing.
CONFIRM_KEYS = {
    "schema_version",
    "requested",
    "code",
    "token",
    "verified",
    "vendor",
    "model",
    "already_offered",
    "intentional_disconnect",
    "confirmation_open",
    "generation",
}


@dataclass(frozen=True, slots=True)
class Scan:
    """What the read-only observer would have returned, without the sysfs."""

    present: bool | None = True
    identity_resolved: bool = True
    authorized: bool | None = False
    enrolled: bool | None = False
    vendor: str = "Synthetic Vendor"
    model: str = "Synthetic Dock"
    uuid: str = DOCK_A


#: A scan that failed. `present=None` is not absence, and nothing may treat it
#: as if it were.
UNREADABLE = Scan(
    present=None,
    identity_resolved=False,
    authorized=None,
    enrolled=None,
    vendor="",
    model="",
    uuid="",
)

#: Nothing attached at all.
EMPTY = Scan(
    present=False,
    identity_resolved=False,
    authorized=None,
    enrolled=None,
    vendor="",
    model="",
    uuid="",
)


class FakeObserver:
    def __init__(self, scan: Scan | None = None) -> None:
        self.scan = Scan() if scan is None else scan
        self.calls = 0
        self.explode = False

    def observe(self) -> Scan:
        self.calls += 1
        if self.explode:
            raise OSError("the scan itself failed")
        return self.scan


class SpyPort:
    """Records what was asked of `boltd`, and answers however the test says."""

    def __init__(
        self,
        enrolled: bool = True,
        code: str = "device_authorization.requested",
        explode: bool = False,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.enrolled = enrolled
        self.code = code
        self.explode = explode

    def _answer(self, action: str, uuid: str) -> DeviceEnrollmentResult:
        self.calls.append((action, uuid))
        if self.explode:
            raise RuntimeError("boltctl is not on this image")
        return DeviceEnrollmentResult(self.enrolled, self.code)

    def enroll(self, uuid: str) -> DeviceEnrollmentResult:
        return self._answer("enroll", uuid)

    def authorize(self, uuid: str) -> DeviceEnrollmentResult:
        return self._answer("authorize", uuid)


#: "the constructor was not given the argument at all", which is a different
#: fixture from "was given False": production wiring passes nothing, so the
#: default-path tests below have to exercise the object built with nothing.
_UNSET = object()


def build(
    scan: Scan | None = None,
    *,
    remembered_grant_enabled: object = _UNSET,
    **port_kwargs,
):
    """The facade as production wires it, unless a test opts in explicitly.

    Leaving `remembered_grant_enabled` alone constructs the facade with two
    positional arguments and nothing else -- the same call `main.py` makes --
    so every test that does not name the opt-in is testing the shipped object
    rather than a fixture that happens to agree with it.
    """
    observer = FakeObserver(scan)
    port = SpyPort(**port_kwargs)
    service = DeviceAuthorizationService(port)
    if remembered_grant_enabled is _UNSET:
        facade = DeviceAuthorizationFacade(observer, service)
    else:
        facade = DeviceAuthorizationFacade(
            observer, service, remembered_grant_enabled=remembered_grant_enabled
        )
    return observer, port, service, facade


def rendered(payload: dict) -> str:
    """The payload exactly as an RPC would put it on the wire.

    Doubles as the JSON-safety check: anything that is not JSON-safe fails
    here rather than at 3am on a handheld.
    """
    return json.dumps(payload, sort_keys=True)


#: The longest stretch of a router id that may survive into a payload built for
#: a normal device. Nothing should carry any of it: a run this long is already
#: far past coincidence between a product string, this backend's own vocabulary
#: and a random hex token, so it is a leak. Spelled as a number here rather than
#: imported, because a guard that shares a constant with the code under test
#: cannot notice the constant being relaxed.
MAX_TOLERATED_ID_RUN = 11


def squashed(value: str) -> str:
    """Lowercase ASCII letters and digits, and nothing else.

    Written out here rather than imported from the facade on purpose. The old
    guard was the *identical* literal-substring test the production code used,
    so it could not fail on the bug it existed to catch: one TAB inside the
    uuid defeated both at once. A guard has to be able to disagree with the
    thing it is guarding.
    """
    return "".join(
        character
        for character in value.casefold()
        if "a" <= character <= "z" or "0" <= character <= "9"
    )


def surviving_id_run(text: str, uuid: str) -> str:
    """The longest run of the uuid's own characters left in `text`.

    Both sides are squashed first, so a leak cannot hide behind separators or
    behind a cap that cut the id in half: "aaaaaaaa-1111", "aaaaaaaa\x001111"
    and a truncated "aaaaaaaa 1111" are all the same twelve characters of a
    hardware identifier.
    """
    identity = squashed(uuid)
    candidate = squashed(text)
    longest = ""
    for start in range(len(identity)):
        for end in range(start + len(longest) + 1, len(identity) + 1):
            run = identity[start:end]
            if run in candidate:
                longest = run
    return longest


def leaks_uuid(payload: dict, uuid: str) -> bool:
    """Whether a payload still spells out the router id, however it is written.

    The values are scanned as they are as well as on the wire, because JSON
    escaping is itself a separator: a NUL rendered as `\\u0000` would break the
    id into pieces in the wire form while the string the panel receives still
    holds every character of it.

    Contiguity is this guard's blind spot, and it is an acceptable one now that
    nothing here is trying to defeat a filter: what it answers is whether this
    backend copied an id it holds into a payload, which it does in one piece or
    not at all.
    """
    haystack = rendered(payload) + "".join(
        value for value in payload.values() if isinstance(value, str)
    )
    return len(surviving_id_run(haystack, uuid)) > MAX_TOLERATED_ID_RUN


def offer(facade: DeviceAuthorizationFacade) -> str:
    """Drive one attachment to an open offer and return its token."""
    status = facade.status()
    assert status["state"] == "offered", status
    return status["token"]


class PollingDoesNotConsumeThePrompt(unittest.TestCase):
    """A status read is a read. The panel polls; the prompt has to survive."""

    def test_a_fresh_attachment_is_offered(self):
        _, _, _, facade = build()
        status = facade.status()
        self.assertEqual(status["state"], "offered")
        self.assertEqual(status["code"], OFFERED)
        self.assertTrue(status["token"])
        self.assertFalse(status["already_offered"])
        self.assertFalse(status["confirmation_open"])

    def test_reading_twice_does_not_lose_the_prompt(self):
        _, _, _, facade = build()
        first = facade.status()
        second = facade.status()
        self.assertEqual(second["state"], "offered")
        self.assertEqual(second["code"], OFFERED)
        self.assertEqual(first["token"], second["token"])

    def test_reading_repeatedly_never_spends_the_latch(self):
        _, _, service, facade = build()
        for _ in range(5):
            status = facade.status()
            self.assertFalse(status["already_offered"])
        self.assertFalse(service.offered)

    def test_the_token_is_stable_while_the_attachment_lasts(self):
        _, _, _, facade = build()
        tokens = {facade.status()["token"] for _ in range(4)}
        self.assertEqual(len(tokens), 1)

    def test_nothing_attached_offers_nothing_and_names_nothing(self):
        _, _, _, facade = build(EMPTY)
        status = facade.status()
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["code"], NO_DEVICE)
        self.assertEqual(status["token"], "")
        self.assertEqual(status["vendor"], "")
        self.assertEqual(status["model"], "")

    def test_polling_an_empty_port_returns_one_stable_payload(self):
        """The reproduced defect: undocked is the default state of a handheld.

        Retiring on every absent poll ticked the generation once per poll, so
        a thousand polls with nothing plugged in reported generation 1000 and
        no two reads of a completely unchanging port agreed with each other.
        """
        _, _, _, facade = build(EMPTY)
        payloads = {rendered(facade.status()) for _ in range(50)}
        self.assertEqual(len(payloads), 1)
        self.assertEqual(facade.status()["generation"], 0)

    def test_an_already_authorized_dock_is_not_offered(self):
        _, _, _, facade = build(Scan(authorized=True))
        status = facade.status()
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["token"], "")

    def test_the_payload_carries_exactly_the_contract_keys(self):
        _, _, _, facade = build()
        self.assertEqual(set(facade.status()), STATUS_KEYS)

    def test_the_payload_is_json_safe(self):
        """The round trip has to come back, not merely go out.

        `json.dumps` not raising says the payload can be encoded; it says
        nothing about what the panel receives. A field that survives encoding
        and comes back as something else -- a tuple as a list, a value the
        encoder stringified -- is a payload the contract does not describe, and
        a test that only encodes cannot fail on one.
        """
        for scan in (Scan(), UNREADABLE, EMPTY, Scan(authorized=None)):
            with self.subTest(scan=scan):
                _, _, _, scanned = build(scan)
                status = scanned.status()
                decoded = json.loads(rendered(status))
                self.assertEqual(decoded, status)
                self.assertEqual(set(decoded), STATUS_KEYS)
                for key, value in status.items():
                    self.assertIs(type(decoded[key]), type(value), key)

    def test_the_generation_is_an_integer(self):
        _, _, _, facade = build()
        self.assertIsInstance(facade.status()["generation"], int)


class AcknowledgingIsWhatSpendsIt(unittest.TestCase):
    """The prompt is spent by being answered, not by being looked at."""

    def test_acknowledge_spends_the_latch(self):
        _, _, service, facade = build()
        token = offer(facade)
        payload = facade.acknowledge(token)
        self.assertTrue(payload["accepted"])
        self.assertTrue(service.offered)
        self.assertTrue(payload["already_offered"])

    def test_after_acknowledging_status_reports_the_same_open_confirmation(self):
        _, _, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        status = facade.status()
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["code"], ALREADY_OFFERED)
        self.assertTrue(status["confirmation_open"])
        self.assertEqual(status["token"], token)

    def test_an_open_confirmation_survives_being_re_read(self):
        _, _, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        for _ in range(3):
            status = facade.status()
            self.assertTrue(status["confirmation_open"])
            self.assertEqual(status["token"], token)

    def test_an_open_confirmation_survives_a_scan_that_goes_unreadable(self):
        """A dialog on screen must not be stranded by a failed read."""
        observer, _, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        observer.scan = UNREADABLE
        status = facade.status()
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["code"], SCAN_UNREADABLE)
        self.assertTrue(status["confirmation_open"])
        self.assertEqual(status["token"], token)

    def test_an_unknown_token_spends_nothing(self):
        _, _, service, facade = build()
        offer(facade)
        payload = facade.acknowledge("not-a-token")
        self.assertFalse(payload["accepted"])
        self.assertFalse(service.offered)
        self.assertEqual(facade.status()["state"], "offered")

    def test_acknowledging_twice_does_not_reopen_anything(self):
        _, _, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        again = facade.acknowledge(token)
        self.assertTrue(again["confirmation_open"])
        self.assertEqual(again["token"], token)
        self.assertEqual(again["code"], ALREADY_OFFERED)


class DecliningIsScopedToThisAttachment(unittest.TestCase):
    """"Not now" is an answer about this dock, not a permanent verdict."""

    def test_declining_suppresses_the_offer(self):
        _, _, _, facade = build()
        token = offer(facade)
        payload = facade.decline(token)
        self.assertTrue(payload["accepted"])
        self.assertEqual(payload["state"], "unavailable")
        self.assertEqual(payload["code"], ALREADY_OFFERED)
        self.assertEqual(payload["token"], "")
        self.assertFalse(payload["confirmation_open"])

    def test_a_declined_offer_does_not_come_back_on_the_next_poll(self):
        _, _, _, facade = build()
        facade.decline(offer(facade))
        for _ in range(3):
            status = facade.status()
            self.assertEqual(status["state"], "unavailable")
            self.assertEqual(status["token"], "")

    def test_declining_does_not_blacklist_the_next_device(self):
        observer, _, _, facade = build()
        first = offer(facade)
        facade.decline(first)
        observer.scan = Scan(uuid=DOCK_B, vendor="Other Vendor", model="Other Dock")
        status = facade.status()
        self.assertEqual(status["state"], "offered")
        self.assertNotEqual(status["token"], first)
        self.assertTrue(status["token"])

    def test_replugging_the_same_dock_asks_again_with_a_new_token(self):
        observer, _, _, facade = build()
        first = offer(facade)
        facade.decline(first)
        observer.scan = EMPTY
        gone = facade.status()
        self.assertEqual(gone["code"], NO_DEVICE)
        observer.scan = Scan()
        back = facade.status()
        self.assertEqual(back["state"], "offered")
        self.assertNotEqual(back["token"], first)
        # `> gone - 1` reduces to `>= gone`, which is true of a generation
        # that never moved at all. The claim is that the replug is a new
        # attachment, so the assertion has to be the strict one.
        self.assertGreater(back["generation"], gone["generation"])

    def test_a_replacement_device_is_a_new_generation(self):
        observer, _, _, facade = build()
        before = facade.status()
        observer.scan = Scan(uuid=DOCK_B)
        after = facade.status()
        self.assertNotEqual(after["generation"], before["generation"])
        self.assertNotEqual(after["token"], before["token"])

    def test_an_unknown_token_declines_nothing(self):
        _, _, _, facade = build()
        offer(facade)
        payload = facade.decline("not-a-token")
        self.assertFalse(payload["accepted"])
        self.assertEqual(facade.status()["state"], "offered")


class NoHardwareIdEverLeaves(unittest.TestCase):
    """SAFETY_INVARIANTS #12, checked by scanning rather than by reading.

    The guarantee, and the whole of it: for a normal device -- one whose
    product name is not its own id -- this backend puts the uuid in no payload
    it produces.  Every fixture here is a dock with an ordinary name, so what
    these scan for is *this code copying an id it holds*, which is the thing
    it is in a position to promise.
    """

    def test_the_status_payload_never_contains_the_uuid(self):
        _, _, _, facade = build()
        self.assertFalse(leaks_uuid(facade.status(), DOCK_A))

    def test_no_answer_payload_ever_contains_the_uuid(self):
        _, _, _, facade = build()
        token = offer(facade)
        self.assertFalse(leaks_uuid(facade.acknowledge(token), DOCK_A))
        self.assertFalse(
            leaks_uuid(
                facade.confirm(token, consent=True, action="authorize"), DOCK_A
            )
        )
        _, _, _, other = build()
        self.assertFalse(leaks_uuid(other.decline(offer(other)), DOCK_A))

    def test_a_refused_confirmation_never_contains_the_uuid(self):
        _, _, _, facade = build()
        token = offer(facade)
        for consent, action in ((False, "authorize"), (True, "nonsense")):
            with self.subTest(consent=consent, action=action):
                payload = facade.confirm(token, consent=consent, action=action)
                self.assertFalse(leaks_uuid(payload, DOCK_A))

    def test_labels_are_collapsed_and_capped(self):
        _, _, _, facade = build(Scan(vendor="  Loud   Vendor\n", model="M" * 200))
        status = facade.status()
        self.assertEqual(status["vendor"], "Loud Vendor")
        self.assertEqual(len(status["model"]), 64)

    def test_a_control_byte_in_a_label_becomes_a_space_and_never_travels(self):
        """A label is rendered somewhere. An escape sequence is not a name.

        The observer sanitizes what it reads, and this is the same rule at the
        boundary the payload leaves through, so the claim holds for a reading
        that arrived some other way too.
        """
        _, _, _, facade = build(
            Scan(vendor="By\x1b]0;x\x07Vendor", model="Dock\x00Two")
        )
        status = facade.status()
        self.assertEqual(status["model"], "Dock Two")
        self.assertEqual(status["state"], "offered")
        for label in (status["vendor"], status["model"]):
            self.assertTrue(all(" " <= character <= "~" for character in label))

    def test_a_label_cut_at_the_cap_does_not_keep_a_trailing_space(self):
        _, _, _, facade = build(Scan(model="M" * 63 + " Dock"))
        status = facade.status()
        self.assertEqual(status["model"], "M" * 63)

    def test_the_token_is_not_derived_from_the_uuid(self):
        observer, _, _, facade = build()
        first = offer(facade)
        observer.scan = Scan(uuid=DOCK_B)
        second = facade.status()["token"]
        for token in (first, second):
            self.assertNotIn(token.replace("-", ""), DOCK_A.replace("-", ""))
            self.assertNotIn(token.replace("-", ""), DOCK_B.replace("-", ""))


class AnUnreadableScanChangesNothing(unittest.TestCase):
    """"I could not look" is not "nothing is there", and never rearms."""

    def test_an_unreadable_scan_is_not_an_offer(self):
        _, _, _, facade = build(UNREADABLE)
        status = facade.status()
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["code"], SCAN_UNREADABLE)
        self.assertEqual(status["token"], "")

    def test_an_unreadable_scan_does_not_rearm_a_spent_prompt(self):
        observer, _, service, facade = build()
        facade.decline(offer(facade))
        observer.scan = UNREADABLE
        facade.status()
        observer.scan = Scan()
        status = facade.status()
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["code"], ALREADY_OFFERED)
        self.assertTrue(service.offered)

    def test_an_observer_that_raises_reads_as_an_unreadable_scan(self):
        observer, _, _, facade = build()
        observer.explode = True
        status = facade.status()
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["code"], SCAN_UNREADABLE)
        self.assertEqual(status["token"], "")
        self.assertEqual(status["vendor"], "")

    def test_an_observer_that_raises_does_not_rearm_a_spent_prompt(self):
        observer, _, service, facade = build()
        facade.decline(offer(facade))
        observer.explode = True
        facade.status()
        observer.explode = False
        self.assertTrue(service.offered)
        self.assertEqual(facade.status()["code"], ALREADY_OFFERED)

    def test_a_nonsense_reading_is_unknown_rather_than_a_decision(self):
        """A truthy string is not a present device."""
        _, _, _, facade = build(Scan(present="yes", authorized="0"))
        status = facade.status()
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["code"], SCAN_UNREADABLE)


class IntentionalDisconnectIsKeyedToTheDevice(unittest.TestCase):
    """A dock Re-Gear deauthorized on purpose is not a first-time stranger.

    The report names the device and nothing else.  Keying it to the attachment
    *generation* was the previous decision and it is reversed here, because it
    could not be filed at all: deauthorizing the dock is what makes it read
    absent, the absent poll retires the attachment and bumps the generation,
    and the owning layer -- holding the number it read while the dock was still
    there -- was always exactly one poll too late.  Every report was refused,
    the flag was never set, and the dock came back on the next wake as
    first-time trust with a full confirmation behind it.

    Filing while nothing was named was the other half: it bound the
    disownership to `""`, which then attached to whatever enumerated next and
    refused a different, never-disowned dock forever with no exit a player
    could reach.
    """

    def test_the_signature_names_a_device_and_no_generation(self):
        signature = inspect.signature(
            DeviceAuthorizationFacade.note_intentional_disconnect
        )
        self.assertEqual(list(signature.parameters), ["self", "active", "uuid"])
        self.assertIs(
            signature.parameters["uuid"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        self.assertNotIn("generation", signature.parameters)

    def test_it_blocks_the_offer(self):
        _, _, _, facade = build()
        facade.status()
        self.assertTrue(facade.note_intentional_disconnect(True, uuid=DOCK_A))
        status = facade.status()
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["code"], INTENTIONAL)
        self.assertTrue(status["intentional_disconnect"])
        self.assertEqual(status["token"], "")

    def test_it_blocks_confirm_without_touching_the_executor(self):
        _, port, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        facade.note_intentional_disconnect(True, uuid=DOCK_A)
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertFalse(payload["requested"])
        self.assertEqual(payload["code"], INTENTIONAL)
        self.assertTrue(payload["intentional_disconnect"])
        self.assertEqual(port.calls, [])

    def test_clearing_it_restores_the_offer(self):
        _, _, _, facade = build()
        facade.status()
        facade.note_intentional_disconnect(True, uuid=DOCK_A)
        self.assertTrue(facade.note_intentional_disconnect(False, uuid=DOCK_A))
        status = facade.status()
        self.assertEqual(status["state"], "offered")
        self.assertFalse(status["intentional_disconnect"])

    def test_the_deauthorization_that_made_the_dock_absent_can_still_be_filed(self):
        """The reproduced defect that reversed the previous decision.

        Deauthorizing the dock is what makes it read absent, so by the time the
        owning layer files, the attachment it was looking at is already gone
        and its generation is already stale. Under the generation-keyed report
        this sequence recorded nothing at all, every time, and the dock came
        back on the next wake as a brand-new device.
        """
        observer, port, _, facade = build()
        facade.status()
        # The deauthorization lands: the dock now reads absent, and the poll
        # that notices retires the attachment underneath the caller.
        observer.scan = EMPTY
        facade.status()
        self.assertTrue(facade.note_intentional_disconnect(True, uuid=DOCK_A))
        # The wake. Same dock, fresh enumeration, and no prompt.
        observer.scan = Scan()
        status = facade.status()
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["code"], INTENTIONAL)
        self.assertTrue(status["intentional_disconnect"])
        payload = facade.confirm(status["token"], consent=True, action="authorize")
        self.assertFalse(payload["requested"])
        self.assertEqual(port.calls, [])

    def test_a_report_can_be_filed_with_nothing_attached_at_all(self):
        _, _, _, facade = build(EMPTY)
        facade.status()
        self.assertTrue(facade.note_intentional_disconnect(True, uuid=DOCK_A))
        self.assertEqual(facade.status()["code"], NO_DEVICE)

    def test_a_report_filed_before_anything_was_ever_observed_still_names_it(self):
        """No read comes first, so there is nothing to race with a poll."""
        observer, _, _, facade = build(EMPTY)
        self.assertTrue(facade.note_intentional_disconnect(True, uuid=DOCK_A))
        observer.scan = Scan()
        status = facade.status()
        self.assertEqual(status["code"], INTENTIONAL)
        self.assertTrue(status["intentional_disconnect"])

    def test_a_report_about_a_dock_that_is_not_the_attached_one_gates_nothing(self):
        observer, _, _, facade = build()
        observer.scan = Scan(uuid=DOCK_B, vendor="Other Vendor", model="Other Dock")
        facade.status()
        self.assertTrue(facade.note_intentional_disconnect(True, uuid=DOCK_A))
        status = facade.status()
        self.assertEqual(status["state"], "offered")
        self.assertFalse(status["intentional_disconnect"])

    def test_a_different_dock_is_never_refused_for_the_disowned_one(self):
        """The permanent blacklist, which is the other reversed defect.

        Binding the disownership to whatever enumerated next refused a dock
        nobody had ever disowned, forever, with no player-reachable exit.
        """
        observer, _, _, facade = build()
        facade.status()
        facade.note_intentional_disconnect(True, uuid=DOCK_A)
        observer.scan = EMPTY
        facade.status()
        observer.scan = Scan(uuid=DOCK_B, vendor="Other Vendor", model="Other Dock")
        status = facade.status()
        self.assertEqual(status["state"], "offered")
        self.assertFalse(status["intentional_disconnect"])
        self.assertTrue(status["token"])

    def test_another_dock_attaching_does_not_clear_the_disownership(self):
        """A second dock is not evidence about the first."""
        observer, _, _, facade = build()
        facade.status()
        facade.note_intentional_disconnect(True, uuid=DOCK_A)
        observer.scan = Scan(uuid=DOCK_B, vendor="Other Vendor", model="Other Dock")
        self.assertEqual(facade.status()["state"], "offered")
        observer.scan = Scan()
        status = facade.status()
        self.assertEqual(status["code"], INTENTIONAL)
        self.assertTrue(status["intentional_disconnect"])

    def test_nothing_but_the_same_uuid_clears_it(self):
        observer, _, _, facade = build()
        facade.status()
        facade.note_intentional_disconnect(True, uuid=DOCK_A)
        # A clear for a different device is a statement about that device.
        self.assertTrue(facade.note_intentional_disconnect(False, uuid=DOCK_B))
        self.assertEqual(facade.status()["code"], INTENTIONAL)
        # An absence, a wake and a replug are not clears either.
        observer.scan = EMPTY
        facade.status()
        observer.scan = Scan()
        self.assertEqual(facade.status()["code"], INTENTIONAL)
        self.assertTrue(facade.note_intentional_disconnect(False, uuid=DOCK_A))
        self.assertEqual(facade.status()["state"], "offered")

    def test_the_same_dock_coming_back_is_still_the_dock_we_disowned(self):
        """The reproduced defect: one empty poll re-offered it after a wake.

        Absence and a replug read identically from sysfs, so the same device
        reappearing stays blocked until the layer that owns the cable files a
        clear. That is the trade, not an oversight -- see the service module.
        """
        observer, port, _, facade = build()
        facade.status()
        facade.note_intentional_disconnect(True, uuid=DOCK_A)
        observer.scan = EMPTY
        facade.status()
        observer.scan = Scan()
        status = facade.status()
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["code"], INTENTIONAL)
        self.assertTrue(status["intentional_disconnect"])
        self.assertEqual(status["token"], "")
        payload = facade.confirm(status["token"], consent=True, action="authorize")
        self.assertFalse(payload["requested"])
        self.assertEqual(port.calls, [])

    def test_a_uuid_that_is_not_a_non_empty_string_is_refused(self):
        """It must never bind to "", so "" is not a device it can be filed for."""
        for uuid in ("", None, 0, [], True, b"aaaa"):
            with self.subTest(uuid=repr(uuid)):
                _, _, service, facade = build()
                facade.status()
                self.assertIs(
                    facade.note_intentional_disconnect(True, uuid=uuid), False
                )
                self.assertFalse(service.intentional_disconnect)
                status = facade.status()
                self.assertEqual(status["state"], "offered")
                self.assertFalse(status["intentional_disconnect"])

    def test_a_report_the_service_refused_is_not_written_into_the_payload(self):
        """The reproduced defect: `offered` and `intentional_disconnect` at once.

        The mirror this layer used to keep was written from the caller's
        argument rather than from the service's answer, so a report the service
        had refused still showed up in the payload.
        """
        _, _, _, facade = build()
        facade.status()
        self.assertIs(facade.note_intentional_disconnect(True, uuid=""), False)
        status = facade.status()
        self.assertEqual(status["state"], "offered")
        self.assertFalse(status["intentional_disconnect"])

    def test_a_report_that_is_not_a_boolean_is_refused_by_both_layers(self):
        for value in (1, "yes", [1], 0, None, ""):
            with self.subTest(active=repr(value)):
                _, _, service, facade = build()
                facade.status()
                self.assertIs(
                    facade.note_intentional_disconnect(value, uuid=DOCK_A),
                    False,
                )
                self.assertFalse(service.intentional_disconnect)
                status = facade.status()
                self.assertEqual(status["state"], "offered")
                self.assertFalse(status["intentional_disconnect"])

    def test_a_non_boolean_never_clears_a_report_that_stands(self):
        _, _, _, facade = build()
        facade.status()
        facade.note_intentional_disconnect(True, uuid=DOCK_A)
        for value in (0, None, "", []):
            with self.subTest(active=repr(value)):
                self.assertIs(
                    facade.note_intentional_disconnect(value, uuid=DOCK_A),
                    False,
                )
                status = facade.status()
                self.assertEqual(status["code"], INTENTIONAL)
                self.assertTrue(status["intentional_disconnect"])


class TheDisconnectFlagHasOneOwner(unittest.TestCase):
    """This layer forwards the report and reads the answer. It stores nothing."""

    class RecordingService:
        """Just enough service to watch what the facade hands it."""

        def __init__(self, answer: object = True) -> None:
            self.answer = answer
            self.calls: list[tuple[object, dict]] = []

        def note_intentional_disconnect(self, active, **keywords):
            self.calls.append((active, keywords))
            return self.answer

    def forwarding(self, answer: object):
        service = self.RecordingService(answer)
        return service, DeviceAuthorizationFacade(FakeObserver(), service)

    def test_the_report_is_forwarded_naming_the_device_and_nothing_else(self):
        service, facade = self.forwarding(True)
        facade.note_intentional_disconnect(True, uuid=DOCK_A)
        self.assertEqual(service.calls, [(True, {"uuid": DOCK_A})])

    def test_the_services_decision_is_what_comes_back(self):
        for answer in (True, False):
            with self.subTest(answer=answer):
                _, facade = self.forwarding(answer)
                self.assertIs(
                    facade.note_intentional_disconnect(True, uuid=DOCK_A),
                    answer,
                )

    def test_an_answer_that_is_not_a_boolean_is_not_an_acceptance(self):
        for answer in ("recorded", 1, None, [1]):
            with self.subTest(answer=repr(answer)):
                _, facade = self.forwarding(answer)
                self.assertIs(
                    facade.note_intentional_disconnect(True, uuid=DOCK_A),
                    False,
                )

    def test_a_refusal_is_forwarded_rather_than_pre_empted(self):
        """The rule belongs to the service, so the service is asked.

        A copy of the validation here is a second place for it to drift, and
        the payload contradicting itself is what two copies produced last time.
        """
        service, facade = self.forwarding(False)
        facade.note_intentional_disconnect("yes", uuid="")
        self.assertEqual(service.calls, [("yes", {"uuid": ""})])

    def test_the_payload_reads_the_flag_from_the_service(self):
        """Filed straight into the service, never through this layer.

        A facade keeping its own copy would report `False` here, because it
        never saw the report.
        """
        _, _, service, facade = build()
        facade.status()
        self.assertTrue(service.note_intentional_disconnect(True, uuid=DOCK_A))
        status = facade.status()
        self.assertTrue(status["intentional_disconnect"])
        self.assertEqual(status["code"], INTENTIONAL)
        self.assertEqual(status["state"], "unavailable")


class ConfirmBindsWhatItObserves(unittest.TestCase):
    """The panel supplies an answer. It never supplies a device."""

    def test_the_signature_accepts_no_identity_from_the_caller(self):
        params = list(
            inspect.signature(DeviceAuthorizationFacade.confirm).parameters
        )
        self.assertEqual(params, ["self", "token", "consent", "action"])

    def test_the_executor_is_named_by_the_observation(self):
        _, port, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        facade.confirm(token, consent=True, action="authorize")
        self.assertEqual(port.calls, [("authorize", DOCK_A)])

    def test_confirm_re_observes_rather_than_trusting_the_prompt(self):
        observer, _, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        before = observer.calls
        facade.confirm(token, consent=True, action="authorize")
        self.assertGreater(observer.calls, before)

    def test_a_device_that_changed_under_the_dialog_refuses(self):
        """A confirmation drawn against one dock cannot trust another."""
        observer, port, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        observer.scan = Scan(uuid=DOCK_B)
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertFalse(payload["requested"])
        self.assertIn(payload["code"], REFUSALS)
        self.assertEqual(port.calls, [])

    def test_a_dock_that_went_away_refuses(self):
        observer, port, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        observer.scan = EMPTY
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertFalse(payload["requested"])
        self.assertEqual(port.calls, [])

    def test_an_unreadable_scan_refuses_rather_than_acting_blind(self):
        observer, port, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        observer.scan = UNREADABLE
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertFalse(payload["requested"])
        self.assertEqual(port.calls, [])

    def test_consent_must_be_exactly_true(self):
        for consent in (False, None, 1, "yes", [1], {"ok": True}):
            with self.subTest(consent=consent):
                _, port, _, facade = build()
                token = offer(facade)
                facade.acknowledge(token)
                payload = facade.confirm(token, consent=consent, action="authorize")
                self.assertFalse(payload["requested"])
                self.assertEqual(payload["code"], CONFIRMATION_REQUIRED)
                self.assertEqual(port.calls, [])

    def test_the_action_is_one_of_exactly_two(self):
        for action in ("Enroll", "", None, "trust", "authorise", 1):
            with self.subTest(action=action):
                _, port, _, facade = build()
                token = offer(facade)
                facade.acknowledge(token)
                payload = facade.confirm(token, consent=True, action=action)
                self.assertFalse(payload["requested"])
                self.assertEqual(payload["code"], ACTION_INVALID)
                self.assertEqual(port.calls, [])

    def test_authorize_goes_to_the_one_shot_command(self):
        _, port, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertTrue(payload["requested"])
        self.assertEqual(port.calls, [("authorize", DOCK_A)])

    def test_an_unknown_token_never_reaches_the_executor(self):
        _, port, _, facade = build()
        offer(facade)
        payload = facade.confirm("not-a-token", consent=True, action="authorize")
        self.assertFalse(payload["requested"])
        self.assertIn(payload["code"], REFUSALS)
        self.assertEqual(port.calls, [])


class TheRememberedGrantIsNotOnOfferFromHere(unittest.TestCase):
    """`enroll` is refused by this facade, and the refusal costs nothing.

    The approved scope of this feature is a **first-time authorization**: the
    player is asked once, the dock is trusted for this attachment, and
    `boltd`'s enrolment database is left alone.  Remembering a device is a
    different promise -- it re-authorizes the dock on every later plug, with
    nobody asked again -- and it is deliberately not reachable through the
    surface Game Mode talks to.

    That is a property of the object rather than a convention about callers.
    Production wiring constructs this facade with two positional arguments and
    passes no opt-in, so an RPC that sends `action="enroll"` -- a stale panel,
    a mistake, or a caller that got the string from somewhere it should not
    have -- is answered with a refusal instead of a stored grant of direct
    access to system memory.

    The refusal is taken **before** anything is observed for the act, spent or
    executed, and that is what most of this class is about: a wrong action
    string must not be able to cost the player the prompt they were actually
    going to be asked.  The two obvious wrong ways to make this suite green --
    flipping the default, or opting in everywhere -- erase exactly that.
    """

    def test_enroll_is_refused_by_the_facade_production_builds(self):
        _, port, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        payload = facade.confirm(token, consent=True, action="enroll")
        self.assertFalse(payload["requested"])
        self.assertEqual(payload["code"], NOT_OFFERED)
        self.assertEqual(port.calls, [])

    def test_the_refusal_reports_the_services_token_not_the_callers_string(self):
        """The one payload field that could have echoed caller input.

        Every other `confirm` path reports `outcome.token`, which the service
        fills with a token it minted or with `""`.  This refusal answers before
        the service is asked about the token at all, so the lazy version of it
        reflected the caller's argument straight back into the payload --
        uncapped and unsanitised, unlike `vendor` and `model` beside it, which
        are capped printable ASCII.  Reporting the live token is also the
        truthful answer: the prompt was not spent, so that is still the handle
        to press with.
        """
        _, port, _, facade = build()
        live = offer(facade)
        facade.acknowledge(live)
        for junk in (
            "not-a-token",
            "../../etc/passwd",
            "x" * 5000,
            "<script>alert(1)</script>",
            live.upper(),
            "",
        ):
            with self.subTest(token=junk[:40]):
                payload = facade.confirm(junk, consent=True, action="enroll")
                self.assertEqual(payload["code"], NOT_OFFERED)
                self.assertEqual(
                    payload["token"],
                    live,
                    "the refusal must report the token the service holds",
                )
                self.assertNotEqual(payload["token"], junk)
                self.assertEqual(port.calls, [])
        # And the prompt really did survive every one of those.
        self.assertTrue(
            facade.confirm(live, consent=True, action="authorize")["requested"]
        )

    def test_the_executor_is_never_reached_however_ready_everything_else_is(self):
        """Present, named, acknowledged, consented -- and still no command.

        Everything the domain checks would have said yes here, so the only
        thing between this call and a stored DMA grant is the gate.  Pressed
        twice, because "refused once, then it goes through" is a real shape of
        this bug.
        """
        _, port, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        facade.confirm(token, consent=True, action="enroll")
        facade.confirm(token, consent=True, action="enroll")
        self.assertEqual(port.calls, [])

    def test_the_refusal_does_not_spend_the_latch(self):
        """The prompt the player was going to be asked survives the refusal.

        A refusal that consumed the offer would turn a caller's bad action
        string into a dock that silently never gets its dialog -- the failure
        this whole feature exists to prevent, arriving through the door meant
        to prevent it.
        """
        _, port, _, facade = build()
        token = offer(facade)
        refused = facade.confirm(token, consent=True, action="enroll")
        self.assertEqual(refused["code"], NOT_OFFERED)
        status = facade.status()
        self.assertEqual(status["state"], "offered")
        self.assertEqual(status["code"], OFFERED)
        self.assertEqual(status["token"], token)
        self.assertFalse(status["already_offered"])
        self.assertEqual(port.calls, [])

    def test_the_refused_token_is_still_live_for_the_action_that_is_offered(self):
        """The whole point of refusing early: the real journey still works."""
        _, port, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        self.assertEqual(
            facade.confirm(token, consent=True, action="enroll")["code"],
            NOT_OFFERED,
        )
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertTrue(payload["requested"])
        self.assertEqual(payload["token"], token)
        self.assertEqual(port.calls, [("authorize", DOCK_A)])

    def test_the_refusal_does_not_close_an_open_confirmation(self):
        _, _, _, facade = build()
        token = offer(facade)
        self.assertTrue(facade.acknowledge(token)["confirmation_open"])
        refused = facade.confirm(token, consent=True, action="enroll")
        self.assertTrue(refused["confirmation_open"])
        self.assertTrue(facade.status()["confirmation_open"])

    def test_the_refusal_payload_carries_the_whole_contract(self):
        """A refusal is a payload the panel renders, not a stub."""
        _, _, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        payload = facade.confirm(token, consent=True, action="enroll")
        self.assertEqual(set(payload), CONFIRM_KEYS)
        self.assertIs(payload["requested"], False)
        self.assertIsNone(payload["verified"])
        self.assertEqual(payload["token"], token)
        self.assertIsInstance(payload["generation"], int)
        self.assertNotIsInstance(payload["generation"], bool)
        json.loads(rendered(payload))

    def test_the_refusal_still_names_the_device_it_refused_for(self):
        _, _, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        payload = facade.confirm(token, consent=True, action="enroll")
        self.assertEqual(payload["vendor"], "Synthetic Vendor")
        self.assertEqual(payload["model"], "Synthetic Dock")
        self.assertFalse(leaks_uuid(payload, DOCK_A))

    def test_the_opt_in_is_keyword_only_and_defaults_to_off(self):
        parameter = inspect.signature(
            DeviceAuthorizationFacade.__init__
        ).parameters["remembered_grant_enabled"]
        self.assertIs(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(parameter.default, False)

    def test_a_truthy_non_bool_does_not_turn_the_opt_in_on(self):
        """Enabling a DMA grant is not something a stray `1` gets to do.

        The flag is stored with `is True`, so a value that merely happens to be
        truthy -- a JSON `1`, a `"yes"` off a config line, a non-empty list --
        leaves the remembered grant exactly as unreachable as it was.  A
        `bool()` there would let every one of these through.
        """
        for enabled in (1, "yes", [1], "false", 2.5, object()):
            with self.subTest(remembered_grant_enabled=repr(enabled)):
                _, port, _, facade = build(remembered_grant_enabled=enabled)
                token = offer(facade)
                facade.acknowledge(token)
                payload = facade.confirm(token, consent=True, action="enroll")
                self.assertFalse(payload["requested"])
                self.assertEqual(payload["code"], NOT_OFFERED)
                self.assertEqual(port.calls, [])

    def test_a_falsey_value_leaves_it_off_too(self):
        for enabled in (False, 0, "", None, []):
            with self.subTest(remembered_grant_enabled=repr(enabled)):
                _, port, _, facade = build(remembered_grant_enabled=enabled)
                token = offer(facade)
                facade.acknowledge(token)
                payload = facade.confirm(token, consent=True, action="enroll")
                self.assertEqual(payload["code"], NOT_OFFERED)
                self.assertEqual(port.calls, [])

    # -- the opt-in itself, which is not what production wires ---------------

    def test_the_opt_in_lets_enroll_reach_the_executor_unchanged(self):
        """**Opt-in only.** Not a description of what production does.

        `remembered_grant_enabled=True` is named explicitly here and nothing
        that ships passes it.  What this pins is that the gate is a gate and
        not a deletion: the remembered grant is retained in the port, the
        service and the runner, and with the opt-in on it runs exactly the
        command it always ran and returns the same payload shape.
        """
        _, port, _, facade = build(remembered_grant_enabled=True)
        token = offer(facade)
        facade.acknowledge(token)
        payload = facade.confirm(token, consent=True, action="enroll")
        self.assertTrue(payload["requested"])
        self.assertEqual(payload["code"], "device_authorization.requested")
        self.assertEqual(port.calls, [("enroll", DOCK_A)])
        self.assertEqual(set(payload), CONFIRM_KEYS)
        self.assertIs(payload["verified"], False)
        self.assertEqual(payload["model"], "Synthetic Dock")
        self.assertFalse(leaks_uuid(payload, DOCK_A))

    def test_the_opt_in_changes_nothing_about_the_one_shot_grant(self):
        """**Opt-in only.** `authorize` is the same act either side of it."""
        _, port, _, facade = build(remembered_grant_enabled=True)
        token = offer(facade)
        facade.acknowledge(token)
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertTrue(payload["requested"])
        self.assertEqual(port.calls, [("authorize", DOCK_A)])

    def test_the_opt_in_does_not_widen_the_set_of_actions(self):
        """**Opt-in only.** It ungates one action; it invents none."""
        for action in ("Enroll", "", None, "trust", "authorise", 1):
            with self.subTest(action=action):
                _, port, _, facade = build(remembered_grant_enabled=True)
                token = offer(facade)
                facade.acknowledge(token)
                payload = facade.confirm(token, consent=True, action=action)
                self.assertFalse(payload["requested"])
                self.assertEqual(payload["code"], ACTION_INVALID)
                self.assertEqual(port.calls, [])


class RequestedIsNotSuccess(unittest.TestCase):
    """A request that was accepted is not a device that is trusted."""

    def test_a_readback_that_cannot_be_taken_leaves_verified_unknown(self):
        observer, _, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        original = observer.scan

        readbacks = iter([original, replace(original, authorized=None)])

        def observe():
            observer.calls += 1
            return next(readbacks, replace(original, authorized=None))

        observer.observe = observe
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertTrue(payload["requested"])
        self.assertIsNone(payload["verified"])

    def test_a_readback_that_still_says_unauthorized_says_so(self):
        _, _, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertTrue(payload["requested"])
        self.assertIs(payload["verified"], False)

    def test_a_readback_that_says_authorized_says_so(self):
        observer, _, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        original = observer.scan
        readbacks = iter([original])

        def observe():
            observer.calls += 1
            return next(readbacks, replace(original, authorized=True))

        observer.observe = observe
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertTrue(payload["requested"])
        self.assertIs(payload["verified"], True)

    def test_a_refused_confirmation_carries_no_verification(self):
        _, _, _, facade = build()
        token = offer(facade)
        payload = facade.confirm(token, consent=False, action="authorize")
        self.assertFalse(payload["requested"])
        self.assertIsNone(payload["verified"])

    def test_an_executor_that_declined_is_reported_as_declined(self):
        _, port, _, facade = build(enrolled=False, code="device_authorization.denied")
        token = offer(facade)
        facade.acknowledge(token)
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertFalse(payload["requested"])
        self.assertEqual(payload["code"], "device_authorization.denied")
        self.assertEqual(port.calls, [("authorize", DOCK_A)])

    def test_the_result_never_claims_success(self):
        _, _, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertNotIn("success", payload)
        self.assertNotIn("authorized", payload)
        self.assertEqual(
            set(payload),
            {
                "schema_version",
                "requested",
                "code",
                "token",
                "verified",
                "vendor",
                "model",
                "already_offered",
                "intentional_disconnect",
                "confirmation_open",
                "generation",
            },
        )
        json.loads(rendered(payload))


class NothingRetries(unittest.TestCase):
    """An action that grants memory access runs when a person presses it."""

    def test_an_executor_that_raises_is_reported_once_and_not_repeated(self):
        _, port, _, facade = build(explode=True)
        token = offer(facade)
        facade.acknowledge(token)
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertFalse(payload["requested"])
        self.assertEqual(payload["code"], UNAVAILABLE)
        self.assertEqual(len(port.calls), 1)

    def test_a_failed_request_leaves_no_live_token_to_press_again(self):
        _, port, _, facade = build(explode=True)
        token = offer(facade)
        facade.acknowledge(token)
        facade.confirm(token, consent=True, action="authorize")
        status = facade.status()
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["token"], "")
        self.assertFalse(status["confirmation_open"])
        self.assertEqual(len(port.calls), 1)

    def test_pressing_confirm_again_never_reaches_the_executor(self):
        _, port, _, facade = build(explode=True)
        token = offer(facade)
        facade.acknowledge(token)
        facade.confirm(token, consent=True, action="authorize")
        again = facade.confirm(token, consent=True, action="authorize")
        self.assertFalse(again["requested"])
        self.assertIn(again["code"], REFUSALS)
        self.assertEqual(len(port.calls), 1)

    def test_a_double_press_of_a_successful_action_runs_once(self):
        _, port, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        first = facade.confirm(token, consent=True, action="authorize")
        second = facade.confirm(token, consent=True, action="authorize")
        self.assertTrue(first["requested"])
        self.assertFalse(second["requested"])
        self.assertEqual(len(port.calls), 1)

    def test_polling_after_an_action_never_re_offers_the_same_attachment(self):
        _, port, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        facade.confirm(token, consent=True, action="authorize")
        for _ in range(3):
            status = facade.status()
            self.assertEqual(status["state"], "unavailable")
            self.assertEqual(status["token"], "")
        self.assertEqual(len(port.calls), 1)

    def test_a_replug_after_a_failure_is_a_fresh_offer(self):
        """The retry is a deliberate physical act, not a poll."""
        observer, port, _, facade = build(explode=True)
        token = offer(facade)
        facade.acknowledge(token)
        facade.confirm(token, consent=True, action="authorize")
        observer.scan = EMPTY
        facade.status()
        observer.scan = Scan()
        status = facade.status()
        self.assertEqual(status["state"], "offered")
        self.assertTrue(status["token"])
        self.assertNotEqual(status["token"], token)
        self.assertEqual(len(port.calls), 1)


class AnUnnamedDeviceIsNeverOffered(unittest.TestCase):
    """The oldest rule in the feature, and the only one about the names.

    "Do not authorize devices you do not trust" is unusable advice when the
    dialog cannot say which device it means, so a reading with no readable
    model is refused before any offer is decided -- and the vendor goes with
    it, because no caller may show half a name.

    What used to leave a device unnamed *as well* was a content filter over the
    product string, and that is gone: it refused the names real docks publish,
    which turned this rule into the failure it exists to prevent -- a named,
    addressable, unenrolled dock that silently never got its prompt.
    """

    def test_a_reading_with_no_model_is_not_offered_however_it_is_labelled(self):
        _, _, _, facade = build(Scan(model="", identity_resolved=True))
        status = facade.status()
        self.assertEqual(status["model"], "")
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["code"], IDENTITY_UNRESOLVED)
        self.assertEqual(status["token"], "")

    def test_a_vendor_without_a_model_is_not_half_a_name(self):
        _, _, _, facade = build(Scan(vendor="Synthetic Vendor", model=""))
        status = facade.status()
        self.assertEqual(status["vendor"], "")
        self.assertEqual(status["state"], "unavailable")

    def test_an_unresolved_identity_blanks_the_name_it_did_publish(self):
        """The reading where dropping the names is not already a no-op.

        Every other case in this file that says `identity_resolved=False` says
        `model=""` in the same breath, so there is nothing left for the rule to
        drop and the case answers the same whether the rule exists or not. The
        reading that tells them apart is the one that publishes a whole name
        *and* an unresolved identity: strings the observer could not tie to a
        device. Shown, they would be a name on a dialog about something else --
        which is the half a name this rule refuses, arriving from the other
        direction to `test_a_vendor_without_a_model_is_not_half_a_name`.
        """
        _, port, _, facade = build(
            Scan(
                identity_resolved=False,
                vendor="Synthetic Vendor",
                model="Synthetic Dock",
            )
        )
        status = facade.status()
        self.assertEqual(status["model"], "")
        self.assertEqual(status["vendor"], "")
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["code"], IDENTITY_UNRESOLVED)
        self.assertEqual(status["token"], "")
        self.assertEqual(port.calls, [])
        json.loads(rendered(status))

    def test_a_model_without_a_vendor_is_a_name(self):
        """Plenty of real hardware publishes no `vendor_name` at all."""
        _, _, _, facade = build(Scan(vendor=""))
        status = facade.status()
        self.assertEqual(status["vendor"], "")
        self.assertEqual(status["model"], "Synthetic Dock")
        self.assertEqual(status["state"], "offered")

    def test_confirming_an_unnamed_device_never_reaches_the_executor(self):
        """The dialog was wrong; the act behind it was worse."""
        observer, port, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        observer.scan = Scan(model="", identity_resolved=True)
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertFalse(payload["requested"])
        self.assertEqual(payload["code"], IDENTITY_UNRESOLVED)
        self.assertEqual(port.calls, [])

    def test_an_ordinary_name_is_still_shown_and_still_offered(self):
        _, _, _, facade = build()
        status = facade.status()
        self.assertEqual(status["state"], "offered")
        self.assertEqual(status["model"], "Synthetic Dock")
        self.assertEqual(status["vendor"], "Synthetic Vendor")

    def test_a_descriptor_that_is_not_a_string_names_nothing(self):
        for value in (None, 17, [1], {"model": "Dock"}):
            with self.subTest(model=repr(value)):
                _, _, _, facade = build(Scan(model=value))
                status = facade.status()
                self.assertEqual(status["model"], "")
                self.assertEqual(status["state"], "unavailable")
                json.loads(rendered(status))


class RealHardwareIsStillOffered(unittest.TestCase):
    """The regression corpus for the filter that was disqualified.

    Every pair below is a real shipping Thunderbolt dock, written the way sysfs
    publishes it: the full legal `vendor_name` beside the full `device_name`.
    The hex-class rule counted twenty or more across each of these four and
    refused the descriptor, which left `identity_resolved` False, which made
    the domain decline with `identity_unresolved` -- so the dock was named,
    addressable and unenrolled, and silently never got its prompt.  The test
    corpus that missed it paired long model strings with short brand nicknames
    ("Kensington"), which is not what the hardware publishes.
    """

    #: vendor_name, device_name.
    HARDWARE = (
        (
            "Dell Technologies",
            "Dell Thunderbolt Dock WD19TBS 180W Docking Station",
        ),
        (
            "Kensington Computer Products Group",
            "SD5780T Thunderbolt 4 Dual 4K Dock",
        ),
        (
            "Plugable Technologies",
            "TBT4-UDZ Thunderbolt 4 Quad Display Docking Stn",
        ),
        ("Razer Inc.", "Razer Thunderbolt 4 Dock Chroma RC21-01690"),
        ("CalDigit, Inc.", "CalDigit TS4 Thunderbolt 4 Dock"),
        ("Sonnet Technologies, Inc.", "Echo 20 Thunderbolt 4 SuperDock"),
    )

    def test_every_one_of_them_is_offered_and_named(self):
        for vendor, model in self.HARDWARE:
            with self.subTest(vendor=vendor, model=model):
                _, _, _, facade = build(Scan(vendor=vendor, model=model))
                status = facade.status()
                self.assertEqual(status["state"], "offered")
                self.assertEqual(status["code"], OFFERED)
                self.assertTrue(status["token"])
                self.assertEqual(status["vendor"], vendor)
                self.assertEqual(status["model"], model)

    def test_every_one_of_them_can_be_confirmed(self):
        """The offer is the point; the act behind it has to work too."""
        for vendor, model in self.HARDWARE:
            with self.subTest(model=model):
                _, port, _, facade = build(Scan(vendor=vendor, model=model))
                token = offer(facade)
                facade.acknowledge(token)
                payload = facade.confirm(token, consent=True, action="authorize")
                self.assertTrue(payload["requested"])
                self.assertEqual(port.calls, [("authorize", DOCK_A)])


class TheResidualIsADeviceAuthoredDisclosure(unittest.TestCase):
    """A device that publishes its own id as its name has it displayed.

    Pinned rather than hidden, because every attempt to prevent it made things
    worse and the next reader needs to find the decision rather than re-take
    it.  The prompt has to name something and this string is the only name the
    device has; a device that writes its id into `device_name` has disclosed it
    itself.  No filter over attacker-controlled text can prevent that -- the
    same id re-encoded is thirteen hex-class characters in base32 and seven in
    base64, and a nibble substitution is none -- and the filters that tried
    refused real hardware instead.

    What Re-Gear owes, and keeps, is the other guarantee: it never copies the
    uuid into a payload itself.  `NoHardwareIdEverLeaves` is that test, and it
    is about a normal device, which is what makes it a claim about this code.
    """

    def test_a_device_named_after_its_own_id_is_named_after_its_own_id(self):
        _, _, _, facade = build(Scan(model=DOCK_A))
        status = facade.status()
        self.assertEqual(status["model"], DOCK_A)
        self.assertEqual(status["state"], "offered")

    def test_it_is_still_only_ever_rendered_safely(self):
        """Sanitizing stays: it is about rendering, not about meaning."""
        _, _, _, facade = build(Scan(model=f"  {DOCK_A}\n\n{DOCK_A}  "))
        status = facade.status()
        self.assertEqual(status["model"], f"{DOCK_A} {DOCK_A}"[:64])
        self.assertEqual(len(status["model"]), 64)

    def test_the_backend_still_never_writes_the_id_anywhere_else(self):
        """The name is the device's disclosure. The token is still opaque."""
        _, _, _, facade = build(Scan(model=DOCK_A))
        status = facade.status()
        self.assertNotIn(squashed(DOCK_A), squashed(status["token"]))
        self.assertNotIn(squashed(DOCK_A), squashed(status["code"]))
        self.assertNotIn(squashed(DOCK_A), squashed(status["vendor"]))


class TheRealObserverEndToEnd(unittest.TestCase):
    """Through the adapter that actually reads sysfs, not a hand-made reading.

    The unit tests above hand the facade a reading the observer never saw. This
    writes the bytes a dock publishes and reads them back through the adapter,
    so the sanitizing the observer does -- control bytes to spaces, runs
    collapsed, the result capped -- is part of what is being tested rather than
    assumed.
    """

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.thunderbolt = root / "thunderbolt"
        self.bolt = root / "bolt"
        self.thunderbolt.mkdir()
        self.bolt.mkdir()
        # A real tree carries a domain and this machine's own host router.
        (self.thunderbolt / "domain0").mkdir()
        self.router("0-0", device_name="Handheld", unique_id=DOCK_B)

    def router(
        self,
        name: str = "0-1",
        *,
        device_name: str,
        unique_id: str = DOCK_A,
        vendor_name: str = "Synthetic Vendor",
        authorized: str = "0",
    ) -> None:
        path = self.thunderbolt / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "authorized").write_text(authorized, encoding="utf-8")
        (path / "unique_id").write_text(unique_id, encoding="utf-8")
        (path / "vendor_name").write_text(vendor_name, encoding="utf-8")
        # Bytes, so a NUL reaches the reader exactly as hardware would send it.
        (path / "device_name").write_bytes(device_name.encode("utf-8"))

    def facade(self) -> DeviceAuthorizationFacade:
        observer = DeviceAuthorizationObserver(self.thunderbolt, self.bolt)
        return DeviceAuthorizationFacade(
            observer, DeviceAuthorizationService(SpyPort())
        )

    def test_an_ordinary_dock_is_offered_end_to_end(self):
        self.router(device_name="Synthetic Dock")
        status = self.facade().status()
        self.assertEqual(status["state"], "offered")
        self.assertEqual(status["model"], "Synthetic Dock")
        self.assertTrue(status["token"])
        self.assertFalse(leaks_uuid(status, DOCK_A))

    def test_a_control_byte_in_the_name_is_rendered_safely_not_refused(self):
        """Sanitizing is a rendering rule, and the dock still gets its prompt."""
        self.router(device_name="Synthetic\x00Dock")
        status = self.facade().status()
        self.assertEqual(status["model"], "Synthetic Dock")
        self.assertEqual(status["state"], "offered")

    def test_a_name_longer_than_the_cap_is_capped_and_still_offered(self):
        self.router(device_name="M" * 200)
        status = self.facade().status()
        self.assertEqual(len(status["model"]), 64)
        self.assertEqual(status["state"], "offered")

    def test_every_answer_stays_clean_for_an_ordinary_dock(self):
        """The guarantee, end to end: this backend copies the id nowhere."""
        self.router(device_name="CalDigit TS4 Thunderbolt 4 Dock")
        facade = self.facade()
        for payload in (
            facade.status(),
            facade.acknowledge("not-a-token"),
            facade.decline("not-a-token"),
            facade.confirm("not-a-token", consent=True, action="authorize"),
        ):
            self.assertFalse(leaks_uuid(payload, DOCK_A), payload)

    def test_the_full_journey_never_names_the_device_by_its_id(self):
        """Offer, acknowledge, confirm, read back -- every payload scanned."""
        self.router(device_name="CalDigit TS4 Thunderbolt 4 Dock")
        facade = self.facade()
        status = facade.status()
        self.assertEqual(status["state"], "offered")
        token = status["token"]
        payloads = [
            status,
            facade.acknowledge(token),
            facade.confirm(token, consent=True, action="authorize"),
            facade.status(),
        ]
        for payload in payloads:
            self.assertFalse(leaks_uuid(payload, DOCK_A), payload)


class TheReadbackHasToBeAboutTheDeviceThatWasActedOn(unittest.TestCase):
    """The reproduced defect: `verified=True` from somebody else's reading."""

    def _readback(self, second: Scan):
        observer, port, service, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        first = observer.scan
        readbacks = iter([first])

        def observe():
            observer.calls += 1
            return next(readbacks, second)

        observer.observe = observe
        return facade.confirm(token, consent=True, action="authorize"), port

    def test_a_reading_of_a_different_device_is_not_evidence(self):
        payload, port = self._readback(
            Scan(uuid=DOCK_B, authorized=True, model="Other Dock")
        )
        self.assertTrue(payload["requested"])
        self.assertIsNone(payload["verified"])
        self.assertEqual(port.calls, [("authorize", DOCK_A)])

    def test_a_reading_that_could_not_be_identified_is_not_evidence(self):
        """The predicate refuses these outright; so must the readback."""
        payload, _ = self._readback(
            Scan(identity_resolved=False, authorized=True, model="")
        )
        self.assertTrue(payload["requested"])
        self.assertIsNone(payload["verified"])

    def test_a_reading_of_the_device_that_was_acted_on_still_counts(self):
        payload, _ = self._readback(Scan(authorized=True))
        self.assertTrue(payload["requested"])
        self.assertIs(payload["verified"], True)


class ThePayloadNeverContradictsItself(unittest.TestCase):
    """A code and the fields beside it have to be able to be true together."""

    def test_an_offer_with_nothing_to_name_is_not_called_already_offered(self):
        _, _, _, facade = build(Scan(uuid=""))
        status = facade.status()
        self.assertFalse(status["already_offered"])
        self.assertEqual(status["code"], IDENTITY_UNRESOLVED)
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["token"], "")

    def test_already_offered_is_only_reported_when_it_is_true(self):
        """Each reading is taken after a prompt was really acknowledged.

        The version this replaces built a fresh facade per case and polled it
        once, and a poll never spends the latch -- so the code it was waiting
        for could not occur, the one assertion it carried sat behind a branch
        nothing ever entered, and five cases asserted nothing at all. The latch
        is spent first, which is the only thing that makes the claim checkable,
        and every case is then asserted whichever way it goes.
        """
        for scan, code, spent in (
            # The same dock, still there: the latch it spent is still its own.
            (Scan(), ALREADY_OFFERED, True),
            # Present and nameless: the attachment stands, so the latch does.
            (Scan(uuid=""), ALREADY_OFFERED, True),
            # A device that publishes its own id is still the same device.
            (Scan(model=f"Dock {DOCK_A}"), ALREADY_OFFERED, True),
            # "I could not look" retires nothing, so it forgets nothing.
            (UNREADABLE, SCAN_UNREADABLE, True),
            # An absence retires the attachment, and the latch dies with it.
            (EMPTY, NO_DEVICE, False),
        ):
            with self.subTest(scan=scan):
                observer, _, service, facade = build()
                token = offer(facade)
                self.assertTrue(facade.acknowledge(token)["accepted"])
                observer.scan = scan
                status = facade.status()
                self.assertEqual(status["code"], code)
                self.assertIs(status["already_offered"], spent)
                # One owner: the payload reports the service's latch rather
                # than a second copy of it kept here.
                self.assertIs(status["already_offered"], service.offered)



class NoPayloadEverContradictsItself(unittest.TestCase):
    """Every field of one payload has to describe the same instant.

    The reproduced defect: a payload was assembled from six separately-locked
    reads of the service -- the assessment, the latch, the generation, the
    token, the disconnect flag, the open confirmation -- so a report or a
    replug landing between two of them produced a dict nothing could make true
    at once.  The one that matters is `state="offered"` with a live token and
    `intentional_disconnect=True`: the prompt raised for a dock Re-Gear had
    just deliberately deauthorized, which is the exact failure the flag exists
    to prevent.

    None of it is visible sequentially, so these race real threads.  The switch
    interval is shortened for the reason the service suite shortens it: with
    the default one the gap between two of the six reads is a handful of
    bytecodes and the window almost never lands inside it.
    """

    def setUp(self):
        interval = sys.getswitchinterval()
        self.addCleanup(sys.setswitchinterval, interval)
        sys.setswitchinterval(1e-6)

    def assertCoherent(self, payload):
        """Everything one payload may not say about itself."""
        self.assertLessEqual(set(payload), STATUS_KEYS | {"accepted"}, payload)
        if payload["state"] == "offered":
            # The three the domain has already answered: it offers only when
            # nothing is disowned and the latch is unspent, and an offer with
            # no token is an offer the player cannot answer.
            self.assertFalse(payload["intentional_disconnect"], payload)
            self.assertFalse(payload["already_offered"], payload)
            self.assertTrue(payload["token"], payload)
            self.assertEqual(payload["code"], OFFERED, payload)
        if payload["token"]:
            self.assertTrue(
                payload["state"] == "offered" or payload["confirmation_open"],
                payload,
            )
        if payload["confirmation_open"]:
            # Acknowledging is what opens one, and acknowledging spends the
            # latch in the same breath.
            self.assertTrue(payload["already_offered"], payload)
        if payload["code"] == INTENTIONAL:
            self.assertTrue(payload["intentional_disconnect"], payload)

    def _race(self, work, workers):
        barrier = threading.Barrier(workers)
        collected: list[dict] = []
        guard = threading.Lock()

        def run(index):
            barrier.wait()
            payloads = work(index)
            with guard:
                collected.extend(payloads)

        threads = [
            threading.Thread(target=run, args=(index,))
            for index in range(workers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        for thread in threads:
            self.assertFalse(thread.is_alive(), "a racing caller never returned")
        return collected

    def test_the_facade_keeps_no_state_of_its_own(self):
        """The cached token had no lock, so the fix was to stop having one.

        It was plain mutable state -- a token and the generation it belonged to
        -- read and written by concurrent RPC calls in front of a service that
        serialises everything under one lock.  Two threads interleaved the
        reset and the store.  The service holds that token already, so this
        layer asks for it instead of remembering it, and there is nothing left
        here for two threads to interleave.

        The three attributes are the two collaborators and the
        remembered-grant opt-in, which is decided once in `__init__` and never
        written again -- so what this pins is not "no attributes" but "nothing
        a call can write".  The snapshot is therefore compared by *identity*
        after a full journey rather than by counting names: an attribute
        rebound during the journey fails here even when it is rebound to an
        equal value, which is exactly what a reintroduced token cache would
        look like.
        """
        _, _, _, facade = build()
        before = dict(vars(facade))
        self.assertEqual(
            set(before), {"_observer", "_service", "_remembered_grant_enabled"}
        )
        token = offer(facade)
        facade.acknowledge(token)
        facade.confirm(token, consent=True, action="authorize")
        facade.status()
        after = vars(facade)
        self.assertEqual(set(after), set(before))
        for name, value in before.items():
            self.assertIs(after[name], value, name)

    def test_a_report_racing_the_pollers_never_produces_an_offer_beside_it(self):
        """The prompt for a dock we deliberately deauthorized."""
        for _ in range(40):
            _, _, _, facade = build()

            def work(index):
                if index == 0:
                    facade.note_intentional_disconnect(True, uuid=DOCK_A)
                    return []
                return [facade.status() for _ in range(15)]

            for payload in self._race(work, 4):
                self.assertCoherent(payload)

    def test_a_report_and_a_clear_racing_the_pollers_stay_coherent(self):
        for _ in range(40):
            _, _, _, facade = build()

            def work(index):
                if index == 0:
                    for _ in range(10):
                        facade.note_intentional_disconnect(True, uuid=DOCK_A)
                        facade.note_intentional_disconnect(False, uuid=DOCK_A)
                    return []
                return [facade.status() for _ in range(15)]

            for payload in self._race(work, 4):
                self.assertCoherent(payload)

    def test_a_swap_mid_poll_never_lends_one_docks_token_to_the_other(self):
        """The reproduced defect this layer's cache produced.

        A status could hand back the replacement dock's token while reporting
        the attachment it replaced.  A token addresses one attachment, so it
        may only ever appear beside the names and the generation of the dock it
        was minted for -- if the same token turns up under two identities or
        two generations, some payload was addressing a device it was not
        describing.
        """
        other = Scan(uuid=DOCK_B, vendor="Other Vendor", model="Other Dock")
        for _ in range(40):
            observer, _, service, facade = build()
            scans = (observer.scan, other)
            counter = {"n": 0}

            def observe():
                counter["n"] += 1
                return scans[counter["n"] % 2]

            observer.observe = observe

            def work(index):
                payloads = []
                for _ in range(15):
                    status = facade.status()
                    payloads.append(status)
                    if index % 2 and status["token"]:
                        payloads.append(facade.acknowledge(status["token"]))
                return payloads

            seen: dict[str, set] = {}
            for payload in self._race(work, 4):
                self.assertCoherent(payload)
                token = payload["token"]
                if not token:
                    continue
                named = (
                    payload["vendor"],
                    payload["model"],
                    payload["generation"],
                )
                seen.setdefault(token, set()).add(named)
            for token, identities in seen.items():
                self.assertEqual(
                    len(identities),
                    1,
                    f"one token addressed {identities!r}",
                )

    #: Four docks, one per polling thread, plus the reading a poll takes when
    #: something is attached and nothing can name it. Synthetic for the reason
    #: `DOCK_A` is, and *named* rather than numbered so that which dock a
    #: payload is about can be read off the only identity that ever leaves this
    #: backend -- its vendor and model -- rather than off a uuid nothing is
    #: allowed to publish.
    DISOWNED = Scan(
        uuid="cccccccc-9999-aaaa-bbbb-cccccccccccc",
        vendor="Disowned Vendor",
        model="Disowned Dock",
    )
    CHURNING = Scan(
        uuid="dddddddd-1111-2222-3333-dddddddddddd",
        vendor="Churning Vendor",
        model="Churning Dock",
    )
    CLEAN = Scan(
        uuid="eeeeeeee-4444-5555-6666-eeeeeeeeeeee",
        vendor="Clean Vendor",
        model="Clean Dock",
    )
    ANSWERED = Scan(
        uuid="ffffffff-7777-8888-9999-ffffffffffff",
        vendor="Answered Vendor",
        model="Answered Dock",
    )
    #: Present, and nothing names it: the poll that marks the held identity
    #: unconfirmed, and the one whose write used to land inside somebody
    #: else's half-built payload.
    NAMELESS = Scan(identity_resolved=False, vendor="", model="", uuid="")

    class PerThreadObserver:
        """A different dock for each calling thread, which is the real case.

        The plugin answers one RPC per thread and the panel polls on a timer,
        so two calls about two docks overlapping is ordinary traffic rather
        than a contrived schedule -- and it is the traffic that made one
        caller's reading answer the other caller's payload.
        """

        def __init__(self, default: Scan) -> None:
            self._local = threading.local()
            self._default = default

        def pin(self, scan: Scan) -> None:
            self._local.scan = scan

        def observe(self) -> Scan:
            return getattr(self._local, "scan", self._default)

    def test_every_payload_describes_exactly_one_attachment(self):
        """Many docks, one bus, and no payload built out of two of them.

        The reproduced defect, and it took two acquisitions of the service's
        lock to produce: `status()` handed its reading in under one and asked
        about it under the next, so between them another thread observed its
        own dock.  Both fields the service answers from the attachment rather
        than from the argument then described that dock: the single
        identity-unconfirmed flag, which whichever thread polled last had
        written, and the disownership that goes into the assessment -- while
        every other input to the very same assessment was this caller's
        reading.  A dock nobody had disowned was reported as disowned, and a
        dock this backend had deauthorized on purpose was reported as clean.

        Everything asserted below is decided before the threads start: the
        disowned dock is disowned for the whole round and the clean docks never
        are, so each payload has exactly one right answer and the test does not
        have to read it back out of the object under test to know what it is.
        """
        for _ in range(25):
            observer = self.PerThreadObserver(self.CLEAN)
            port = SpyPort()
            service = DeviceAuthorizationService(port)
            facade = DeviceAuthorizationFacade(observer, service)
            self.assertTrue(
                facade.note_intentional_disconnect(True, uuid=self.DISOWNED.uuid)
            )

            def poll(scan, rounds=12):
                def run():
                    observer.pin(scan)
                    return [facade.status() for _ in range(rounds)]

                return run

            def churn():
                """A report and a clear, over and over, for one dock only."""
                observer.pin(self.CHURNING)
                for _ in range(12):
                    facade.note_intentional_disconnect(
                        True, uuid=self.CHURNING.uuid
                    )
                    facade.note_intentional_disconnect(
                        False, uuid=self.CHURNING.uuid
                    )
                return []

            def answer():
                """The player, pressing things while the panels poll."""
                observer.pin(self.ANSWERED)
                payloads = []
                for _ in range(6):
                    status = facade.status()
                    payloads.append(status)
                    if not status["token"]:
                        continue
                    payloads.append(facade.acknowledge(status["token"]))
                    payloads.append(
                        facade.confirm(
                            status["token"], consent=True, action="authorize"
                        )
                    )
                return payloads

            workers = [
                poll(self.DISOWNED),
                poll(self.DISOWNED),
                poll(self.CHURNING),
                poll(self.CLEAN),
                poll(self.CLEAN),
                poll(self.NAMELESS),
                churn,
                answer,
            ]
            collected = self._race(lambda index: workers[index](), len(workers))
            self.assertTrue(collected)
            addressed: dict[str, set] = {}
            for payload in collected:
                acting = "requested" in payload
                if not acting:
                    self.assertCoherent(payload)
                self._assertOneDock(payload, acting)
                token = payload["token"]
                if not token or not payload["model"]:
                    # A reading that named nothing is deliberately answered
                    # with the attachment's own token -- a dialog on screen
                    # must not be stranded by one unreadable poll -- so it
                    # carries a token beside no name at all. That is the rule,
                    # not a payload addressing a device it is not describing.
                    continue
                if acting and payload["code"] in REFUSALS:
                    # A refusal echoes the token back to say which prompt it
                    # answers. The attachment that token addresses is exactly
                    # the one this call could not bind to, so it makes no claim
                    # about the state printed beside it.
                    continue
                addressed.setdefault(token, set()).add(
                    (payload["vendor"], payload["model"], payload["generation"])
                )
            for token, identities in addressed.items():
                self.assertEqual(
                    len(identities),
                    1,
                    f"one token addressed {identities!r}",
                )

    def _assertOneDock(self, payload, acting):
        """Which dock a payload is about, and what it may say about it."""
        model = payload["model"]
        if model == self.DISOWNED.model:
            # Disowned before the race and never cleared, so every field is
            # known: the domain refuses ahead of any fact about the device,
            # there is nothing to mint, and nothing here ever answers for it.
            self.assertTrue(payload["intentional_disconnect"], payload)
            if not acting:
                self.assertEqual(payload["state"], "unavailable", payload)
                self.assertEqual(payload["code"], INTENTIONAL, payload)
                self.assertEqual(payload["token"], "", payload)
                self.assertFalse(payload["already_offered"], payload)
                self.assertFalse(payload["confirmation_open"], payload)
        elif model in (self.CLEAN.model, self.ANSWERED.model):
            # Never disowned by anybody. Reporting one of these as disowned is
            # the flag having been answered from another thread's dock.
            self.assertFalse(payload["intentional_disconnect"], payload)
            self.assertNotEqual(payload["code"], INTENTIONAL, payload)
        elif not model and not acting:
            # Present and nameless. The guard this reading writes is its own,
            # so the record of the dock still held answers for nobody.
            self.assertFalse(payload["intentional_disconnect"], payload)
            self.assertEqual(payload["code"], IDENTITY_UNRESOLVED, payload)
            self.assertEqual(payload["vendor"], "", payload)
        if not acting and model and payload["state"] != "offered":
            # For a status payload about a present, named dock, the code and
            # the flag are one answer: the domain refuses under this code
            # exactly when the flag is set, and both came out of one lock.
            self.assertIs(
                payload["intentional_disconnect"],
                payload["code"] == INTENTIONAL,
                payload,
            )

    def test_confirming_while_the_pollers_run_leaves_every_payload_coherent(self):
        for _ in range(30):
            _, port, _, facade = build()
            token = offer(facade)
            facade.acknowledge(token)

            def work(index):
                if index == 0:
                    return [facade.confirm(token, consent=True, action="authorize")]
                if index == 1:
                    facade.note_intentional_disconnect(True, uuid=DOCK_A)
                    return []
                return [facade.status() for _ in range(15)]

            payloads = self._race(work, 4)
            for payload in payloads:
                if "requested" in payload:
                    # A confirm payload answers a different question; what it
                    # may not do is report a refusal for a disownership beside
                    # a flag that says there was none.
                    if payload["code"] == INTENTIONAL:
                        self.assertTrue(payload["intentional_disconnect"])
                    continue
                self.assertCoherent(payload)
            self.assertLessEqual(len(port.calls), 1)


class TheConfirmPayloadNamesTheDeviceThatWasActedOn(unittest.TestCase):
    """`confirm` observes twice. Only one of them is the device it acted on.

    The reproduced defect: the second observation was assigned back over the
    local reading, so every identity field in the payload described whatever
    was on the bus *after* the act.  Swap the dock in between and the payload
    reported `requested=True` for dock A carrying dock B's name -- and `vendor`
    and `model` are the only device identity that ever leaves this backend, so
    that is the payload naming the wrong device as having just been granted
    direct access to system memory.

    The tell was already there: `verified` was correctly `None` in exactly this
    case.  This layer knew it could not prove the readback described the acted
    device, and then labelled the outcome with it anyway.
    """

    def swapped(self, replacement: Scan, **build_kwargs):
        """Act on dock A, then let the readback see something else entirely."""
        observer, port, service, facade = build(**build_kwargs)
        token = offer(facade)
        facade.acknowledge(token)
        acted = observer.scan
        readings = iter([acted])

        def observe():
            observer.calls += 1
            return next(readings, replacement)

        observer.observe = observe
        acted_generation = service.generation
        payload = facade.confirm(token, consent=True, action="authorize")
        return payload, port, service, token, acted_generation

    #: The dock that turns up for the readback. Named so that any leak of it
    #: into a payload is unmistakable rather than a plausible product string.
    INTERLOPER = Scan(
        uuid=DOCK_B,
        vendor="Interloper Vendor",
        model="Interloper Dock",
        authorized=True,
    )

    def test_the_payload_names_the_acted_device(self):
        payload, port, _, _, _ = self.swapped(self.INTERLOPER)
        self.assertTrue(payload["requested"])
        self.assertEqual(port.calls, [("authorize", DOCK_A)])
        self.assertEqual(payload["vendor"], "Synthetic Vendor")
        self.assertEqual(payload["model"], "Synthetic Dock")

    def test_the_device_that_replaced_it_is_named_nowhere(self):
        payload, _, _, _, _ = self.swapped(self.INTERLOPER)
        self.assertNotIn("Interloper", rendered(payload))
        self.assertFalse(leaks_uuid(payload, DOCK_B))

    def test_the_token_is_the_one_the_act_was_bound_to(self):
        payload, _, _, token, _ = self.swapped(self.INTERLOPER)
        self.assertEqual(payload["token"], token)

    def test_the_readback_contributes_verified_and_nothing_else(self):
        """It read `authorized=True`, and it is not evidence about dock A."""
        payload, _, _, _, _ = self.swapped(self.INTERLOPER)
        self.assertTrue(payload["requested"])
        self.assertIsNone(payload["verified"])

    def test_the_generation_is_the_acted_attachment_s(self):
        payload, _, service, _, acted_generation = self.swapped(self.INTERLOPER)
        self.assertEqual(payload["generation"], acted_generation)
        # And the swap really did retire it underneath, which is what made the
        # rebound reading report the replacement's generation instead.
        self.assertGreater(service.generation, acted_generation)

    def test_already_offered_describes_the_attachment_that_was_offered(self):
        """The readback's retire drops the latch, so this used to read False.

        A payload that says an offer was just confirmed and that no offer was
        ever made is describing two different docks in one dict.
        """
        payload, _, service, _, _ = self.swapped(self.INTERLOPER)
        self.assertTrue(payload["already_offered"])
        self.assertFalse(service.offered)

    def test_confirmation_open_describes_the_acted_attachment(self):
        payload, _, _, _, _ = self.swapped(self.INTERLOPER)
        self.assertFalse(payload["confirmation_open"])

    def test_a_disownership_that_arrives_with_the_replacement_is_not_charged(self):
        """The replacement is a dock we disowned. The acted one was not.

        Read after the readback, the service reports the disownership of the
        device now on the bus -- so the payload said `requested=True` and
        `intentional_disconnect=True` about an act that was never refused for
        one, and pointed the blame at the wrong dock while doing it.
        """
        observer, port, service, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        self.assertTrue(facade.note_intentional_disconnect(True, uuid=DOCK_B))
        acted = observer.scan
        readings = iter([acted])

        def observe():
            observer.calls += 1
            return next(readings, self.INTERLOPER)

        observer.observe = observe
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertTrue(payload["requested"])
        self.assertFalse(payload["intentional_disconnect"])
        self.assertEqual(port.calls, [("authorize", DOCK_A)])
        # The service is not wrong -- the disowned dock really is attached now.
        self.assertTrue(service.intentional_disconnect)

    def test_a_readback_that_could_not_be_taken_still_names_the_acted_device(self):
        payload, _, _, _, acted_generation = self.swapped(UNREADABLE)
        self.assertTrue(payload["requested"])
        self.assertIsNone(payload["verified"])
        self.assertEqual(payload["vendor"], "Synthetic Vendor")
        self.assertEqual(payload["model"], "Synthetic Dock")
        self.assertEqual(payload["generation"], acted_generation)

    def test_a_readback_of_the_same_device_verifies_and_changes_no_name(self):
        payload, _, _, _, acted_generation = self.swapped(Scan(authorized=True))
        self.assertTrue(payload["requested"])
        self.assertIs(payload["verified"], True)
        self.assertEqual(payload["model"], "Synthetic Dock")
        self.assertEqual(payload["generation"], acted_generation)

    def test_a_refused_confirmation_still_names_the_device_it_was_refused_for(self):
        _, _, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        payload = facade.confirm(token, consent=False, action="authorize")
        self.assertFalse(payload["requested"])
        self.assertEqual(payload["code"], CONFIRMATION_REQUIRED)
        self.assertEqual(payload["model"], "Synthetic Dock")
        self.assertEqual(payload["vendor"], "Synthetic Vendor")


if __name__ == "__main__":
    unittest.main()


class RememberedTrustReadbackProvesBothFacts(unittest.TestCase):
    """`enroll` promised the device would be remembered; the payload may say
    `verified: true` only when the same attachment reads back both trusted
    and stored."""

    def confirm_enroll_with_readback(self, **readback):
        observer, port, _, facade = build(remembered_grant_enabled=True)
        token = offer(facade)
        facade.acknowledge(token)
        original = observer.scan
        readbacks = iter([original])

        def observe():
            observer.calls += 1
            return next(readbacks, replace(original, **readback))

        observer.observe = observe
        payload = facade.confirm(token, consent=True, action="enroll")
        self.assertTrue(payload["requested"])
        self.assertEqual(port.calls, [("enroll", original.uuid)])
        return payload

    def test_authorized_and_enrolled_is_verified(self):
        payload = self.confirm_enroll_with_readback(authorized=True, enrolled=True)
        self.assertIs(payload["verified"], True)

    def test_authorized_but_not_enrolled_is_not_verified(self):
        """The reproduced defect: this used to report `verified: true`."""
        payload = self.confirm_enroll_with_readback(authorized=True, enrolled=False)
        self.assertIs(payload["verified"], False)

    def test_authorized_with_unreadable_enrollment_is_unknown(self):
        payload = self.confirm_enroll_with_readback(authorized=True, enrolled=None)
        self.assertIsNone(payload["verified"])

    def test_not_authorized_is_not_verified(self):
        payload = self.confirm_enroll_with_readback(authorized=False, enrolled=True)
        self.assertIs(payload["verified"], False)

    def test_authorize_once_is_unaffected_by_enrollment(self):
        observer, _, _, facade = build()
        token = offer(facade)
        facade.acknowledge(token)
        original = observer.scan
        readbacks = iter([original])

        def observe():
            observer.calls += 1
            return next(readbacks, replace(original, authorized=True, enrolled=False))

        observer.observe = observe
        payload = facade.confirm(token, consent=True, action="authorize")
        self.assertIs(payload["verified"], True)
