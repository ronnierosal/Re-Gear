"""Offer to trust a new dock once, and act on it only when the player says yes.

Holds the three things the pure decision deliberately does not: the latch that
keeps one attachment to one prompt, the identity that binds a confirmation to
one device, and the call to `boltd`.

**The prompt is the authorization.**  Nothing here acts on its own, and the
confirmation is checked by identity rather than truthiness -- `"yes"`, `1` and
a stray dict are all truthy and none of them are a player pressing a button.
That mirrors the guard on `execute_automatic`, for the same reason: this grants
a device direct access to system memory, and on this profile
`iommu_dma_protection` reads `0`, so nothing stands behind it.

**Nothing is minted for a device this layer has not seen.**  A token addresses
an *observed* attachment, so `candidate_token` refuses any UUID that is not the
one the last reading named.  Minting on the caller's word let two things
through that should never have been possible: `boltd` driven against a router
the read-only observation layer never saw, and a confirmation completed at
generation 0 -- before the first real scan -- whose scan then bumped the
generation, cleared the spent marker with it, and offered a second enrolment
for a dock nobody had unplugged.  `confirm` checks the same way: the identity
it accepts is the one that was *observed*, not the one the token happens to
remember about itself.

**Re-checked at the moment of acting, and proven to be about the same dock.**
A dialog can sit on screen while the dock is unplugged, replaced, or trusted by
something else, so the caller's fresh reading is assessed again immediately
before acting.  That re-check used to be worth less than it looked: fresh
booleans carry no identity, so a perfectly true reading *of a different device*
still authorized the cached one.  `confirm` therefore takes the attachment
generation and the observed UUID as well, and refuses with `attachment_changed`
unless both match the attachment that was observed and the token minted for it.
The caller has to prove its reading is about this dock; it is no longer allowed
to assume it.

**An unreadable scan is not an absence.**  `observe_attachment` takes presence
as a tri-state, and `None` changes nothing at all.  Collapsing a failed scan
into "the dock is gone" re-armed the latch and brought the prompt back on the
next poll, which is a permissions error turned into a security question.
Presence is read by identity for the same reason everything else here is: only
the literal `False` is an absence.

**A held identity stops answering once a reading cannot confirm it.**  A poll
that finds something present and cannot name it changes nothing about the
attachment -- retiring there would drop a live prompt every time one sysfs
attribute went briefly unreadable -- but the identity still being held is the
*previous* dock's.  Read straight, it answered questions about a device that
may already be gone: plug dock B in where a disowned dock A was, catch the poll
before B's `device_name` is readable, and the reported answer was that the
attached device is one we disowned -- about a dock nobody had disowned.  So
that poll marks the identity unconfirmed, and the disownership question answers
`False` until some reading names the device again.  Nothing else is dropped:
the token, the latch and the generation belong to the attachment and survive
it.  `confirm` is the exception, and deliberately: it carries an identity of
its own and is refused unless that identity matches the one held here, so a
caller that can name the device is better evidence than a poll that could not,
and the record is what answers for it.

**Retiring is a transition, not a state.**  An undocked handheld is the default
state of this hardware, and "nothing attached" is the reading it produces every
few seconds, forever.  Retiring on each of those polls ticked the generation
once per poll -- a thousand polls, generation one thousand -- so the number
that is supposed to name one attachment named nothing instead, and no payload
built from it was stable between two reads.  So absence retires only what is
there to retire: with no identity, no token, no latch and no acknowledgement
left, the attachment is already gone and a poll has nothing to do.

**One attachment, one act.**  The token is consumed by `confirm`, and the
generation it belonged to is marked spent.  Clearing the token alone was not
enough: the bound UUID stayed behind, so the next poll minted a *fresh* token
for the same dock and a second press enrolled it all over again.  A spent
generation mints nothing; it takes a real replug -- a new generation -- to ask
again.

**Remembered, or just this once.**  `enroll` stores the device with the `auto`
policy, the way Desktop Mode already did to the dock that works today;
`authorize` trusts it for this session alone.  Which one runs is named by the
caller and checked by identity against exactly those two words, because the
difference is what the player was told, not an implementation detail.

**A deliberate disconnect is carried in, and the report names the dock.**
When Re-Gear deauthorizes a still-cabled dock on purpose, the hardware
afterwards looks exactly like a brand-new attachment: present, named,
unauthorized, unenrolled.  Nothing in sysfs can tell that apart from a replug,
so this layer does not try to infer which one happened -- it takes the fact
from the layer that owns the physical-cable story, and that layer says which
device it is about: `note_intentional_disconnect(active, uuid=...)`.

Keying the report to the attachment *generation* instead could not be filed at
all, and the feature itself is the reason.  The deauthorization is what makes
the dock read absent; that absent poll retires the attachment and bumps the
generation.  The owning layer is holding the generation it read while the dock
was still there, so its report always arrives one poll late, is refused as
stale, and nothing is ever recorded -- after which the dock re-enumerates on
wake as first-time trust with a full confirmation behind it.  Filing while
nothing was named was worse than useless: it bound the disownership to `""`,
which then attached itself to whatever enumerated next, so a different dock
that had never been disowned was refused forever, with no exit a player could
reach.

So what is kept is a set of disowned UUIDs.  A report is filed against the UUID
the caller names, whether or not that device is the attached one and whether or
not anything is attached at all -- the normal case is that it is *not*
attached, because deauthorizing it is what made it read absent.  A device is
blocked when the *currently attached* UUID is one that has been disowned and
not cleared.  It never binds to `""`, it names no generation, and there is no
moment at which it can go stale.  Clearing takes the same UUID, and nothing
else clears it: not an absence, not a wake, not a re-enumeration, not a replug,
and not another dock attaching -- a second dock arriving is not evidence about
the first, and treating it as evidence is how plugging in something else came
to unblock a dock we had disowned.

The whole report is taken under the one lock, so a caller does not have to read
anything from this object before filing one.  That is not only tidier: the old
read-then-file pair -- read the generation, then file against it -- was a race
with every poll in the system, and it dropped reports silently when one landed
in between.

The trade this makes, stated plainly so a reader does not take it for a bug: a
physical unplug-and-replug of the *same* dock stays blocked until the owning
layer files the clear for that UUID.  It is not a blacklist and it is not an
oversight; it is the side of an unresolvable ambiguity chosen on purpose,
because wrongly re-offering a DMA grant for a dock we just disowned is worse
than making the layer that knows the cable was pulled say so once.  The exit is
always reachable and it is one call: the same UUID, `active=False`.

**Both sides of that comparison are spelled the same way.**  A report's UUID is
normalized on the way in exactly as the observer normalizes what it reads --
stripped, then case-folded -- on the file path and on the clear path alike.
The set used to store whatever arrived, byte for byte, while the attached
identity it is compared against had already been case-folded, so a report
naming the same dock in the uppercase hex some tools print was *accepted* --
it returned `True`, and the layer that filed it had every reason to believe the
dock was disowned -- and blocked nothing at all.  The dock was offered as
first-time trust on its next attach and a full confirmation ran the executor.
A report that is accepted and does nothing is worse than one that is refused,
because nobody is left to notice.

**A NAMED LIMITATION: the disowned set does not survive a plugin restart.**  It
is in-memory state, so restarting the plugin forgets every disownership, and a
dock deauthorized on purpose before the restart comes back afterwards as
first-time trust.  That is real and it is not fixed here.  Where that record
belongs, how long it lives and who may write it is a question for the layer
that owns claims and admission rather than something to answer by inventing a
store in this module, and it is escalated to that owner as an open design
question.  Written down here so the next reader finds a limitation rather than
a surprise.

**The player never sees a hardware id, and neither does an RPC.**  A
Thunderbolt router UUID is a hardware unique identifier, which
`SAFETY_INVARIANTS` #12 requires redacted from diagnostics.  So the device is
addressed outwards by an opaque token minted per attachment: random, never
derived from the UUID, stable while that attachment lasts so a status poll does
not make the card flicker, and invalidated the moment the dock goes away.

That is the guarantee this layer keeps, and it is enforceable because it is a
rule about this code rather than about hardware: **Re-Gear never puts the uuid
into a payload itself.**  The id is handed to the executor, which has to name
the device to `boltd`, and to nothing else -- no outcome field, no log line, no
exception.  What a device chooses to publish about itself in its own product
string is a separate matter, and not one this layer can legislate; the observer
module says why, and says it without claiming a filter that works.

**The executor's result code is passed through unedited.**  The shape filter
that used to sit here is gone.  It refused a code whole once the count of its
hex-class characters crossed a limit, and it was wrong in both directions at
once.  Too weak: the same id re-encoded is thirteen hex-class characters in
base32 and seven in base64, so the rule was blind to every non-hex encoding it
was supposed to stop.  Too strong, and this is what actually cost something:
the short generic codes this feature emits itself all sail well under the
limit, while a real diagnostic -- the sentence that says `boltd` is not
running, or why it refused -- is long and dense enough to be refused whole.  So
the filter removed precisely the codes with information in them and passed the
ones without, and a player whose dock did not enrol was handed a stand-in where
the reason had been.  A code that is missing or is not a string still cannot be
repeated, because a payload field typed `str` has to hold one.

**A zero exit is not proof.**  `boltctl` accepting the request says it was
taken, not that the device became trusted, so the outcome reports `requested`
and carries `verified=None` until somebody actually re-reads the device.
`record_verification` is where that reading comes back, and it stays tri-state:
unread is not the same as unauthorized.  It also has to be a reading of the
right device.  It takes the identity and generation the reading was taken in,
and answers `None` -- nobody could look -- unless they are the ones the spent
token was bound to, because a reading that cannot be proven to be about the
device that was acted on is not evidence about it.

**Single-flight.**  Every public method holds one lock, so a double press, a
status poll and a readback cannot interleave halfway through spending a token.
The lock is held across the executor call as well: the token is already spent
by then, but serialising the whole act is what makes "exactly once" true under
real threads rather than true in a sequential test.

**One payload, one lock acquisition.**  `snapshot` exists because serialising
each field separately is not the same as answering once.  The delivery layer
used to build a status payload from six calls -- assess, the latch, the
generation, the token, the disconnect flag, the open confirmation -- each
correct under this lock and each taken at a different instant, so a report
landing between two of them produced a payload that contradicted itself:
`offered` beside a live token beside `intentional_disconnect=True`, which is
the prompt raised for a dock Re-Gear had just deliberately deauthorized.  Every
field a payload needs is computed here under one acquisition, including minting
the token, so the fields are answers about one moment.  A caller that reads
them one at a time is back to sampling six moments, which is why this is the
method a payload is built from and the properties beside it are for callers
asking a single question.

**And the reading is part of that payload, so it is part of that acquisition.**
That claim was still one acquisition short of true.  The caller handed its
reading in through `observe_attachment` under one acquisition and built the
payload under the next, so a second RPC thread could observe a *different* dock
in between -- and the snapshot then answered from the attachment rather than
from the argument in exactly the two places this layer looks at the attachment:
the disownership that goes into the assessment, read from the uuid whichever
thread observed most recently, and the "has any reading confirmed this
identity" guard beside it, a single flag that whichever thread polled last had
written.  Every other input to that same assessment was the caller's own
reading, so two concurrent `status()` calls for two docks cross-contaminated:
an offer for one dock carried the other's disownership, and one thread's
nameless poll flipped the answer inside another thread's half-built payload.

So `observe_and_snapshot` takes the reading and does the whole sequence --
apply it, assess it, mint against it, read every remaining field -- without
letting go of the lock once, and nothing it returns was read in a different
acquisition from anything else.  `observe_and_answer` is the same sequence with
the player's answer in the middle, because an acknowledgement's payload is a
payload.  `confirm` carries the state that travels beside its outcome in the
outcome itself, for the same reason and against the same defect: a poll landing
between the act and a separately-locked snapshot produced `requested=True` for
one dock beside the generation and the spent latch of the one that replaced it.

The latch belongs to the attachment, so declining does not blacklist: unplug
and plug back in and the offer returns.  A player who said "not now" and
changed their mind should not have to find a settings screen.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, replace

from ..domain.device_authorization import (
    DeviceAuthorizationAssessment,
    assess_device_authorization,
)
from ..ports.device_authorization import (
    DeviceAuthorizationPort,
    DeviceEnrollmentResult,
)


#: The only two acts behind this prompt. `enroll` is remembered, `authorize`
#: lasts for this session -- the player was told which one they are agreeing
#: to, so anything else is refused rather than resolved to a default.
_ACTIONS = frozenset({"enroll", "authorize"})

#: What an executor's result code becomes when there is no code to repeat:
#: missing, empty, or not a string at all. Nothing about its *content*, which
#: is the port's own words and travels unedited -- a code is the only place a
#: failed act can say what went wrong.
_UNREPORTABLE = "device_authorization.result_unreportable"


@dataclass(frozen=True, slots=True)
class DeviceAuthorizationOutcome:
    #: True only when the executor accepted the request. Never a claim that the
    #: device is now trusted -- `verified` is where that would live.
    requested: bool
    code: str
    #: The attachment-scoped token the request named. Never a hardware id, so a
    #: result can be logged and shown without leaking which dock this is.
    token: str = ""
    #: What a post-action re-read found. `None` means nobody looked yet, which
    #: is a different fact from "looked, and it is not authorized".
    verified: bool | None = None
    #: The attachment state that travels beside this outcome in a payload,
    #: read in the same acquisition that produced the outcome. Not decoration:
    #: a delivery layer that takes its own snapshot afterwards is sampling a
    #: second instant, and a poll landing in that window made the payload
    #: describe two attachments at once -- this dock's token and names beside
    #: the generation and the latch of the dock that replaced it. Defaulted so
    #: the dataclass can still be built field by field; `confirm` always fills
    #: it in.
    state: DeviceAuthorizationSnapshot | None = None


@dataclass(frozen=True, slots=True)
class DeviceAuthorizationSnapshot:
    """Every field a payload needs, all of them read at one instant.

    Not a view onto the service: the values are copies, taken under one
    acquisition of the one lock, and they stay true of that moment however long
    the caller holds them.  That is the whole point -- a payload assembled from
    six separately-locked reads is six moments wearing one dict, and the
    contradictions it produced are named in the module docstring.
    """

    #: Whether the domain says a prompt is honest right now. It is an answer
    #: about the *caller's reading*, so it can be True with no token beside
    #: it: a reading of a dock that was retired underneath it is offered and
    #: has nothing to mint against. The delivery layer owns that pair and
    #: turns it into an unresolved identity, because "which device is this a
    #: reading of" is its question, not the domain's.
    offered: bool
    #: The domain's code for that decision, whichever way it went.
    code: str
    #: This attachment's opaque token: minted if a prompt is being offered for
    #: the device this layer observed, repeated if a confirmation is already
    #: open and the reading could name nothing, and "" otherwise. Never a
    #: hardware id.
    token: str
    #: The latch: whether this attachment has already been offered.
    already_offered: bool
    #: Whether the device attached right now is one this backend disowned.
    intentional_disconnect: bool
    #: Whether a prompt was acknowledged and its token is still live.
    confirmation_open: bool
    #: The attachment this all describes.
    generation: int


@dataclass(frozen=True, slots=True)
class DeviceAuthorizationAnswer:
    """What the player's answer did, and the payload state around it.

    Both from one acquisition, because the payload a delivery layer builds out
    of them is one payload: reading the latch back afterwards is a second
    instant, and another thread's poll lands in it.
    """

    #: Whether the token named a live prompt and the latch was spent by this.
    accepted: bool
    #: The same fields a status payload is built from, taken after the answer.
    state: DeviceAuthorizationSnapshot


class DeviceAuthorizationService:
    """One offer per attachment, and one act behind an explicit yes."""

    def __init__(self, commands: DeviceAuthorizationPort) -> None:
        self._commands = commands
        #: One lock for every public method. See the module docstring.
        self._lock = threading.Lock()
        #: Bumped whenever the thing on the other end of the cable may have
        #: changed. Everything scoped to an attachment is scoped to this.
        self._generation = 0
        #: The identity this layer has actually observed, and the only identity
        #: anything may be minted for or acted on.
        self._uuid = ""
        #: Whether the most recent reading failed to confirm that identity --
        #: something present that nothing could name. The attachment survives
        #: it, but the id above stops answering questions about "the attached
        #: device" until a reading names one again. Part of the attachment
        #: record, like the id it qualifies, and written and read inside the
        #: one acquisition that answers about a reading: a poll that set it in
        #: one acquisition while another thread's payload was being built in
        #: the next is what made one caller's nameless reading flip the
        #: disownership answer inside somebody else's payload.
        self._identity_unconfirmed = False
        self._offered = False
        self._acknowledged = False
        self._token = ""
        self._token_uuid = ""
        #: The generation whose one token has been spent. Not a blacklist: a
        #: replug bumps past it.
        self._consumed_generation: int | None = None
        self._consumed_token = ""
        #: The identity the spent token was bound to, kept so a later readback
        #: has to prove it is about that device rather than about whatever the
        #: bus happens to hold by then.
        self._consumed_uuid = ""
        #: Every device the owning layer has disowned and not taken back. A set
        #: keyed by UUID rather than a flag keyed by attachment: the report is
        #: normally filed for a device that is *not* attached, because
        #: deauthorizing it is what makes it read absent, and a flag with
        #: nothing to bind to bound itself to whatever enumerated next. Only
        #: this backend can add to it, one entry per dock it disowned.
        self._disowned: set[str] = set()

    # -- observation ---------------------------------------------------------

    def observe_attachment(self, *, present: bool | None, uuid: str) -> None:
        """Take one reading of what is attached, and retire what it invalidates.

        `present` is a tri-state read by identity: only the literal `False` is
        an absence.  `None` -- a scan that could not be read -- says nothing, so
        it changes nothing, and so does anything that is not one of the three.
        Absence retires the attachment, but only when there is an attachment
        left to retire: undocked is the default state of a handheld, and
        re-retiring it on every poll is what made the generation count polls
        instead of attachments.  A different UUID is a different dock, however
        quickly it replaced the last one, so it retires the attachment too -- a
        replacement must not inherit an offer the player answered about
        something else.

        A reading is never a report.  Nothing observed here files or clears a
        disownership: a dock arriving says nothing about which docks this
        backend deauthorized, and letting it speak for them is how a replug --
        or simply plugging in a second dock -- came to unblock one.

        A caller that is about to build a payload out of this reading wants
        `observe_and_snapshot` instead, which does this and answers in one
        acquisition.  Observing here and snapshotting afterwards is two
        instants, and another RPC thread's reading of another dock lands
        between them.
        """
        with self._lock:
            self._observe_locked(present=present, uuid=uuid)

    def _observe_locked(self, *, present: bool | None, uuid: str) -> None:
        """`observe_attachment`'s body, with the lock already held.

        Split out so the one acquisition that answers about a reading is also
        the one that took it. One implementation, so the composed call and the
        bare one cannot drift.
        """
        if present is False:
            if self._holds_attachment():
                self._retire_attachment()
            return
        if present is not True:
            return
        if type(uuid) is not str or not uuid:
            # Present, but nothing names it. An unresolved identity is as
            # unreadable as a failed scan, and must not read as "the dock
            # was replaced by a nameless one" on every single poll -- so
            # the attachment stands. What it may not do is keep answering
            # as if the id we hold were confirmed: the thing present may
            # already be a different dock, and the previous one's record
            # is not evidence about it.
            self._identity_unconfirmed = True
            return
        if uuid != self._uuid:
            self._retire_attachment()
            self._uuid = uuid
        self._identity_unconfirmed = False

    def observe_device(self, present: bool) -> None:
        """Deprecated: use `observe_attachment`, which is identity-aware.

        Kept as a thin shim for callers that have not been moved across. It
        carries no UUID, so it can retire an attachment but never recognise a
        replacement -- and, like the method it delegates to, it treats an
        unreadable `None` as a reading that says nothing, and retires only on
        the transition into absence.
        """
        self.observe_attachment(present=present, uuid="")

    def note_intentional_disconnect(self, active: bool, *, uuid: str) -> bool:
        """Record that Re-Gear deauthorized a named, still-cabled dock on purpose.

        An input, never an inference: sysfs can say a device is unauthorized,
        never why, and from it a deliberate disconnect and a replug are the
        same reading.  So the layer that owns the physical-cable fact states it,
        and states it strictly -- exactly `True` is a report, exactly `False` is
        a clear.  Anything else is neither, and is refused rather than coerced,
        because `bool(active)` turned `None`, `0`, `""` and `[]` into a clear
        that silently unblocked a dock we had disowned.

        `uuid` names the device the report is *about*, and it is required: a
        non-empty string or nothing happens.  It does not have to be the
        attached device and there does not have to be an attached device at
        all, which is the whole point -- the deauthorization is what makes that
        dock read absent, so by the time the owning layer can file, the dock it
        is filing about has usually already gone.  Nothing here consults the
        attachment or its generation, so there is no window in which a report
        becomes too late to file, and no way for one to bind to a device it was
        never about.

        It is normalized the way the observer normalizes the id it reads --
        stripped, then case-folded -- before it is filed or cleared, because
        the set is compared against *that* value.  Storing the caller's bytes
        instead meant a report naming the same dock in uppercase hex, or with
        whitespace still around it, was accepted and then matched nothing: the
        caller was told `True`, the dock was offered as first-time trust on its
        next attach, and a full confirmation ran the executor.

        A report adds that UUID to the disowned set; a clear removes it, and
        only the same UUID does.  A clear for a device that was not disowned is
        accepted and changes nothing: it is a statement about that device, and
        it is true once the call returns.

        Returns whether the report was accepted, so a caller mirroring it into
        a payload records this layer's decision rather than its own argument.
        """
        with self._lock:
            named = _normalized(uuid)
            if not named:
                return False
            if active is True:
                self._disowned.add(named)
                return True
            if active is False:
                self._disowned.discard(named)
                return True
            return False

    # -- the token -----------------------------------------------------------

    def candidate_token(self, uuid: str) -> str:
        """The opaque handle for this attachment, minted once and then stable.

        Minted only for the device this layer has *observed*.  A caller naming
        anything else is asking for a handle on a dock nobody looked at, and
        the answer to that is `""`: the observation layer is read-only, and it
        is the only thing entitled to say what is attached.

        Random rather than derived: a token that could be reversed into the
        UUID would leak the hardware id it exists to keep out of the payload.
        Returns `""` for a generation whose token has already been spent, so a
        status poll after a confirmation cannot mint a second chance at the
        same dock.

        A caller building a payload wants `snapshot` instead, which mints the
        same token beside every other field it needs and under the same
        acquisition of this lock.
        """
        with self._lock:
            return self._mint_token(uuid)

    def acknowledge(self, token: str) -> bool:
        """Spend this attachment's one prompt, because it was actually shown.

        The only thing that spends the latch. A status read must never call it:
        reading twice is not being asked twice, and losing the prompt to a poll
        is how a player ends up with a dock that silently never works.

        A caller that answers *and* builds a payload wants
        `observe_and_answer`, which observes, answers and snapshots under one
        acquisition. Answering here and reading the latch back afterwards is
        two instants.
        """
        with self._lock:
            return self._acknowledge_locked(token)

    def decline(self, token: str) -> bool:
        """"Not now", for this attachment and no further.

        Spends the latch and drops the token, so nothing reappears on the next
        poll. No blacklist: a replug bumps the generation and asks again.
        """
        with self._lock:
            return self._decline_locked(token)

    def _acknowledge_locked(self, token: str) -> bool:
        """`acknowledge`'s body, with the lock already held."""
        if not self._is_live_token(token):
            return False
        self._offered = True
        self._acknowledged = True
        return True

    def _decline_locked(self, token: str) -> bool:
        """`decline`'s body, with the lock already held."""
        if not self._is_live_token(token):
            return False
        self._offered = True
        self._acknowledged = False
        self._token = ""
        self._token_uuid = ""
        self._consumed_generation = self._generation
        return True

    # -- state ---------------------------------------------------------------

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def offered(self) -> bool:
        with self._lock:
            return self._offered

    @property
    def intentional_disconnect(self) -> bool:
        """Whether a dock we disowned is still the answer for this attachment.

        Published so a delivery layer can report the fact without keeping a
        second copy of it. Two stores of one flag is what produced a payload
        that said `offered` and `intentional_disconnect` at the same time.

        It is a question about the device in front of us, not about the record:
        a disowned dock that is not attached blocks nothing, there is no state
        in which an empty port reports itself as disowned, and a port holding
        something no reading has managed to name answers `False` rather than
        answering for whatever was there before it.
        """
        with self._lock:
            return self._attached_is_disowned()

    @property
    def confirmation_open(self) -> bool:
        """A prompt that was acknowledged and whose token is still live."""
        with self._lock:
            return bool(self._acknowledged and self._token)

    def assess(
        self,
        *,
        device_present: bool | None,
        identity_resolved: bool,
        authorized: bool | None,
        already_enrolled: bool | None,
    ) -> DeviceAuthorizationAssessment:
        """Ask the pure predicate, with the state only this layer holds.

        One question, one answer.  A caller that needs the decision *and* the
        fields that travel beside it in a payload asks `snapshot`, because two
        calls are two moments.
        """
        with self._lock:
            return assess_device_authorization(
                device_present=device_present,
                identity_resolved=identity_resolved,
                authorized=authorized,
                already_enrolled=already_enrolled,
                already_offered=self._offered,
                intentional_disconnect=self._attached_is_disowned(),
            )

    def snapshot(
        self,
        *,
        device_present: bool | None = None,
        identity_resolved: bool = False,
        authorized: bool | None = None,
        already_enrolled: bool | None = None,
        uuid: str = "",
    ) -> DeviceAuthorizationSnapshot:
        """Everything one payload needs, answered at a single instant.

        The arguments are one reading, exactly as `assess` takes it, plus the
        identity that reading named.  Everything else comes from this layer,
        and all of it is read -- and the token minted -- inside one acquisition
        of the one lock, so no report, poll or press can land between two
        fields of the same payload.  That interleaving is what produced
        `state="offered"` with a live token and `intentional_disconnect=True`
        in one dict: a prompt for a dock this backend had just deauthorized.

        Called with no reading at all -- the default arguments -- it answers
        the state fields and nothing is offered and nothing is minted, which is
        what a caller wants after `confirm`, where the decision and the token
        are the outcome's and only the surrounding state is still to be read.

        The token is minted only for the device the reading named, as
        `candidate_token` does.  When the reading could name no device and a
        confirmation is open, the token already minted for the attachment is
        repeated instead: a dialog on screen must not be stranded by one
        unreadable poll.  That repeat is deliberately *not* extended to a
        reading that named some other device -- answering with the attached
        dock's token there is how a status could return the replacement's token
        while reporting the attachment it replaced.

        This answers about the reading it is handed and about the attachment as
        it stands *now*, which are the same thing only if the caller's own
        reading is the one this layer last observed.  A payload must not assume
        that under threads, so `observe_and_snapshot` is what a payload is
        built from; this stays for a caller asking the state alone.
        """
        with self._lock:
            return self._snapshot_locked(
                device_present=device_present,
                identity_resolved=identity_resolved,
                authorized=authorized,
                already_enrolled=already_enrolled,
                uuid=uuid,
            )

    def observe_and_snapshot(
        self,
        *,
        present: bool | None,
        identity_resolved: bool,
        authorized: bool | None,
        already_enrolled: bool | None,
        uuid: str,
    ) -> DeviceAuthorizationSnapshot:
        """One reading in, one payload's worth of answers out, one acquisition.

        The whole sequence -- take the reading, retire what it invalidates,
        assess it, mint against it, read the latch, the flag, the open
        confirmation and the generation -- happens without the lock being
        released once, so no field of the result was read in a different
        acquisition from any other, and no other thread's reading can land in
        the middle of one payload.

        Handing the reading to `observe_attachment` and then asking `snapshot`
        is the same work in two acquisitions, and that gap is a defect rather
        than an inefficiency: between them another RPC thread observes its own
        dock, and the two things this layer reads from the *attachment* rather
        than from the argument -- the disownership and the guard that says
        whether any reading has confirmed the held identity -- then answer
        about that thread's dock inside this thread's payload.
        """
        with self._lock:
            self._observe_locked(present=present, uuid=uuid)
            return self._snapshot_locked(
                device_present=present,
                identity_resolved=identity_resolved,
                authorized=authorized,
                already_enrolled=already_enrolled,
                uuid=uuid,
            )

    def observe_and_answer(
        self,
        token: str,
        *,
        accept: bool,
        present: bool | None,
        identity_resolved: bool,
        authorized: bool | None,
        already_enrolled: bool | None,
        uuid: str,
    ) -> DeviceAuthorizationAnswer:
        """The player's answer, taken against the device that is there now.

        Observe, answer, snapshot -- one acquisition, for the reason
        `observe_and_snapshot` is one: what comes back is a payload, and a
        payload whose latch was read in a later acquisition than its token is
        two moments wearing one dict.

        `accept` is read by identity, exactly as everything else here is:
        `True` acknowledges, `False` declines, and anything else answers
        nothing and spends nothing rather than being resolved to whichever of
        the two is truthier.
        """
        with self._lock:
            self._observe_locked(present=present, uuid=uuid)
            if accept is True:
                accepted = self._acknowledge_locked(token)
            elif accept is False:
                accepted = self._decline_locked(token)
            else:
                accepted = False
            return DeviceAuthorizationAnswer(
                accepted,
                self._snapshot_locked(
                    device_present=present,
                    identity_resolved=identity_resolved,
                    authorized=authorized,
                    already_enrolled=already_enrolled,
                    uuid=uuid,
                ),
            )

    def _snapshot_locked(
        self,
        *,
        device_present: bool | None = None,
        identity_resolved: bool = False,
        authorized: bool | None = None,
        already_enrolled: bool | None = None,
        uuid: str = "",
        acted_uuid: str = "",
    ) -> DeviceAuthorizationSnapshot:
        """`snapshot`'s body, with the lock already held.

        `acted_uuid` is for `confirm`, and only for it: a caller that has
        proved which device it means gets the disownership answered about
        *that* device rather than about whatever is attached by the time the
        act finishes.  The two agree on every path that reaches the act, since
        reaching it means the identity matched; where they differ is a refusal,
        and there the caller's own dock is the one the payload is about.

        A proof is a non-empty string and nothing else, read by identity like
        every other decision here: an argument that names no device is no
        proof, so the attached device answers for it exactly as it does for a
        poll, which is what a caller passing nothing at all gets.
        """
        proved = type(acted_uuid) is str and bool(acted_uuid)
        disowned = (
            self._named_is_disowned(acted_uuid)
            if proved
            else self._attached_is_disowned()
        )
        assessment = assess_device_authorization(
            device_present=device_present,
            identity_resolved=identity_resolved,
            authorized=authorized,
            already_enrolled=already_enrolled,
            already_offered=self._offered,
            intentional_disconnect=disowned,
        )
        open_prompt = bool(self._acknowledged and self._token)
        named = type(uuid) is str and bool(uuid)
        token = ""
        if assessment.offered or open_prompt:
            if named:
                token = self._mint_token(uuid)
            elif open_prompt:
                token = self._token
        return DeviceAuthorizationSnapshot(
            offered=assessment.offered,
            code=str(assessment.code),
            token=token,
            already_offered=self._offered,
            intentional_disconnect=disowned,
            # Read again rather than reused: minting a *fresh* token closes
            # whatever prompt was open, and re-reading makes that a fact
            # about the state rather than an assumption about the order.
            # A live token is repeated rather than replaced, so in practice
            # the two readings agree.
            confirmation_open=bool(self._acknowledged and self._token),
            generation=self._generation,
        )

    # -- the act -------------------------------------------------------------

    def confirm(
        self,
        token: str,
        *,
        consent: bool,
        action: str,
        device_present: bool | None,
        identity_resolved: bool,
        authorized: bool | None,
        already_enrolled: bool | None,
        uuid: str,
        generation: int,
    ) -> DeviceAuthorizationOutcome:
        """Act on one named device, after proving it is still the same one.

        `token` is the attachment-scoped handle the prompt was drawn against,
        never a hardware id.  `consent` must be exactly `True`.  `uuid` and
        `generation` are the caller's *freshly observed* identity, and the
        remaining arguments its fresh reading of that same observation -- all
        of it refused unless it describes the device this layer observed and
        minted the token for.

        The outcome carries the attachment state that travels beside it in a
        payload, read in this same acquisition.  A delivery layer that asked
        for a snapshot afterwards was sampling a second instant: a poll landing
        in that window retires the attachment this call just acted on, so the
        payload reported `requested=True` with this dock's token and names
        beside the *next* dock's generation and spent latch -- one dict about
        two attachments, and the one it named is not the one it described.
        """
        with self._lock:
            outcome = self._confirm_locked(
                token,
                consent=consent,
                action=action,
                device_present=device_present,
                identity_resolved=identity_resolved,
                authorized=authorized,
                already_enrolled=already_enrolled,
                uuid=uuid,
                generation=generation,
            )
            return replace(outcome, state=self._snapshot_locked(acted_uuid=uuid))

    def _confirm_locked(
        self,
        token: str,
        *,
        consent: bool,
        action: str,
        device_present: bool | None,
        identity_resolved: bool,
        authorized: bool | None,
        already_enrolled: bool | None,
        uuid: str,
        generation: int,
    ) -> DeviceAuthorizationOutcome:
        """`confirm`'s decision and act, with the lock already held."""
        if consent is not True:
            return DeviceAuthorizationOutcome(
                False, "device_authorization.confirmation_required", ""
            )
        if type(action) is not str or action not in _ACTIONS:
            return DeviceAuthorizationOutcome(
                False, "device_authorization.action_invalid", ""
            )
        # An unknown token is a confirmation for a dock that is not the one
        # in front of us -- a replug, a second device, or a stale dialog.
        # Refuse rather than resolving it to whatever happens to be here.
        if not self._is_live_token(token):
            return DeviceAuthorizationOutcome(
                False, "device_authorization.token_stale", ""
            )
        # The identity binding, checked against what was OBSERVED. The
        # token's own record of the device it was minted for is checked as
        # well, but it is not the authority: a record that agrees only with
        # itself is how a UUID nobody had ever seen reached `boltd`.
        if (
            type(generation) is not int
            or generation != self._generation
            or type(uuid) is not str
            or not uuid
            or uuid != self._uuid
            or uuid != self._token_uuid
        ):
            return DeviceAuthorizationOutcome(
                False, "device_authorization.attachment_changed", token
            )
        # Re-assessed with the latch ignored: the offer being spent is what
        # got us here, and must not be the reason the act is refused. The
        # disownership is read from the record rather than through the
        # "has a reading confirmed it" guard the polls use: the caller has
        # just proved its identity against the one held here, so there is
        # nothing unconfirmed about which device this is.
        fresh = assess_device_authorization(
            device_present=device_present,
            identity_resolved=identity_resolved,
            authorized=authorized,
            already_enrolled=already_enrolled,
            already_offered=False,
            intentional_disconnect=self._is_disowned(),
        )
        if not fresh.offered:
            return DeviceAuthorizationOutcome(False, fresh.code, token)
        self._offered = True
        self._acknowledged = False
        # Spend the token *and* the generation before acting, so neither a
        # second press nor the next status poll can produce a second act.
        self._token = ""
        self._token_uuid = ""
        self._consumed_token = token
        self._consumed_uuid = uuid
        self._consumed_generation = self._generation
        result = self._run(action, uuid)
        return DeviceAuthorizationOutcome(
            result.enrolled is True, result.code, token
        )

    def record_verification(
        self,
        token: str,
        *,
        authorized: bool | None,
        uuid: str,
        generation: int,
    ) -> bool | None:
        """Carry back what a post-action re-read of the device actually found.

        Tri-state on purpose: `None` means nobody managed to read the state,
        which is not the same as reading it and finding the device untrusted.

        A reading is evidence only about the device it was taken of, so it has
        to be shown to be about this one.  The token must be the spent one, and
        the `uuid` and `generation` the reading was taken in must be the ones
        that token was bound to.  Nothing else produces a `True` or a `False`:
        a reading with no identity -- the caller could not tell what it was
        looking at -- is exactly the case this exists to answer `None` to,
        because crediting one of those to the confirmed device is how
        `verified=True` came to be drawn from a dock nobody had identified.
        """
        with self._lock:
            if not self._is_spent_token(token):
                return None
            if type(uuid) is not str or not uuid or uuid != self._consumed_uuid:
                return None
            if (
                type(generation) is not int
                or generation != self._consumed_generation
            ):
                return None
            if authorized is True or authorized is False:
                return authorized
            return None

    # -- internals -----------------------------------------------------------

    def _holds_attachment(self) -> bool:
        """Whether an absence would still have something to retire. Lock held.

        Deliberately does not consult the disowned set: that outlives any
        attachment on purpose and is not scoped to one, so counting it here
        would put the retire back on every single poll of an empty port, with
        the generation ticking once per poll again.
        """
        return bool(
            self._uuid
            or self._token
            or self._token_uuid
            or self._offered
            or self._acknowledged
            or self._consumed_token
        )

    def _retire_attachment(self) -> None:
        """Everything scoped to the attachment dies with it. Lock held.

        Everything except the disowned set, which is not part of an
        attachment: it is keyed by device, and absence is precisely the reading
        a deliberately deauthorized dock produces, so forgetting it here is
        what re-offered that dock as first-time trust after a wake.
        """
        self._generation += 1
        self._uuid = ""
        self._identity_unconfirmed = False
        self._offered = False
        self._acknowledged = False
        self._token = ""
        self._token_uuid = ""
        self._consumed_token = ""
        self._consumed_uuid = ""

    def _is_disowned(self) -> bool:
        """Is the device this layer holds one we disowned? Lock held.

        Both halves matter.  Without the identity there is nothing to ask the
        question about, so an empty port is never disowned however many docks
        the set remembers; and the question is asked of the *attached* device,
        so a report about some other dock cannot answer it.

        Normalized on this side too, not only where a report is filed.  The
        observer already case-folds what it reads, so in the shipping path the
        two agree; normalizing here as well means they agree whatever the
        reading came through, and a disowned dock stays blocked rather than
        slipping past on a difference of spelling.
        """
        return self._named_is_disowned(self._uuid)

    def _named_is_disowned(self, uuid: object) -> bool:
        """Is the device this id names one we disowned? Lock held.

        The same question asked of a named device rather than of the held one,
        for `confirm`: a payload about an act names the device the caller
        proved, so the flag beside it has to be about that device too. Anything
        that is not a device id -- `""`, and anything `_normalized` cannot
        spell -- names nobody and is disowned by nobody.
        """
        named = _normalized(uuid)
        return bool(named) and named in self._disowned

    def _attached_is_disowned(self) -> bool:
        """The same question, refused while no reading confirms the id. Lock held.

        What a poll is entitled to say.  When the last reading found something
        present that it could not name, the id still held is the previous
        dock's, and answering from it reports a fresh dock B under dock A's
        disownership.  Nothing is offered in that state either way -- an
        unnamed reading is refused as `identity_unresolved` -- so this costs no
        protection: what it buys is that the refusal names the right reason and
        the flag beside it is not about a device that may already be gone.
        """
        return not self._identity_unconfirmed and self._is_disowned()

    def _mint_token(self, uuid: str) -> str:
        """`candidate_token`'s body, with the lock already held.

        Split out so `snapshot` can mint inside the same acquisition that reads
        every other field of a payload.  One implementation, so a caller that
        takes the token with the state cannot drift from one that asks for it
        alone.
        """
        if type(uuid) is not str or not uuid:
            return ""
        if not self._uuid or uuid != self._uuid:
            return ""
        if self._consumed_generation == self._generation:
            return ""
        if self._token and self._token_uuid == uuid:
            return self._token
        self._token = secrets.token_hex(16)
        self._token_uuid = uuid
        self._acknowledged = False
        return self._token

    def _is_token(self, token: str, known: str) -> bool:
        # `isascii` before the constant-time compare: it raises on anything
        # else, and a caller handing us a non-ASCII string is refusing a token,
        # not crashing the panel. Minted tokens are hex, so nothing real is lost.
        if type(token) is not str or not token or not token.isascii():
            return False
        if not known:
            return False
        return secrets.compare_digest(token, known)

    def _is_live_token(self, token: str) -> bool:
        return self._is_token(token, self._token)

    def _is_spent_token(self, token: str) -> bool:
        return self._is_token(token, self._consumed_token)

    def _run(self, action: str, uuid: str) -> DeviceEnrollmentResult:
        try:
            if action == "authorize":
                result = self._commands.authorize(uuid)
            else:
                result = self._commands.enroll(uuid)
            return DeviceEnrollmentResult(
                result.enrolled is True, _reportable(result.code)
            )
        except Exception:
            return DeviceEnrollmentResult(
                False, "device_authorization.enroll_unavailable"
            )


def _normalized(uuid: object) -> str:
    """A device id spelled the one way this layer compares them. Pure.

    Stripped and case-folded, which is exactly what the observer does to the
    `unique_id` it reads, and `""` for anything that is not a string -- so a
    caller handing this `None`, a `bytes` or a `True` gets the same answer as
    one handing it an empty string, and the caller's own "did this name a
    device" test is a single truthiness check on the result.
    """
    if type(uuid) is not str:
        return ""
    return uuid.strip().casefold()


def _reportable(code: object) -> str:
    """An executor's result code, repeated as it stands.

    The port's words travel unedited.  A code is the only place a failed act
    can say *what* failed -- that `boltd` is not running, that the daemon
    refused, that the id was rejected -- and the shape filter that used to sit
    here refused exactly those: the short generic codes this feature emits
    itself passed every time, while a real diagnostic is long and dense enough
    in hex-class characters to be replaced whole by a stand-in.  It was also
    unwinnable on its own terms, being blind to every non-hex encoding of the
    thing it existed to stop.  See the module docstring.

    The only substitution left is for a code there is nothing to repeat of:
    missing, empty, or not a string.  `DeviceAuthorizationOutcome.code` is
    typed `str` and travels into payloads, so a `None` from a misbehaving port
    becomes this rather than a payload field nobody can render.
    """
    if type(code) is not str or not code:
        return _UNREPORTABLE
    return code
