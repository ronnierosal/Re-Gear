"""The one surface Game Mode talks to about trusting a dock.

The plugin holds a single one of these for its lifetime and root's `main.py`
does nothing but forward to it, because every rule that keeps this feature
honest is a rule about *ordering* -- observe, then decide, then act, then read
back -- and an RPC layer that reaches past this object gets to skip steps.

**Polling must not consume what it is polling.**  The panel re-reads state on a
timer, so `status()` is a pure read: it observes, mints this attachment's
opaque token if there is something to offer, and returns.  It never spends the
latch.  A read that did would make the prompt disappear on the second poll and
look, from the player's side, exactly like a dock that stopped working.  The
latch is spent by `acknowledge()` -- by the prompt having actually been put in
front of someone -- and by nothing else.  For the same reason an acknowledged
prompt keeps reporting the *same* token while it is still live: a dialog on
screen survives being re-read.

**Identity only ever travels outward.**  The caller supplies an action, the
attachment-scoped token, and a literal consent.  It cannot name a device,
because it is not allowed to be right about which one is attached: a dialog can
sit on screen across an unplug, a replacement, or a wake.  So `confirm()`
re-observes here and binds the freshly read identity and generation itself.
The confirmation the player pressed is checked against the device in front of
us, never against the device the panel remembers.

**The payload names the device that was acted on.**  `confirm()` observes
twice -- once to bind and act, once to read back -- and those are two different
devices whenever a dock is swapped in between.  This used to rebind its one
local reading to the second observation and then emit *that* reading's vendor
and model, so a payload could report `requested=True` for dock A under dock
B's name.  `vendor` and `model` are the only device identity that ever leaves
this backend, so that named the wrong device as having just been granted
direct memory access.  The identity, the offer fields and the generation now
all come from the observation the token was bound to and the executor acted
on; the readback feeds exactly one field, `verified`, and nothing else.  The
tell that the old shape was wrong was already in the payload: `verified` was
correctly `None` in precisely that case -- this layer knew it could not prove
the readback described the acted device, and labelled the outcome with it
anyway.

**The one guarantee about the hardware id, and the residual beside it.**  The
guarantee is this: **Re-Gear never puts the uuid into a payload itself.**  The
id is read, handed to the service and handed to the executor, which needs it to
name the device to `boltd`; it reaches no return value, no log line and no
exception, and a device is addressed outward by the opaque attachment token
instead.  That is enforceable because it is a rule about this code, and a test
asserts it for a normal device -- one whose product name is not its own id.

The residual, stated plainly because three earlier passes stated it wrongly: **a
device that publishes its own identifier as its product name will have that
string displayed.**  It is the only name the device has and the prompt has to
name something.  That is a device-authored disclosure rather than a Re-Gear
diagnostic leak, and no filter over attacker-controlled text can prevent it.
The content filter that used to sit here tried and is gone: it was too weak --
the same id in base32 or base64, or one nibble substitution, walked through a
hex-class count untouched -- and it was too strong in the way that actually
costs a player something.  Full vendor and product strings that real docks
publish, Dell's and Kensington's and Plugable's and Razer's among them, carried
enough hex-class characters to be refused, and a refused name left the identity
unresolved, so a named, addressable, unenrolled dock silently never got its
prompt.  That is precisely the failure this feature exists to prevent.  What is
left is rendering: whitespace collapsed and the label capped, so a descriptor
cannot push a dialog off screen.

**An unnamed device is never offered.**  The oldest rule in this feature --
"do not authorize devices you do not trust" is unusable advice when the dialog
cannot say which device it means.  A reading with no readable model leaves the
identity unresolved however confidently it was reported, and an unresolved
identity is refused under the domain's own code, before any offer is decided.
The vendor goes with it, because no caller may show half a name.

**`requested` is not success.**  The executor accepting a request says the
request was taken.  Whether the device became trusted is a separate reading,
taken once afterwards, and reported as a tri-state `verified` that stays `None`
when nothing could be read.  Nothing here promotes one to the other -- and the
readback has to be a reading *of the device that was acted on*.  It is handed
the identity and generation it was taken in, and an unidentifiable one is
handed no identity at all, because a reading the feature's own predicate
refuses as `identity_unresolved` is not evidence that anything was authorized.

**One flag, one owner.**  The deliberate-disconnect report belongs to the
service, which keys it to the device it names; this layer keeps no copy of it
and adds no rule of its own.  It used to mirror the flag from the caller's
argument even when the service had rejected the report -- which is how a
payload came to say `state="offered"` and `intentional_disconnect=True` in the
same breath.  What the payload reports is the service's flag, read from the
service, and what this returns is the service's decision.  The named limitation
on that record -- it is in-memory, so a plugin restart forgets it -- is written
out where the record lives, in the service module.

**One payload, one instant.**  This layer holds no state at all.  It used to
keep a cached token beside a cached generation, plain attributes read and
written by concurrent RPC calls with no lock of their own, in front of a
service that serialises everything under one: two threads could interleave the
reset and the store, and a `status()` could hand back the replacement dock's
token while reporting the attachment it replaced.  The cache is gone, and so is
the reason for it -- the service holds that token and can simply be asked.

For the same reason a payload is built from exactly one call.  Assembling one
from six separately-locked reads -- the assessment, the latch, the generation,
the token, the flag, the open confirmation -- samples six different instants,
and a report landing between two of them produced the self-contradiction this
docstring used to claim was fixed: `state="offered"` with a live token *and*
`intentional_disconnect=True`, a prompt raised for a dock Re-Gear had
deliberately deauthorized.

**And the reading is one of those instants.**  One call was still two
acquisitions, because handing the reading to the service and asking the service
about that reading were separate ones: `observe_attachment` wrote the identity
the service holds, and the snapshot that followed read it back.  In between,
another RPC thread observed *its* dock -- and the two fields the service
answers from the attachment rather than from the argument, the disownership and
the guard saying whether any reading has confirmed the held identity, then
described that thread's dock inside this thread's payload.  Two panels, two
docks, one answer each, and both of them somebody else's.

So the reading goes in with the question.  `observe_and_snapshot` observes,
assesses, mints and reads every remaining field without releasing the lock
once; `observe_and_answer` is the same with the player's answer in the middle,
because an acknowledgement returns a payload too; and `confirm` carries the
state that belongs beside its outcome in the outcome itself.  Every payload
below is built from one such return value and from the reading it was taken
for, and from no second call to the service.  `confirm()`'s state is still read
before the readback, because the readback's observation can retire the
attachment underneath it; what changed is that it is read in the acquisition
that acted rather than in a third one a poll could land inside.

**No retries.**  A request that failed is reported once and leaves no live
token to press again, so neither the panel nor a poll can quietly re-run an
action that grants a device direct access to system memory.  The player
re-plugs, which is a deliberate act, and gets a fresh offer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only; never imported at runtime
    from ..application.device_authorization import (
        DeviceAuthorizationService,
        DeviceAuthorizationSnapshot,
    )


#: The domain codes this layer names on its own. Everything else it reports is
#: whatever the predicate said, passed through unedited.
_IDENTITY_UNRESOLVED = "device_authorization.identity_unresolved"
_INTENTIONAL_DISCONNECT = "device_authorization.intentional_disconnect"
#: Asked for a grant this facade is not permitted to make. Not a failure of
#: the device or the player: the remembered grant simply is not on offer
#: here, and saying so is better than silently performing the other one.
_REMEMBERED_GRANT_NOT_OFFERED = "device_authorization.remembered_grant_not_offered"

#: The same cap the observer sanitizes to. A panel label is not a place for a
#: device-supplied string of unbounded length.
_TEXT_CAP = 64


class AttachmentObserver(Protocol):
    """The read-only half: whatever can answer `observe()` about the bus."""

    def observe(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class _Reading:
    """One observation, normalized to the exact types the predicate expects.

    `uuid` is internal to this module: it is handed to the service and to the
    executor, and it never reaches a payload.  It survives an unresolved
    identity, because the attachment still has to be told apart from the next
    one; what an unresolved identity costs is the *names*, and the offer.
    """

    present: bool | None
    identity_resolved: bool
    authorized: bool | None
    enrolled: bool | None
    vendor: str
    model: str
    uuid: str


#: A scan that could not be taken at all. `present=None` is deliberately not
#: `False`: "I could not look" is not "nothing is there", and only the second
#: one is allowed to rearm anything.
_UNREADABLE = _Reading(None, False, None, None, "", "", "")


def _tri(value: object) -> bool | None:
    """Exactly `True`, exactly `False`, or unknown.

    Anything else -- a truthy string, a stray int -- is a reading nobody should
    act on, so it becomes unknown rather than being coerced into a decision.
    """
    if value is True:
        return True
    if value is False:
        return False
    return None


def _text(value: object) -> str:
    """A descriptor as it arrived, or "" when it is not a string at all."""
    return value if isinstance(value, str) else ""


def _capped(value: str) -> str:
    """A device-supplied label made safe to render, and nothing more.

    Control characters and non-ASCII bytes become spaces rather than vanishing,
    so two words separated by one stay two words; runs of whitespace collapse;
    the result is capped and re-stripped, because a cut made mid-run would
    otherwise leave a trailing space.  That keeps a descriptor from carrying a
    terminal escape into a log or pushing a dialog off screen.

    Rendering, and only rendering: it judges nothing about what the string
    says.  It is the observer's rule applied again at the boundary the payload
    actually leaves through, which costs one pass over a short string and means
    the claim in this docstring is true of every reading, not only of the ones
    that came through the adapter that sanitizes.
    """
    printable = "".join(
        character if " " <= character <= "~" else " " for character in value
    )
    return " ".join(printable.split())[:_TEXT_CAP].strip()


def _token_text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _read(observed: Any) -> _Reading:
    raw_uuid = getattr(observed, "uuid", "")
    uuid = raw_uuid if isinstance(raw_uuid, str) else ""
    vendor = _capped(_text(getattr(observed, "vendor", "")))
    model = _capped(_text(getattr(observed, "model", "")))
    # A device with no readable model is unnamed however confidently the
    # observer reported an identity, and an unnamed device is never offered.
    # The vendor goes with it for the reason the observer drops it too: no
    # caller may show half a name.
    identity_resolved = (
        getattr(observed, "identity_resolved", False) is True and bool(model)
    )
    if not identity_resolved:
        vendor = ""
        model = ""
    return _Reading(
        present=_tri(getattr(observed, "present", None)),
        identity_resolved=identity_resolved,
        authorized=_tri(getattr(observed, "authorized", None)),
        enrolled=_tri(getattr(observed, "enrolled", None)),
        vendor=vendor,
        model=model,
        uuid=uuid,
    )


class DeviceAuthorizationFacade:
    """Compose the read-only observer with the latch, for the plugin's life."""

    def __init__(
        self,
        observer: AttachmentObserver,
        service: DeviceAuthorizationService,
        *,
        remembered_grant_enabled: bool = False,
    ) -> None:
        self._observer = observer
        self._service = service
        #: Whether the remembered grant (`enroll`) may be asked for at all.
        #: Off by default, and production wiring does not turn it on: the
        #: approved scope is a one-shot authorization, and a remembered grant
        #: is a different promise to the player. Keeping it a constructor
        #: argument rather than a comment is what makes "not exposed" a
        #: property of the object instead of a habit -- a caller that sends the
        #: wrong action string gets a refusal, not a stored DMA grant.
        self._remembered_grant_enabled = remembered_grant_enabled is True
        # No state of its own, deliberately. Anything cached here is read and
        # written by concurrent RPC calls in front of a service that holds one
        # lock, and the cache this replaces could be stamped with one
        # generation while holding another generation's token.

    # -- reads ---------------------------------------------------------------

    def status(self) -> dict:
        """Observe, and say what there is to offer. Spends nothing."""
        reading = self._read()
        return self._payload(
            reading,
            self._service.observe_and_snapshot(
                present=reading.present,
                identity_resolved=reading.identity_resolved,
                authorized=reading.authorized,
                already_enrolled=reading.enrolled,
                uuid=reading.uuid,
            ),
        )

    # -- the player's answers ------------------------------------------------

    def acknowledge(self, token: str) -> dict:
        """Spend this attachment's one prompt, because it was shown.

        Observed first so the latch is spent against the device that is
        actually there: a token for a dock that has since gone away resolves to
        nothing, rather than marking a fresh attachment as already asked.
        """
        return self._answer(token, accept=True)

    def decline(self, token: str) -> dict:
        """Take "not now" for an answer, for this attachment only.

        No blacklist: the latch dies with the attachment, so unplugging and
        plugging back in asks again. Someone who changed their mind should not
        have to find a settings screen to say so.
        """
        return self._answer(token, accept=False)

    def confirm(self, token: str, *, consent: bool, action: str) -> dict:
        """Act on an explicit yes, against a device observed just now.

        The caller gets no say in which device this is. `action` picks between
        remembering the device and trusting it for this session; `consent` must
        be the literal `True`.

        Two observations happen here and they are kept apart on purpose.  The
        first one is the device: it binds the token, it is what the executor is
        run against, and it is what every identity and offer field below is
        built from.  The second is the readback, and it buys exactly one fact
        -- `verified` -- because between the two the dock can be swapped, and a
        payload that took its name from the second one announced a memory-access
        grant under the wrong device's name.
        """
        if action == "enroll" and not self._remembered_grant_enabled:
            # Refused before the executor is reachable, and before anything is
            # spent: the token stays live so the player can still be asked the
            # question this facade IS allowed to ask. The remembered grant is
            # retained in the port and the runner, and is simply not on offer
            # from here -- so a caller that sends the wrong action string gets
            # a refusal rather than a stored grant of direct memory access.
            refused = self._read()
            state = self._service.observe_and_snapshot(
                present=refused.present,
                identity_resolved=refused.identity_resolved,
                authorized=refused.authorized,
                already_enrolled=refused.enrolled,
                uuid=refused.uuid,
            )
            return {
                "requested": False,
                "code": _REMEMBERED_GRANT_NOT_OFFERED,
                # The service's token, never the caller's argument. Every other
                # confirm path reports a token the service minted or "", and
                # this refusal must not be the one place an unvalidated,
                # uncapped caller string is reflected back into a payload.
                # Reporting the live one is also the more useful answer: the
                # prompt was not spent, so this is still the handle to use.
                "token": state.token,
                "verified": None,
                "vendor": refused.vendor,
                "model": refused.model,
                "already_offered": state.already_offered,
                "intentional_disconnect": self._disconnect(state.code, state),
                "confirmation_open": state.confirmation_open,
                "generation": state.generation,
            }
        acted = self._observe()
        outcome = self._service.confirm(
            token,
            consent=consent,
            action=action,
            device_present=acted.present,
            identity_resolved=acted.identity_resolved,
            authorized=acted.authorized,
            already_enrolled=acted.enrolled,
            uuid=acted.uuid,
            generation=int(self._service.generation),
        )
        requested = outcome.requested is True
        code = str(outcome.code)
        spent = _token_text(outcome.token) or _token_text(token)
        # The state that belongs beside the outcome, and it arrives *with* the
        # outcome. Taken before the readback, because the readback's own
        # `observe_attachment` retires the attachment the moment it sees a
        # different device, which bumps the generation, drops the latch and
        # closes the confirmation -- so these four fields, read afterwards,
        # described the dock that replaced the one this call just acted on. And
        # taken inside the acquisition that acted, because a snapshot asked for
        # here is a third one: a poll landing between the act and it retires
        # the attachment just the same, and the payload then reported
        # `requested=True` with this dock's token and names beside the next
        # dock's generation and spent latch.
        snapshot = outcome.state
        payload = {
            "requested": requested,
            "code": code,
            "token": _token_text(outcome.token),
            "verified": None,
            "vendor": acted.vendor,
            "model": acted.model,
            "already_offered": snapshot.already_offered,
            "intentional_disconnect": self._disconnect(code, snapshot),
            "confirmation_open": snapshot.confirmation_open,
            "generation": snapshot.generation,
        }
        if requested:
            # Exactly one readback, and only to learn what actually happened. A
            # request that was merely accepted is not a device that is trusted,
            # and re-running the action is never the answer here.
            readback = self._observe()
            payload["verified"] = _tri(
                self._service.record_verification(
                    spent,
                    authorized=readback.authorized,
                    # A reading that could not resolve an identity names no
                    # device, so it is offered none: the service answers
                    # "nobody could look" rather than crediting it to the dock
                    # that was just acted on.
                    uuid=readback.uuid if readback.identity_resolved else "",
                    # The generation the *readback* was taken in, which is not
                    # the acted one once a swap has retired the attachment.
                    # The service compares it against the generation the spent
                    # token was bound to, and that mismatch is the refusal.
                    generation=int(self._service.generation),
                )
            )
        return payload

    # -- reports from elsewhere in the backend -------------------------------

    def note_intentional_disconnect(self, active: bool, *, uuid: str) -> bool:
        """Re-Gear deliberately deauthorized a dock that is still cabled.

        The report names the **device**, and nothing else.  It used to carry
        the generation it was observed in, which could not be filed at all:
        the deauthorization itself makes the dock read absent, that absent poll
        retires the attachment and bumps the generation, so the owning layer --
        holding the number it read while the dock was still there -- always
        arrived one poll late and was refused every time.  The flag was never
        set, the dock re-enumerated on wake as first-time trust, and a full
        confirmation ran the executor.

        Naming the device instead cannot go stale: it does not matter whether
        that dock is the attached one, or whether anything is attached at all.
        The service does the whole thing under its one lock, so there is
        nothing to read first and no window between reading and filing.

        Returns the service's decision, not this layer's opinion of the
        arguments.  Every rule about what a report may be -- a non-empty `uuid`,
        an `active` that is exactly `True` or exactly `False` -- belongs to the
        service that holds the flag, and is asked rather than re-implemented
        here: two copies of one rule is how a payload came to report a
        disconnect the service had refused to record.
        """
        return self._service.note_intentional_disconnect(active, uuid=uuid) is True

    # -- internals -----------------------------------------------------------

    def _read(self) -> _Reading:
        """Take one reading, and nothing else.

        The observer touches the filesystem, so it is allowed to fail; failing
        reads as an unreadable scan, which changes nothing. An RPC surface that
        raised here would turn a permissions error into a broken panel.

        It hands the reading to nobody: a reading that is about to become a
        payload travels into the service *with* the question, so that observing
        it and answering about it are one acquisition.
        """
        try:
            observed = self._observer.observe()
        except Exception:
            observed = None
        return _UNREADABLE if observed is None else _read(observed)

    def _observe(self) -> _Reading:
        """Take one reading and hand it to the latch, producing no payload.

        What is left of the old pairing, and the one place it is still right:
        `confirm()`'s two observations. Neither of them is answered by a
        snapshot -- the first binds the act, the second buys `verified` -- so
        there is no payload here whose fields could be split across the two
        acquisitions.
        """
        reading = self._read()
        self._service.observe_attachment(present=reading.present, uuid=reading.uuid)
        return reading

    def _answer(self, token: str, *, accept: bool) -> dict:
        """Observe, answer, and report -- one reading, one acquisition.

        The reading travels in with the answer, so the latch this payload
        reports is the one this answer spent, on the device this reading named.
        """
        reading = self._read()
        answer = self._service.observe_and_answer(
            token,
            accept=accept,
            present=reading.present,
            identity_resolved=reading.identity_resolved,
            authorized=reading.authorized,
            already_enrolled=reading.enrolled,
            uuid=reading.uuid,
        )
        payload = self._payload(reading, answer.state)
        payload["accepted"] = answer.accepted is True
        return payload

    def _payload(
        self, reading: _Reading, snapshot: DeviceAuthorizationSnapshot
    ) -> dict:
        """One reading and one snapshot, and nothing read a second time.

        Every field below comes from the same instant, so the payload cannot
        disagree with itself: the domain cannot say `offered` while the flag
        beside it says this dock was deliberately deauthorized, because the
        assessment was made from that same flag under that same lock -- and the
        reading those names come from is the reading that same lock was holding
        when it answered.
        """
        offered = snapshot.offered
        code = snapshot.code
        if offered and not snapshot.token:
            # A reading the service cannot mint against: it claimed an identity
            # and named no uuid, or it named one that is no longer the attached
            # device. Either way this reading cannot be tied to the dock in
            # front of us, which is the domain's own refusal. There is no
            # second reason to name here -- a spent generation mints no token,
            # but it spent the latch in the same act, so the domain refused the
            # offer before this point and `offered` is already False.
            offered = False
            code = _IDENTITY_UNRESOLVED
        return {
            "state": "offered" if offered else "unavailable",
            "code": code,
            "token": snapshot.token,
            "vendor": reading.vendor,
            "model": reading.model,
            "already_offered": snapshot.already_offered,
            "intentional_disconnect": self._disconnect(code, snapshot),
            "confirmation_open": snapshot.confirmation_open,
            "generation": snapshot.generation,
        }

    def _disconnect(self, code: str, snapshot: DeviceAuthorizationSnapshot) -> bool:
        """Whether a dock we disowned is the answer, as the service holds it.

        The snapshot is the only source, on every path. A code-based override
        used to sit above this line, on the theory that `confirm()`'s code
        comes from the act rather than from the snapshot; it never once
        changed the answer. On the `_payload`/`_answer` path the code and
        `snapshot.intentional_disconnect` are both derived from the same
        `disowned` reading inside one `_snapshot_locked`, and on the confirm
        path the domain cannot emit that code unless the snapshot beside it
        already agrees. So there was no instant at which the two could
        disagree, and the override only made it look as though there were.
        """
        return snapshot.intentional_disconnect
