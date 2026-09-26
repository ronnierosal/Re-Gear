"""Read-only evidence about one attached Thunderbolt device's trust state.

This observes and does nothing else.  It writes no sysfs file, authorizes
nothing and enrols nothing: the decision lives in `regear.domain`, the act
lives behind `boltd`, and reading whether a player's dock is trusted must never
be the thing that changes it.  That holds here by construction -- nothing
below opens a file for anything but reading -- and it is held to it by test:
`tests/test_device_authorization_observer.py` walks this source for filesystem
writers and, separately, compares a snapshot of an entire sysfs tree either
side of an observation.  `scripts/check_architecture.py` guards the same ground
repository-wide, but it delivers less than "no adapter but `device_removal.py`
may write at all": it bans a list of write *attribute names*, so a write
spelled some other way -- `open(path, "w").write(...)`, `shutil.rmtree`,
`os.remove`, a bound `write_text` handed to a local name and called through it
-- passes the gate in silence.  It catches the forms a mistake usually takes;
it is not a proof that none happened, and the two tests above are what actually
hold this module to being read-only.  The other half of the boundary the gate
does check: the one command this module can reach arrives as an injected
callable rather than as a `subprocess` import.

Every field that can be unread is a tri-state, and **every unknown stays
unknown**.  What this reading feeds is a prompt that grants a device direct
access to system memory on a profile where `iommu_dma_protection` reads `0`, so
a file that could not be read must never be rounded to the convenient answer.
Each one, and why:

- **a scan that did not happen is not an empty result.**  A missing or
  unreadable `/sys/bus/thunderbolt/devices` says nothing at all about what is
  plugged in, so `present` is None.  A walk that finished and found no
  attachable router is False, and means exactly what it says.  Collapsed
  together, a permissions error on a docked machine reads as "nothing is
  attached", and the player is told there is no decision waiting while their
  dock sits there dark;
- **unreadable authorization is not unauthorized.**  `authorized` is None for
  anything that is not the literal "0" or "1" -- an absent file, a truncated
  read, or a value this code does not recognise such as the key-authorized
  "2".  Reading any of those as False invents a prompt out of a permissions
  error, and offering to trust a device that is already trusted is how a
  player learns the prompt does not know what it is talking about;
- **unknown enrolment is not unenrolled.**  `boltd` owns the enrolment
  database.  When its directory cannot be read at all, `enrolled` is None:
  stored-but-unauthorized is a real state that a second enrolment does not
  fix, and guessing False there would offer an action that quietly does
  nothing.  A directory that *was* read and does not name the device is a real
  answer, and that one is False.  The `boltctl` listing consulted when the
  directory is unreadable is text a device can write into, so it answers only
  from a structure that is exactly what is expected and is None otherwise --
  see below;
- **an unnamed or unaddressable device is not identified.**  A prompt that
  cannot say which device it means turns "do not authorize devices you do not
  trust" into unusable advice, and a device with no readable `unique_id`
  cannot be handed to `boltctl` afterwards even if the player says yes.
  Either gap leaves `identity_resolved` False and blanks the names, because a
  half-named device is worse than an admitted unknown.

**Two routers, no answer.**  A `device_name` is a product string, not an
identity: two identical docks publish the same one.
`dock_branch.observe_tunnel` refuses in that case rather than picking the first
match, and this refuses more broadly -- *any* second attachable router leaves
`identity_resolved` False.  That module is told which name the caller meant;
this one is not, so with two routers attached there is no non-arbitrary way to
say which one the player just plugged in.  Sort order is not evidence.  The
cost of guessing is naming one device in the dialog and granting memory access
to another.

**The host router is not an attachment.**  Route 0 -- `0-0`, `1-0` -- is this
machine's own Thunderbolt controller, present on every boot with nothing
plugged into it.  Counting it as a device would offer to trust the handheld to
itself on first launch, forever.  `domainN` entries are the domains
themselves, and retimer entries carry a `:`, so neither matches the router
shape either.

**Names are sanitized so a label renders safely, and that is all sanitizing
is.**  `vendor_name` and `device_name` are the only attributes that reach a
player.  Control characters and non-ASCII bytes become spaces, runs of
whitespace collapse, and the result is capped at `MAX_NAME` and re-stripped.
That keeps a descriptor from carrying terminal escapes into a log, or from
pushing a dialog off screen.  It is a rendering rule.  It is not a filter over
what the text *means*, and `identity_resolved` means exactly what it says: the
device published a readable name and the scan found one router.

`unique_id` is read for one purpose -- addressing the device when `boltctl` is
asked to enrol it -- and `serial` is not read at all.

**The one guarantee about the identifier, and the residual beside it.**  The
guarantee is enforceable because it is about this code rather than about
hardware: *Re-Gear never puts the uuid into a payload itself*.
`ObservedAttachment.uuid` is internal, `SAFETY_INVARIANTS` #12 keeps it out of
every payload, log line, diagnostic and exception, and the delivery facade
addresses a device outward by an opaque attachment token instead.  A test
asserts it for a normal device -- one whose product name is not its own id --
and that is the claim this module stands behind.

The residual, stated plainly because two earlier passes stated it wrongly: **a
device that publishes its own identifier as its product name will have that
string displayed.**  It is the only name the device has, the prompt has to name
something, and a device that has decided to disclose its own id has already
done so by writing it into `device_name`.  That is a device-authored
disclosure, not a Re-Gear diagnostic leak.

No filter over attacker-controlled text can prevent it, and the attempts are
what proved it.  A denylist that matched the id inside the descriptor lost
three ways at once: one non-hex letter inserted every eleven characters leaves
no run to find, the id spelled backwards matches nothing a forward scan looks
at, and eleven characters in each of two fields clear both while twenty-two
characters of one identifier leave together.  Counting hex-class characters
instead of matching them lost in both directions.  Too weak: the same id
re-encoded is thirteen hex-class characters in base32 and seven in base64, and
a nibble-to-`g`..`v` substitution is zero, so any hex-counting rule is blind
to every non-hex encoding.  Too strong, and this is the part that disqualified
it -- it refused real shipping hardware.  "Dell Technologies" beside "Dell
Thunderbolt Dock WD19TBS 180W Docking Station" carries twenty-two hex-class
characters; Kensington's, Plugable's and Razer's full names carry twenty or
more as well.  A refused descriptor left `identity_resolved` False, the domain
declined with `identity_unresolved`, and a named, addressable, unenrolled dock
silently never got its prompt -- precisely the failure this feature exists to
prevent.  `tests/test_device_authorization_observer.py` keeps those product
strings as a permanent regression corpus.

So there is no content filter here, and no claim of one.

**The enrolment listing is a device-writable text, so it is barely trusted.**
`boltd` persists a device's `device_name` and prints it verbatim at the head of
that device's block, so a stored device whose name contains newlines writes
whole `uuid:` and `stored:` lines into `boltctl list` output.  Attributing a
`stored:` line to whichever `uuid:` line came before it reproduced the failure
in both directions: a dock whose own truthful block says `stored: no` reported
as enrolled, so a genuinely new dock never gets its prompt; and a dock that is
stored reported as not enrolled, which is the duplicate enrolment this module
says it refuses to guess at.  Therefore the stored-device directory under
`bolt_state_root` is the source of truth -- it is the database itself, and a
file name there is not a string the device chose -- and `boltctl` is asked only
when that directory cannot be read at all.  What comes back is then read
strictly: one header line opens a device, a block answers only for the single
`uuid` line inside it, and any ambiguity at all -- a uuid appearing twice
anywhere in the listing, two uuids or two `stored` lines in one block, a
`stored` line with no device above it to attribute it to, a `uuid` value that
is not uuid-shaped -- is None.  None is not a cost: the domain's
enrollment-unreadable branch declines the prompt, which is what an unanswered
question should do.  A guess does not.

**Strict is not the same as narrow.**  The field-key grammar used to accept a
single word, on the reasoning that every key `boltctl` prints is one word.  It
is not: `boltctl list` prints `rx speed:` and `tx speed:` under `status:`, and
`dbus path:` beside the uuid.  Those lines are not field lines to a one-word
grammar, so each opened a spurious device block, and the `stored:` line that
followed landed in a block naming no device -- an unattributable `stored`,
which is None.  A completely truthful listing for a genuinely unstored dock was
therefore answered None instead of False, and a truthful `stored: yes` listing
was refused the same way.  `FIELD_LINE` now accepts the keys `boltctl` really
prints: up to three space-separated words of letters, digits and hyphens.  What
it still refuses is what it always refused -- the bullet that opens a device
entry is deliberately not a tree glyph, so a device name reading `* uuid: ...`
is a header rather than a uuid field, and a key must start with a letter.

That is a detection rule, not a proof, and the residual is worth naming: a
device can write a *well-formed* block for a uuid the listing does not
otherwise mention, and nothing in the text distinguishes it from a real one.
It is caught here only because a `boltctl` that is answering at all lists the
attached device too, which makes the fabrication the second appearance of that
uuid -- so the defence is the duplicate, not the parse.  A daemon that answered
while omitting the attached device would leave that gap open.  What closes it
is not reading the listing: the filesystem is the source of truth, and this
function runs only when the filesystem could not be read at all.

**Thunderbolt state only.**  Whether a PCI function or an HDMI connector showed
up is not consulted here and is never proof of anything about authorization: a
dock can be authorized with no display attached, and an eGPU can be trusted
before its driver binds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


#: A router directory: "<domain index>-<route>", e.g. "0-1" or "1-303". The
#: route is hex. "domain0" has no route, and a retimer ("0-1:1.2") carries a
#: colon, so neither can match.
ROUTER_PATTERN = re.compile(r"\d+-[0-9a-fA-F]+")
#: The exact shape `boltd` names a device by, and the only shape
#: `BoltDeviceAuthorizationRunner` will put on a command line.
UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
#: A name shown to a player. Long enough for any real product string -- the
#: longest in the regression corpus is fifty-one characters -- and short enough
#: that a hostile descriptor cannot push a dialog off screen.
MAX_NAME = 64
#: `boltctl list` output this long is a broken pipe or a hostile fixture, and a
#: partial parse of it answers nothing.
MAX_COMMAND_LINES = 2000
#: One word of a `boltctl` field key: a letter first, then letters, digits or
#: hyphens. Starting with a letter is what keeps a tree glyph or a bullet from
#: being read as the beginning of a key.
FIELD_WORD = r"[A-Za-z][A-Za-z0-9-]*"
#: A whole field key. `boltctl list` prints two-word keys -- "rx speed", "tx
#: speed", "dbus path" -- so a one-word grammar silently turned three real
#: lines of every listing into device headers; the third word is headroom for a
#: version that adds one, not an invitation.
FIELD_KEY = rf"{FIELD_WORD}(?: {FIELD_WORD}){{0,2}}"
#: One field line of a `boltctl` block: tree glyphs, then the field key, then
#: its value.
#:
#: The bullet characters that open a device entry are deliberately NOT glyphs
#: here -- neither the ASCII "*" nor the "\u25cf"/"\u25cb" of the unicode
#: rendering. A header line is where `boltd` prints the device's own name, and
#: a name that reads " * uuid: ..." must be a header rather than a uuid field.
FIELD_LINE = re.compile(rf"[ \t|`+\-\u2500-\u257f]*({FIELD_KEY}):(.*)")
#: The two field names read out of a listing. Anything else `boltctl` prints is
#: not an answer to the one question being asked.
READ_FIELDS = ("uuid", "stored")
#: The fallback question, asked only when `boltd`'s own directory is unreadable.
BOLTCTL_LIST = ("/usr/bin/boltctl", "list")


def _read_text(path: Path) -> str:
    """One attribute, or "" when it could not be read.

    Every caller treats "" as the unknown value for its own field rather than
    as content, which is why an unreadable `authorized` becomes None and an
    unreadable `device_name` leaves the device unnamed.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _sanitized(value: str) -> str:
    """A descriptor string made safe to put in front of a player.

    Non-printable and non-ASCII bytes become spaces rather than vanishing, so
    two words separated by a control character stay two words; runs of
    whitespace collapse; the result is capped and re-stripped, because a cut
    made mid-run would otherwise leave a trailing space.

    This is a rendering rule and nothing more. It does not read the string, and
    it makes no judgement about what the device chose to publish -- see the
    module docstring for why nothing here tries to.
    """
    printable = "".join(
        character if " " <= character <= "~" else " " for character in value
    )
    return " ".join(printable.split())[:MAX_NAME].strip()


def _device_uuid(raw: str) -> str:
    """The router's id, normalized, or "" when it is not one.

    Case-folded because `boltctl` is given lowercase and sysfs publishes
    lowercase; anything not matching the shape exactly is refused here rather
    than at the command line, so a garbled id declines the prompt instead of
    producing one that cannot be acted on.
    """
    return raw.casefold() if UUID_PATTERN.fullmatch(raw) else ""


def _is_host_route(name: str) -> bool:
    """Whether a router id names this machine's own controller.

    Route 0 is the host router of its domain. It is always there and is not an
    attachable dock.
    """
    _, _, route = name.partition("-")
    return bool(route) and set(route) == {"0"}


@dataclass(frozen=True, slots=True)
class ObservedAttachment:
    """One reading of the Thunderbolt attachment, completeness included."""

    #: None = the scan itself failed. False = it finished and found nothing.
    present: bool | None
    #: Whether exactly one router was found AND it can be both named and
    #: addressed. False whenever which device this is stays open.
    identity_resolved: bool
    #: None = unreadable or unrecognised. NEVER collapsed into False.
    authorized: bool | None
    #: None = `boltd`'s enrolment state could not be established.
    enrolled: bool | None
    #: Sanitized, "" when the identity is unresolved.
    vendor: str
    model: str
    #: INTERNAL ONLY. A hardware unique identifier; `SAFETY_INVARIANTS` #12
    #: keeps it out of every payload, popup, diagnostic and log line. The
    #: delivery facade converts it to an opaque attachment token and never
    #: emits this.
    uuid: str


#: The scan did not finish. Nothing below `present` can be claimed from it.
_SCAN_FAILED = ObservedAttachment(
    present=None,
    identity_resolved=False,
    authorized=None,
    enrolled=None,
    vendor="",
    model="",
    uuid="",
)
#: The scan finished and there is no attachable router. A real answer.
_NO_DEVICE = ObservedAttachment(
    present=False,
    identity_resolved=False,
    authorized=None,
    enrolled=None,
    vendor="",
    model="",
    uuid="",
)
#: Something is attached and no single router is the answer.
_AMBIGUOUS = ObservedAttachment(
    present=True,
    identity_resolved=False,
    authorized=None,
    enrolled=None,
    vendor="",
    model="",
    uuid="",
)


class DeviceAuthorizationObserver:
    """Observe one Thunderbolt attachment's trust state. Changes nothing."""

    def __init__(
        self,
        thunderbolt_root: Path = Path("/sys/bus/thunderbolt/devices"),
        bolt_state_root: Path = Path("/var/lib/boltd/devices"),
        run=None,
    ) -> None:
        self._thunderbolt_root = thunderbolt_root
        self._bolt_state_root = bolt_state_root
        self._run = run

    def observe(self) -> ObservedAttachment:
        """What is attached, whether it is trusted, and what is unknown."""
        try:
            entries = sorted(
                self._thunderbolt_root.iterdir(), key=lambda item: item.name
            )
        except OSError:
            # Absent, not a directory, or not readable. All three are the same
            # fact: the look did not happen.
            return _SCAN_FAILED
        routers: list[Path] = []
        for entry in entries:
            if ROUTER_PATTERN.fullmatch(entry.name) is None:
                continue
            if _is_host_route(entry.name):
                continue
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                # A candidate that could not even be classified leaves the walk
                # unfinished, and an inventory that stopped early must not be
                # returned as though it were exhaustive.
                return _SCAN_FAILED
            routers.append(entry)
            if len(routers) > 1:
                # A second one settles it. Nothing further is worth reading.
                break
        if not routers:
            return _NO_DEVICE
        if len(routers) > 1:
            return _AMBIGUOUS
        return self._describe(routers[0])

    def _describe(self, router: Path) -> ObservedAttachment:
        """The single attached router, read attribute by attribute."""
        raw_authorized = _read_text(router / "authorized")
        authorized = (
            None if raw_authorized not in ("0", "1") else raw_authorized == "1"
        )
        uuid = _device_uuid(_read_text(router / "unique_id"))
        # The descriptors are rendered safe and otherwise passed through. What
        # the device chose to write there is the device's disclosure, and the
        # module docstring says why nothing here second-guesses it.
        model = _sanitized(_read_text(router / "device_name"))
        vendor = _sanitized(_read_text(router / "vendor_name"))
        # Named AND addressable, or neither. A device that can be shown but not
        # enrolled produces a prompt whose yes does nothing; one that can be
        # enrolled but not named produces a dialog that cannot say what it is
        # about. The names are dropped along with the identity so that no
        # caller can show half of one.
        identity_resolved = bool(model) and bool(uuid)
        if not identity_resolved:
            vendor = ""
            model = ""
        return ObservedAttachment(
            present=True,
            identity_resolved=identity_resolved,
            authorized=authorized,
            enrolled=self._enrolled(uuid),
            vendor=vendor,
            model=model,
            uuid=uuid,
        )

    def _enrolled(self, uuid: str) -> bool | None:
        """Whether `boltd` has this device stored.

        The stored-device directory is preferred over asking `boltctl`: it is
        the database itself rather than a rendering of it, needs no subprocess,
        and cannot be confused by a version whose output format moved. A
        listing that succeeded and does not name the device is a real False.
        A listing that failed is not -- it is the question going unanswered,
        and the command is asked only then.
        """
        if not uuid:
            # No addressable identity, so there is nothing to look up. A
            # question never asked is not a negative answer.
            return None
        try:
            for entry in self._bolt_state_root.iterdir():
                if entry.name.casefold() == uuid:
                    return True
        except OSError:
            return self._enrolled_by_command(uuid)
        return False

    def _enrolled_by_command(self, uuid: str) -> bool | None:
        """`boltctl list`, when `boltd`'s directory could not be read.

        Every failure mode here is None rather than False: no runner injected,
        the call raising, a non-zero exit, output that is not text, a device
        this parser could not find, and a `stored` field in a form this does
        not recognise. Each of those is "not established", and an
        unestablished enrolment declines the prompt rather than offering an
        enrolment that may be a duplicate.

        The *whole* interaction with the injected runner is inside the guard,
        not just the call. A result object is somebody else's code too, and a
        `returncode` or `stdout` that raises on attribute access used to
        propagate straight out of `observe()` -- the one thing the paragraph
        above promises cannot happen.
        """
        if self._run is None:
            return None
        try:
            completed = self._run(BOLTCTL_LIST)
            returncode = getattr(completed, "returncode", None)
            output = getattr(completed, "stdout", None)
            if type(output) is bytes:
                output = output.decode("utf-8", errors="replace")
        except Exception:
            # An injected callable is somebody else's code. It failing is a
            # reading that did not happen, never a crash out of an observation.
            return None
        if returncode != 0:
            return None
        if type(output) is not str:
            return None
        return _stored_flag(output, uuid)


def _blocks(output: str) -> list[dict[str, list[str]]] | None:
    """A listing split into device blocks, or None if it cannot be split.

    A header line -- anything that is not a field line -- opens a block, and
    every field line after it belongs to that block until the next header.
    That is the whole grammar, and it is the grammar `boltd` renders a device's
    own name into: the name sits on the header, so a name carrying newlines
    writes extra lines of *this* shape. It cannot be told apart from the real
    thing line by line, which is why nothing here tries; the caller settles it
    by refusing every listing whose blocks are not unambiguous.

    Because a header is "not a field line", the field-key grammar has to admit
    every key `boltctl` really prints -- `rx speed:`, `tx speed:` and
    `dbus path:` included. A key this does not recognise is not ignored, it
    opens a block, and three spurious blocks per device is how a truthful
    listing stopped being attributable at all.

    Splitting is on "\\n" alone rather than `str.splitlines`, which also breaks
    on `\\x0b`, `\\x1c` and `\\u2028`. Those are not line breaks to the program
    that wrote this text, and a parser that saw line breaks its source did not
    would be a second injection route opened by the reader.
    """
    lines = output.split("\n")
    if len(lines) > MAX_COMMAND_LINES:
        # Truncated is unparsed. Answering from the part that fit would report
        # "not stored" for a device further down the list.
        return None
    blocks: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] | None = None
    for raw_line in lines:
        line = raw_line.rstrip("\r")
        if not line.strip():
            continue
        match = FIELD_LINE.fullmatch(line)
        if match is None:
            current = {field: [] for field in READ_FIELDS}
            blocks.append(current)
            continue
        field = match.group(1).casefold()
        if field not in READ_FIELDS:
            continue
        if current is None:
            # A field with no device above it belongs to nothing, and a value
            # that cannot be attributed cannot be reported.
            return None
        current[field].append(match.group(2).strip().casefold())
    return blocks


def _stored_flag(output: str, uuid: str) -> bool | None:
    """Read one device's `stored` field out of `boltctl list` output.

    Every listing is walked to the end before anything is returned, because
    what disqualifies an answer may be printed after it: the ambiguity that
    matters most is one uuid appearing in two blocks, which is what a device
    naming itself into somebody else's block produces.

    Refused, each as None: a uuid appearing more than once anywhere; a block
    claiming more than one device; a `stored` line in a block that names no
    device; a `uuid` value that is not uuid-shaped; the device's own block
    answering other than exactly once; and a `stored` value that is not the
    literal "yes" or "no" -- some `boltctl` versions print a timestamp there,
    and inferring "stored" from the presence of a field is the guess this
    module refuses to make about the enrolment database.

    A device that the listing does not name is None too, not False. The device
    is attached; its absence from a listing of attached devices says the
    listing was not understood, not that it is unstored.
    """
    blocks = _blocks(output)
    if blocks is None:
        return None
    seen: set[str] = set()
    answer: bool | None = None
    for block in blocks:
        named = block["uuid"]
        stored = block["stored"]
        if len(named) > 1:
            # One block, two devices. Which one the rest of it describes is
            # exactly the question a fabricated line is asking us to get wrong.
            return None
        for value in named:
            if UUID_PATTERN.fullmatch(value) is None:
                return None
            if value in seen:
                return None
            seen.add(value)
        if stored and not named:
            return None
        if not named or named[0] != uuid:
            continue
        if len(stored) != 1 or stored[0] not in ("yes", "no"):
            return None
        answer = stored[0] == "yes"
    return answer
