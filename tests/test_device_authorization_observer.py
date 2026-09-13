"""Reading a Thunderbolt attachment without ever answering for it.

Almost every case here is about an unknown staying unknown.  The adapter feeds
a prompt that grants a device direct access to system memory, so the two
failure shapes that matter are the ones where a gap in the reading turns into a
confident answer: a scan that could not run reading as "no device attached",
and a file that could not be read reading as "not authorized" or "not
enrolled".  Both produce a plausible-looking result, and both are wrong in the
direction that costs somebody something.

There is a third shape, and it took three passes to see: a *refusal* that turns
into a confident answer.  A rule that blanked a descriptor it disliked set
`identity_resolved` False, and a False there is not a warning -- the domain
declines with `identity_unresolved` and the dock never gets its prompt at all.
`RealDocksAreNeverRefused` is the corpus that disqualified that rule: four
shipping Thunderbolt docks whose ordinary marketing names were refused by it,
every one of them named, addressable and unenrolled.  A silent refusal of real
hardware is the exact failure this feature exists to prevent, so those names
stay here permanently.

Every tree is built under a per-test temporary directory, exposed as
`self.tmp_path` -- the name pytest gives the same thing, because the rule it
enforces is the same rule: nothing in this file touches the real `/sys`, and no
test can see another's tree.  The cases are `unittest.TestCase` rather than
bare pytest functions so that both runners execute them: `pytest` collects
`TestCase` classes, and the repository's own gate
(`python -m unittest discover -s tests -v`, which has no pytest installed)
would otherwise import-error on this file and take the whole suite with it.

`ALineInjectableListing` is about text the device itself wrote: a `boltctl`
listing is attacker-influenced, because `boltd` prints a stored device's name
into it verbatim.  It drives the parser in both directions -- the truthful
"stored: no" device reported as enrolled, and the truthfully stored device
reported as not enrolled.  `ARealBoltctlListing` is its other half, and the
half that was missing: the listing `boltctl` actually prints, tree glyphs and
two-word keys included, has to come back with True or False rather than an
abstention.

Every UUID here is an obviously-synthetic placeholder.  A router UUID is a
hardware unique identifier and `SAFETY_INVARIANTS` #12 keeps real ones out of
fixtures as firmly as out of payloads.
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos import device_authorization_observer  # noqa: E402
from regear.adapters.steamos.device_authorization_observer import (  # noqa: E402
    FIELD_LINE,
    MAX_NAME,
    ROUTER_PATTERN,
    DeviceAuthorizationObserver,
    ObservedAttachment,
)


#: Obviously synthetic, and shaped exactly as `boltctl` requires.
DEVICE_UUID = "aaaaaaaa-1111-2222-3333-444444444444"
SECOND_UUID = "bbbbbbbb-5555-6666-7777-888888888888"
#: A third, equally synthetic, written so that no run of it repeats. The two
#: above are runs of one character each, which makes them their own reverse in
#: every window; a leak test written against one of those measures nothing.
VARIED_UUID = "abcdef01-2345-6789-abcd-ef0123456789"
#: The domain's own id, which `boltctl list` prints under `status:`. It is a
#: uuid in the text that is not a device's uuid, which is one reason the parser
#: reads values only out of the field names it asked for.
DOMAIN_UUID = "cccccccc-9999-0000-1111-222222222222"
#: A stand-in product string. Two docks of one model publish the same one,
#: which is the whole reason the ambiguity rule exists.
MODEL = "Tapex Creek Dock"
VENDOR = "Tapex"

#: Sysfs attribute names are the only strings this adapter may append to a
#: router path. Anything else in that position is a new file being read.
PERMITTED_ATTRIBUTES = {"authorized", "unique_id", "device_name", "vendor_name"}

#: Retimer ids contain a colon, which Windows path names forbid. The router
#: shape is pinned separately and runs everywhere; only the filesystem case is
#: skipped, exactly as the dock-branch suite does for PCI-shaped paths.
REQUIRES_COLON_PATHS = unittest.skipUnless(
    os.name != "nt", "retimer ids need a filesystem allowing colons"
)


def normalized(value: str) -> str:
    """Lowercase, and nothing but ASCII letters and digits.

    Written out here rather than imported so that a comparison cannot borrow
    its normalizer from the module it is checking and miss that normalizer
    being weakened.
    """
    return "".join(
        character
        for character in value.casefold()
        if "a" <= character <= "z" or "0" <= character <= "9"
    )


def hex_class_length(*values: str) -> int:
    """How many hex-class characters some text reduces to.

    This is the arithmetic of the content filter that used to live in the
    module, kept here for one purpose: to state, in the corpus below, *how far
    over the old limit a real dock's own name goes*.  It measures the evidence
    that disqualified the rule.  Nothing in the adapter computes it any more,
    and `TheFilterIsGone` fails if anything starts to again.
    """
    return sum(
        1
        for value in values
        for character in value.casefold()
        if "a" <= character <= "f" or "0" <= character <= "9"
    )


#: How much of an identifier may coincide with ordinary text before it stops
#: being a coincidence.  Measured, not guessed: across every product string in
#: the corpus below and both synthetic ids, the longest accidental overlap is
#: two characters ("de", out of "Dell Technologies").  Asserting an overlap of
#: exactly zero would be asserting that no label contains the letter "a".
LONGEST_COINCIDENCE = 4


def surviving_id_run(text: str, uuid: str) -> str:
    """The longest stretch of the uuid's own characters left in `text`.

    Both sides are normalized first, so a leak cannot hide behind separators:
    "aaaaaaaa-1111", "aaaaaaaa\t1111" and "aaaaaaaa 1111" all count as the
    same twelve characters of a hardware identifier.
    """
    identity = normalized(uuid)
    candidate = normalized(text)
    longest = ""
    for start in range(len(identity)):
        for end in range(start + len(longest) + 1, len(identity) + 1):
            run = identity[start:end]
            if run in candidate:
                longest = run
    return longest


def module_source() -> str:
    return Path(device_authorization_observer.__file__).read_text(encoding="utf-8")


def module_docstring() -> str:
    return " ".join(ast.get_docstring(ast.parse(module_source())).split())


class Sysfs:
    """A Thunderbolt tree and a `boltd` store, shaped like the real ones."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.thunderbolt = root / "thunderbolt"
        self.bolt = root / "bolt"
        self.thunderbolt.mkdir(parents=True, exist_ok=True)
        self.bolt.mkdir(parents=True, exist_ok=True)
        # A domain entry and a host router, which every real tree carries, so
        # that no case passes by looking at an unrealistically bare directory.
        (self.thunderbolt / "domain0").mkdir(exist_ok=True)
        self.router("0-0", device_name="Ally X", unique_id=SECOND_UUID)

    def observer(self, run=None) -> DeviceAuthorizationObserver:
        return DeviceAuthorizationObserver(self.thunderbolt, self.bolt, run=run)

    def router(
        self,
        name: str = "0-1",
        *,
        authorized: str | None = "0",
        unique_id: str | None = DEVICE_UUID,
        device_name: str | None = MODEL,
        vendor_name: str | None = VENDOR,
    ) -> Path:
        path = self.thunderbolt / name
        path.mkdir(parents=True, exist_ok=True)
        attributes = {
            "authorized": authorized,
            "unique_id": unique_id,
            "device_name": device_name,
            "vendor_name": vendor_name,
        }
        for attribute, value in attributes.items():
            if value is not None:
                (path / attribute).write_text(value, encoding="utf-8")
        return path

    def store(self, *uuids: str) -> None:
        for uuid in uuids:
            (self.bolt / uuid).write_text("[device]\n", encoding="utf-8")

    def snapshot(self) -> set[tuple[str, int]]:
        """Every path under the tree and its size, for a no-write check."""
        return {
            (
                str(path.relative_to(self.root)),
                path.stat().st_size if path.is_file() else -1,
            )
            for path in sorted(self.root.rglob("*"))
        }


class ObserverCase(unittest.TestCase):
    """One isolated temporary tree per test."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        #: The per-test temporary directory. No case reaches outside it, and
        #: nothing here ever reads the machine's real /sys.
        self.tmp_path = Path(directory.name)
        self.sysfs = Sysfs(self.tmp_path)

    def observe(self, run=None) -> ObservedAttachment:
        return self.sysfs.observer(run=run).observe()


class Run:
    """A stand-in for the injected command runner."""

    def __init__(self, returncode=0, stdout="", raises=None, result=None) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.raises = raises
        self.result = result
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv):
        self.calls.append(tuple(argv))
        if self.raises is not None:
            raise self.raises
        return self if self.result is None else self.result


class RaisingResult:
    """A result object whose attribute access raises.

    An injected runner can return anything.  A `subprocess.CompletedProcess`
    reads its fields off a struct, but a lazy wrapper around a pipe -- the
    obvious way to write one -- does the read when the attribute is touched,
    and that read can fail long after the call returned.
    """

    def __init__(self, error: BaseException, *, attribute: str = "returncode") -> None:
        self._error = error
        self._attribute = attribute

    @property
    def returncode(self):
        if self._attribute == "returncode":
            raise self._error
        return 0

    @property
    def stdout(self):
        if self._attribute == "stdout":
            raise self._error
        return listing(DEVICE_UUID, "yes")


#: The tree glyphs `boltctl` draws a device block with, in its unicode
#: rendering. None of them opens an entry -- the bullet does -- so all of them
#: are leading noise in front of a field key.
BRANCH = "\u251c\u2500"
LAST = "\u2514\u2500"
PIPE = "\u2502"


def listing(
    uuid: str,
    stored: str,
    *,
    name: str = MODEL,
    bullet: str = "\u25cf",
    branch: str = BRANCH,
    last: str = LAST,
    pipe: str = PIPE,
) -> str:
    """One device block in the shape `boltctl list` really prints.

    Taken from the real command's output rather than abbreviated from it, and
    that is the point.  `rx speed:`, `tx speed:` and `dbus path:` are two-word
    keys; a field grammar that accepted only single-word keys read each of
    those three lines as a device header, opened a block for it, and left the
    `stored:` line underneath attributed to a block naming no device.  The
    parser then answered None for a listing that was entirely truthful.
    """
    return (
        f" {bullet} {name}\n"
        f"   {branch} type:          peripheral\n"
        f"   {branch} name:          {name}\n"
        f"   {branch} vendor:        {VENDOR}\n"
        f"   {branch} uuid:          {uuid}\n"
        f"   {branch} dbus path:     /org/freedesktop/bolt/devices/"
        f"{uuid.replace('-', '_')}\n"
        f"   {branch} generation:    Thunderbolt 3\n"
        f"   {branch} status:        connected\n"
        f"   {pipe}  {branch} domain:     {DOMAIN_UUID}\n"
        f"   {pipe}  {branch} rx speed:   40 Gb/s = 2 lanes * 20 Gb/s\n"
        f"   {pipe}  {branch} tx speed:   40 Gb/s = 2 lanes * 20 Gb/s\n"
        f"   {pipe}  {last} authflags:  none\n"
        f"   {last} stored:        {stored}\n"
    )


def ascii_listing(uuid: str, stored: str, *, name: str = MODEL) -> str:
    """The same block as `boltctl` draws it without unicode glyphs."""
    return listing(
        uuid, stored, name=name, bullet="*", branch="|-", last="|-", pipe="|"
    )


class TheOrdinaryReadings(ObserverCase):
    def test_a_newly_attached_unauthorized_device_reads_as_itself(self) -> None:
        self.sysfs.router()

        observed = self.observe()

        self.assertIs(observed.present, True)
        self.assertIs(observed.identity_resolved, True)
        self.assertIs(observed.authorized, False)
        self.assertIs(observed.enrolled, False)
        self.assertEqual(observed.vendor, VENDOR)
        self.assertEqual(observed.model, MODEL)
        self.assertEqual(observed.uuid, DEVICE_UUID)

    def test_an_authorized_device_reports_authorized(self) -> None:
        self.sysfs.router(authorized="1")

        self.assertIs(self.observe().authorized, True)

    def test_a_hex_route_is_a_router(self) -> None:
        """Routes are hex: "0-303" and "0-70d" are ordinary ids."""
        self.sysfs.router("0-70d")

        observed = self.observe()

        self.assertIs(observed.present, True)
        self.assertIs(observed.identity_resolved, True)

    def test_reading_twice_gives_the_same_answer(self) -> None:
        self.sysfs.router()
        observer = self.sysfs.observer()

        self.assertEqual(observer.observe(), observer.observe())

    def test_observing_writes_nothing(self) -> None:
        """The point of the adapter: reading trust must not change it."""
        self.sysfs.router()
        self.sysfs.store(DEVICE_UUID)
        before = self.sysfs.snapshot()

        self.observe()

        self.assertEqual(self.sysfs.snapshot(), before)


class AuthorizationIsATriState(ObserverCase):
    def test_an_absent_authorized_file_is_unknown_not_unauthorized(self) -> None:
        self.sysfs.router(authorized=None)

        self.assertIsNone(self.observe().authorized)

    def test_an_unreadable_authorized_file_is_unknown(self) -> None:
        router = self.sysfs.router(authorized=None)
        # A directory where a file belongs: the read raises exactly as a
        # permissions failure would, on every platform this suite runs on.
        (router / "authorized").mkdir()

        self.assertIsNone(self.observe().authorized)

    def test_an_empty_authorized_file_is_unknown(self) -> None:
        self.sysfs.router(authorized="")

        self.assertIsNone(self.observe().authorized)

    def test_an_unrecognised_authorized_value_is_unknown(self) -> None:
        """Key-based authorization publishes "2". Unknown declines; guessing
        either way is a claim about memory access nobody verified."""
        for value in ("2", "yes", "01", "1\n1"):
            with self.subTest(authorized=value):
                self.sysfs.router(authorized=value)
                self.assertIsNone(self.observe().authorized)

    def test_an_unreadable_state_still_leaves_the_device_present(self) -> None:
        self.sysfs.router(authorized=None)

        observed = self.observe()

        self.assertIs(observed.present, True)
        self.assertIs(observed.identity_resolved, True)


@contextlib.contextmanager
def unclassifiable(name: str, error: OSError):
    """Make one directory entry refuse to be classified, and leave the rest real.

    `Path.is_dir()` answers False for the errors that mean "there is no such
    thing" -- ENOENT, ENOTDIR, ELOOP -- and re-raises every other one, so a
    candidate whose `stat` comes back EACCES or EIO raises out of the
    classification rather than being classified by it.  That is the entry this
    produces: router-shaped, not the host route, and neither a directory nor
    not one.  A router that vanished mid-walk is not this case -- ENOENT is
    one of the swallowed ones and answers False -- which is why the errors
    used below are the two that a real sysfs raises: a permission the process
    does not have over the entry, and a controller whose read fails outright.

    Only the named entry is affected.  Every other path is classified by the
    real implementation, so what the walk sees around the unreadable candidate
    is a real tree rather than a stub that answers for everything.
    """
    classify = Path.is_dir

    def refusing(self, *arguments, **keywords):
        if self.name == name:
            raise error
        return classify(self, *arguments, **keywords)

    with patch.object(Path, "is_dir", refusing):
        yield


class PresenceIsATriState(ObserverCase):
    def test_a_missing_root_is_a_failed_scan_not_an_absence(self) -> None:
        observer = DeviceAuthorizationObserver(
            self.tmp_path / "absent", self.tmp_path / "bolt", run=None
        )

        observed = observer.observe()

        self.assertIsNone(observed.present)
        self.assertIsNot(observed.present, False)
        self.assertIs(observed.identity_resolved, False)
        self.assertIsNone(observed.authorized)
        self.assertIsNone(observed.enrolled)
        self.assertEqual(observed.vendor, "")
        self.assertEqual(observed.model, "")
        self.assertEqual(observed.uuid, "")

    def test_a_root_that_is_not_a_directory_is_a_failed_scan(self) -> None:
        root = self.tmp_path / "file-not-a-root"
        root.write_text("", encoding="utf-8")

        observed = DeviceAuthorizationObserver(root, self.tmp_path / "bolt").observe()

        self.assertIsNone(observed.present)

    def test_a_candidate_that_cannot_be_classified_is_a_failed_scan(self) -> None:
        """The walk reached a router-shaped entry and could not find out
        whether it was a directory at all.  A scan that could not classify
        what it found did not finish, and an unfinished scan is None: False
        here tells a player whose dock is sitting there plugged in that there
        is nothing attached, and no prompt ever arrives."""
        self.sysfs.router("0-1")

        with unclassifiable("0-1", PermissionError(13, "stat refused")):
            observed = self.observe()

        self.assertIsNone(observed.present)
        # The distinction is the whole point of the tri-state: None is a scan
        # that failed, False is a scan that finished and found nothing.
        self.assertIsNot(observed.present, False)
        self.assertIs(observed.identity_resolved, False)
        self.assertIsNone(observed.authorized)
        self.assertIsNone(observed.enrolled)
        self.assertEqual(observed.vendor, "")
        self.assertEqual(observed.model, "")
        self.assertEqual(observed.uuid, "")

    def test_an_unclassifiable_candidate_stops_an_otherwise_good_walk(self) -> None:
        """The costlier half of the same rule.  A readable router was found
        first, so an inventory that stopped early still has something in it --
        and returning that would be reporting a partial walk as though it were
        exhaustive.  The entry it could not classify may have been a second
        router, which is the case that must never resolve to one named
        device: naming this dock in a memory-access dialog while another one
        sits unaccounted for is exactly the ambiguity `_AMBIGUOUS` exists
        for."""
        self.sysfs.router("0-1")
        self.sysfs.router("0-3", unique_id=SECOND_UUID)

        with unclassifiable("0-3", OSError(5, "I/O error")):
            observed = self.observe()

        self.assertIsNone(observed.present)
        self.assertIs(observed.identity_resolved, False)
        self.assertEqual(observed.model, "")
        self.assertEqual(observed.vendor, "")
        self.assertEqual(observed.uuid, "")

    def test_an_empty_root_is_a_finished_scan_that_found_nothing(self) -> None:
        observed = self.observe()

        self.assertIs(observed.present, False)
        self.assertIs(observed.identity_resolved, False)
        self.assertIsNone(observed.authorized)
        self.assertIsNone(observed.enrolled)

    def test_the_host_router_is_not_an_attachment(self) -> None:
        """`0-0` and `1-0` are the machine's own controllers and are always
        there. Counting one would offer to trust the handheld to itself."""
        self.sysfs.router("1-0", device_name="Ally X", unique_id=SECOND_UUID)

        self.assertIs(self.observe().present, False)

    def test_a_domain_entry_is_not_a_router(self) -> None:
        (self.sysfs.thunderbolt / "domain1").mkdir()

        self.assertIs(self.observe().present, False)

    def test_a_stray_file_in_the_root_is_not_a_router(self) -> None:
        (self.sysfs.thunderbolt / "0-9").write_text("", encoding="utf-8")

        self.assertIs(self.observe().present, False)

    @REQUIRES_COLON_PATHS
    def test_a_retimer_directory_is_not_a_router(self) -> None:
        (self.sysfs.thunderbolt / "0-1:1.2").mkdir()

        self.assertIs(self.observe().present, False)

    def test_only_router_shaped_names_are_candidates(self) -> None:
        """The filesystem case above cannot run where a path may not contain
        a colon, and the rule is not platform-specific, so the shape is
        pinned here as well."""
        for name in (
            "domain0",
            "domain12",
            "0-1:1.2",
            "0-0:3.1",
            "0-",
            "-1",
            "0-1.2",
            "usb1",
            "",
        ):
            with self.subTest(name=name):
                self.assertIsNone(ROUTER_PATTERN.fullmatch(name))
        for name in ("0-1", "0-3", "1-303", "0-70d", "12-1"):
            with self.subTest(name=name):
                self.assertIsNotNone(ROUTER_PATTERN.fullmatch(name))

    def test_the_host_router_is_skipped_while_a_real_one_is_read(self) -> None:
        self.sysfs.router("1-0", device_name="Ally X", unique_id=SECOND_UUID)
        self.sysfs.router("0-1")

        observed = self.observe()

        self.assertIs(observed.present, True)
        self.assertIs(observed.identity_resolved, True)
        self.assertEqual(observed.model, MODEL)


class TwoRoutersNoAnswer(ObserverCase):
    def test_two_routers_with_the_same_name_refuse_to_be_identified(self) -> None:
        """Two identical docks publish one product string. Naming either in a
        memory-access dialog and acting on the other is the failure."""
        self.sysfs.router("0-1", unique_id=DEVICE_UUID)
        self.sysfs.router("0-3", unique_id=SECOND_UUID)

        observed = self.observe()

        self.assertIs(observed.present, True)
        self.assertIs(observed.identity_resolved, False)
        self.assertIsNone(observed.authorized)
        self.assertIsNone(observed.enrolled)
        self.assertEqual(observed.vendor, "")
        self.assertEqual(observed.model, "")
        self.assertEqual(observed.uuid, "")

    def test_two_differently_named_routers_also_refuse(self) -> None:
        """Unlike `dock_branch.observe_tunnel`, nothing tells this adapter
        which name the caller meant, so sort order would be the only
        tie-break, and sort order is not evidence."""
        self.sysfs.router("0-1", device_name=MODEL, unique_id=DEVICE_UUID)
        self.sysfs.router(
            "0-3", device_name="Cedar Fork Enclosure", unique_id=SECOND_UUID
        )

        observed = self.observe()

        self.assertIs(observed.present, True)
        self.assertIs(observed.identity_resolved, False)
        self.assertEqual(observed.uuid, "")

    def test_an_ambiguous_scan_never_reports_unauthorized(self) -> None:
        self.sysfs.router("0-1", authorized="0", unique_id=DEVICE_UUID)
        self.sysfs.router("0-3", authorized="0", unique_id=SECOND_UUID)

        self.assertIsNone(self.observe().authorized)

    def test_a_host_router_does_not_make_one_device_ambiguous(self) -> None:
        """The regression this guards: skipping the host is what keeps a
        single attached dock from reading as two routers."""
        self.sysfs.router("0-1")

        self.assertIs(self.observe().identity_resolved, True)


class Identity(ObserverCase):
    def test_an_unnamed_device_is_not_identified(self) -> None:
        self.sysfs.router(device_name=None)

        observed = self.observe()

        self.assertIs(observed.present, True)
        self.assertIs(observed.identity_resolved, False)
        self.assertEqual(observed.vendor, "")
        self.assertEqual(observed.model, "")
        self.assertIs(observed.authorized, False)

    def test_a_device_with_no_readable_id_is_not_identified(self) -> None:
        """Without a `unique_id` there is nothing to hand `boltctl`, so a yes
        would do nothing. The names go with the identity."""
        self.sysfs.router(unique_id=None)

        observed = self.observe()

        self.assertIs(observed.identity_resolved, False)
        self.assertEqual(observed.uuid, "")
        self.assertEqual(observed.model, "")

    def test_a_malformed_id_is_refused_here_not_at_the_command_line(self) -> None:
        for raw in ("not-a-uuid", DEVICE_UUID[:-1], DEVICE_UUID + "0", "", "   "):
            with self.subTest(unique_id=raw):
                self.sysfs.router(unique_id=raw)
                observed = self.observe()
                self.assertIs(observed.identity_resolved, False)
                self.assertEqual(observed.uuid, "")

    def test_an_uppercase_id_is_normalized(self) -> None:
        self.sysfs.router(unique_id=DEVICE_UUID.upper())

        observed = self.observe()

        self.assertIs(observed.identity_resolved, True)
        self.assertEqual(observed.uuid, DEVICE_UUID)

    def test_a_missing_vendor_name_still_identifies_the_device(self) -> None:
        """Plenty of hardware publishes no vendor string. A model and an id
        are enough to both name and address it."""
        self.sysfs.router(vendor_name=None)

        observed = self.observe()

        self.assertIs(observed.identity_resolved, True)
        self.assertEqual(observed.vendor, "")
        self.assertEqual(observed.model, MODEL)

    def test_an_unidentified_device_is_never_looked_up_in_the_store(self) -> None:
        self.sysfs.router(unique_id=None)
        self.sysfs.store(DEVICE_UUID)

        self.assertIsNone(self.observe().enrolled)

    def test_identity_resolved_is_about_naming_and_nothing_else(self) -> None:
        """The meaning the field went back to.  A readable name and one
        router is the whole test; no property of the *content* of that name
        takes a device out of the dialog."""
        for model in (
            MODEL,
            "Dock " * 12,
            "4A11",
            "deadbeefcafe",
            "0123456789abcdef0123456789abcdef",
        ):
            with self.subTest(model=model):
                self.sysfs.router(device_name=model)

                observed = self.observe()

                self.assertIs(observed.identity_resolved, True)
                self.assertTrue(observed.model)


class Enrolment(ObserverCase):
    def test_a_stored_device_reads_as_enrolled(self) -> None:
        self.sysfs.router()
        self.sysfs.store(DEVICE_UUID)

        self.assertIs(self.observe().enrolled, True)

    def test_a_readable_store_without_the_device_reads_as_not_enrolled(self) -> None:
        """A listing that succeeded is a real answer, and this is the one
        place the adapter is allowed to say False about enrolment."""
        self.sysfs.router()
        self.sysfs.store(SECOND_UUID)

        self.assertIs(self.observe().enrolled, False)

    def test_an_empty_store_reads_as_not_enrolled(self) -> None:
        self.sysfs.router()

        self.assertIs(self.observe().enrolled, False)

    def test_a_stored_name_in_another_case_still_matches(self) -> None:
        self.sysfs.router()
        self.sysfs.store(DEVICE_UUID.upper())

        self.assertIs(self.observe().enrolled, True)

    def test_a_missing_store_directory_is_unknown_not_unenrolled(self) -> None:
        self.sysfs.router()
        self.sysfs.bolt.rmdir()

        self.assertIsNone(self.observe().enrolled)

    def test_a_store_that_is_not_a_directory_is_unknown(self) -> None:
        self.sysfs.router()
        self.sysfs.bolt.rmdir()
        self.sysfs.bolt.write_text("", encoding="utf-8")

        self.assertIsNone(self.observe().enrolled)


class TheBoltctlFallback(ObserverCase):
    def unreadable_store(self) -> None:
        self.sysfs.router()
        self.sysfs.bolt.rmdir()

    def test_the_command_is_asked_only_when_the_store_cannot_be_read(self) -> None:
        self.sysfs.router()
        self.sysfs.store(DEVICE_UUID)
        run = Run(stdout=listing(DEVICE_UUID, "no"))

        observed = self.observe(run=run)

        self.assertIs(observed.enrolled, True)
        self.assertEqual(run.calls, [])

    def test_the_command_answers_when_the_store_is_unreadable(self) -> None:
        self.unreadable_store()
        run = Run(stdout=listing(DEVICE_UUID, "yes"))

        observed = self.observe(run=run)

        self.assertIs(observed.enrolled, True)
        self.assertEqual(run.calls[0][1], "list")

    def test_the_command_can_report_a_device_that_is_not_stored(self) -> None:
        self.unreadable_store()

        observed = self.observe(run=Run(stdout=listing(DEVICE_UUID, "no")))

        self.assertIs(observed.enrolled, False)

    def test_a_non_zero_exit_is_unknown(self) -> None:
        self.unreadable_store()
        run = Run(returncode=1, stdout=listing(DEVICE_UUID, "yes"))

        self.assertIsNone(self.observe(run=run).enrolled)

    def test_a_runner_that_raises_is_unknown(self) -> None:
        """An injected callable is somebody else's code. Whatever it raises,
        an observation must come back with an unknown rather than a crash."""
        self.unreadable_store()

        for error in (OSError("no such command"), RuntimeError("broken"), ValueError()):
            with self.subTest(error=type(error).__name__):
                self.assertIsNone(self.observe(run=Run(raises=error)).enrolled)

    def test_a_result_whose_attributes_raise_is_unknown(self) -> None:
        """The reproduced crash path.  Only the call used to sit inside the
        guard; the `returncode` and `stdout` reads sat outside it, so a runner
        that returned a lazy result object raised straight out of `observe()`.
        A reading that did not happen is None, and an observation never
        crashes -- an exception here reaches the caller of a *read-only*
        adapter, where nothing is prepared for one."""
        self.unreadable_store()

        for attribute in ("returncode", "stdout"):
            for error in (
                RuntimeError("pipe closed"),
                OSError("read failed"),
                ValueError(),
                AttributeError("not populated"),
            ):
                with self.subTest(attribute=attribute, error=type(error).__name__):
                    run = Run(
                        result=RaisingResult(error, attribute=attribute)
                    )

                    self.assertIsNone(self.observe(run=run).enrolled)

    def test_a_result_whose_attributes_raise_still_reports_the_device(self) -> None:
        """The rest of the reading survives it: the crash used to take the
        whole observation down, including the attachment that was read
        successfully before `boltctl` was ever asked."""
        self.unreadable_store()
        run = Run(result=RaisingResult(RuntimeError("pipe closed")))

        observed = self.observe(run=run)

        self.assertIs(observed.present, True)
        self.assertIs(observed.identity_resolved, True)
        self.assertEqual(observed.model, MODEL)
        self.assertIsNone(observed.enrolled)

    def test_output_that_is_not_text_is_unknown(self) -> None:
        self.unreadable_store()

        for value in (None, 7, ["stored: yes"]):
            with self.subTest(stdout=value):
                self.assertIsNone(self.observe(run=Run(stdout=value)).enrolled)

    def test_byte_output_is_decoded(self) -> None:
        self.unreadable_store()
        run = Run(stdout=listing(DEVICE_UUID, "yes").encode("utf-8"))

        self.assertIs(self.observe(run=run).enrolled, True)

    def test_output_naming_another_device_only_is_unknown(self) -> None:
        """The device is attached, so its absence from the listing means the
        listing was not understood -- not that the device is unstored."""
        self.unreadable_store()
        run = Run(stdout=listing(SECOND_UUID, "yes"))

        self.assertIsNone(self.observe(run=run).enrolled)

    def test_an_unrecognised_stored_field_is_unknown(self) -> None:
        """Some `boltctl` versions print a timestamp there. Inferring
        "stored" from the presence of the field is the guess this refuses."""
        self.unreadable_store()
        run = Run(stdout=listing(DEVICE_UUID, "Tue 01 Jan 2030 00:00:00 UTC"))

        self.assertIsNone(self.observe(run=run).enrolled)

    def test_unparseable_output_is_unknown(self) -> None:
        self.unreadable_store()

        for output in ("", "boltctl: could not connect to the daemon\n", "\n\n"):
            with self.subTest(stdout=output):
                self.assertIsNone(self.observe(run=Run(stdout=output)).enrolled)

    def test_the_right_device_is_read_out_of_a_multi_device_listing(self) -> None:
        self.unreadable_store()
        run = Run(stdout=listing(SECOND_UUID, "yes") + listing(DEVICE_UUID, "no"))

        self.assertIs(self.observe(run=run).enrolled, False)

    def test_no_runner_leaves_an_unreadable_store_unknown(self) -> None:
        self.unreadable_store()

        self.assertIsNone(self.observe().enrolled)


class ARealBoltctlListing(ObserverCase):
    """The listing `boltctl` actually prints has to get a real answer.

    The reproduced failure: `boltctl list` prints two-word field keys --
    `rx speed:` and `tx speed:` under `status:`, and `dbus path:` beside the
    uuid.  The field grammar accepted single-word keys only, so each of those
    lines failed to parse as a field and was therefore read as a *device
    header*, opening a block of its own.  The `stored:` line printed after them
    landed in a block that named no device, which is an unattributable
    `stored` -- and unattributable is None.

    So a completely truthful listing for a genuinely unstored dock answered
    None instead of False, and a truthful `stored: yes` answered None instead
    of True.  Both are the fallback abstaining on the only output it will ever
    be given, which makes the fallback dead code that looks alive.

    An abstention is not a safe default here.  None declines the prompt, so the
    dock whose `boltd` directory is unreadable -- exactly the machine this
    fallback exists for -- never gets one.
    """

    def unreadable_store(self) -> None:
        self.sysfs.router()
        self.sysfs.bolt.rmdir()

    def test_a_truthful_listing_answers_rather_than_abstaining(self) -> None:
        self.unreadable_store()

        for stored, expected in (("yes", True), ("no", False)):
            with self.subTest(stored=stored):
                run = Run(stdout=listing(DEVICE_UUID, stored))

                self.assertIs(self.observe(run=run).enrolled, expected)

    def test_the_ascii_rendering_answers_too(self) -> None:
        """`boltctl` drops to ASCII glyphs without a UTF-8 locale, and the
        same listing has to read the same way."""
        self.unreadable_store()

        for stored, expected in (("yes", True), ("no", False)):
            with self.subTest(stored=stored):
                run = Run(stdout=ascii_listing(DEVICE_UUID, stored))

                self.assertIs(self.observe(run=run).enrolled, expected)

    def test_the_real_two_word_keys_are_field_lines_not_headers(self) -> None:
        """The specific lines, named.  A regression here is silent -- the
        answer just becomes None -- so the grammar is pinned directly as well
        as through the observer."""
        for line in (
            f"   {PIPE}  {BRANCH} rx speed:   40 Gb/s = 2 lanes * 20 Gb/s",
            f"   {PIPE}  {BRANCH} tx speed:   40 Gb/s = 2 lanes * 20 Gb/s",
            f"   {BRANCH} dbus path:     /org/freedesktop/bolt/devices/x",
            f"   {BRANCH} authflags:  none",
            f"   {BRANCH} generation:    Thunderbolt 3",
            f"   {LAST} stored:        no",
            "   |- rx speed:   40 Gb/s",
            "   |- dbus path:  /org/freedesktop/bolt/devices/x",
        ):
            with self.subTest(line=line):
                self.assertIsNotNone(FIELD_LINE.fullmatch(line))

    def test_a_key_may_carry_digits_and_hyphens(self) -> None:
        """Headroom for the keys a later `boltctl` prints, so that the next
        added field is an ignored line rather than a spurious block."""
        for key in ("uuid", "dbus path", "rx speed", "tb-generation", "usb4 speed"):
            with self.subTest(key=key):
                match = FIELD_LINE.fullmatch(f"   {BRANCH} {key}:  value")

                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), key)

    def test_an_entry_bullet_still_opens_a_device_rather_than_a_field(self) -> None:
        """What the grammar must keep refusing.  A device's own name sits on
        the header line, so a name reading "uuid: ..." must stay a header --
        the bullet, not the key, is what says "new device"."""
        for line in (
            f" \u25cf uuid: {SECOND_UUID}",
            " \u25cb stored: yes",
            " * uuid: not-a-field",
            "   |- * stored: yes",
            "   |- 4 speed: digits first is not a key",
            "   |- 2500: a number is not a key",
            "Tapex Creek Dock",
        ):
            with self.subTest(line=line):
                self.assertIsNone(FIELD_LINE.fullmatch(line))

    def test_a_real_listing_of_two_devices_still_picks_the_right_one(self) -> None:
        self.unreadable_store()
        run = Run(
            stdout=listing(SECOND_UUID, "yes", name="Cedar Fork Enclosure")
            + listing(DEVICE_UUID, "no")
        )

        self.assertIs(self.observe(run=run).enrolled, False)

    def test_the_domain_uuid_in_a_real_listing_is_not_a_device(self) -> None:
        """`status:` carries the domain's own uuid, and `dbus path:` carries
        the device's.  Neither is a `uuid:` field, and reading either as one
        would make every truthful listing ambiguous."""
        self.unreadable_store()
        run = Run(stdout=listing(DEVICE_UUID, "yes"))

        self.assertIs(self.observe(run=run).enrolled, True)


def named_listing(name: str, uuid: str, stored: str) -> str:
    """One device block, with the device's own name where `boltd` prints it.

    `boltctl` renders a stored device's `device_name` verbatim at the head of
    its block, and `boltd` persisted whatever the device published -- newlines
    included.  So this is not a hostile fixture pretending to be output: it is
    what the real command prints for a device with that name.
    """
    return (
        f" * {name}\n"
        "   |- type:     peripheral\n"
        f"   |- uuid:     {uuid}\n"
        "   |- status:   connected\n"
        f"   |- stored:   {stored}\n"
        "      |- policy: auto\n"
    )


#: A device name that closes its own header line and writes two more lines of
#: the listing. Everything after the first newline is the device talking.
def injecting_name(uuid: str, stored: str, *, header: str = "") -> str:
    return (
        "Tapex Creek Dock\n"
        + (f" * {header}\n" if header else "")
        + f"   |- uuid:     {uuid}\n"
        + f"   |- stored:   {stored}\n"
    )


class ALineInjectableListing(ObserverCase):
    """A listing is text a device writes into, so it answers or it abstains.

    `boltd` persists a device's `device_name` and `boltctl` prints it verbatim,
    so a device whose name contains newlines emits whole `uuid:` and `stored:`
    lines into the listing.  Attributing a `stored:` line to whichever `uuid:`
    line preceded it reproduced the failure in both directions, and both are
    below: the dock whose own truthful block says `stored: no` reported as
    enrolled, which is a genuinely new dock never getting its prompt, and the
    dock that is stored reported as not enrolled, which is the duplicate
    enrolment the module docstring says it refuses to guess at.

    Neither is fixed by parsing harder.  A fabricated block is indistinguishable
    from a real one line by line, because it is made of real lines.  What is
    fixed is the answering: the filesystem is the source of truth, and a
    listing that is ambiguous in any way at all -- one uuid in two places, two
    devices in one block, a `stored:` line with nothing above it to attribute
    it to -- says None.  None declines the prompt through the domain's
    enrollment-unreadable branch, which is what an unanswered question should
    do.

    These rules are unchanged by the field-key widening.  Widening decides
    which lines are *fields*; every case here is settled afterwards, by what
    the blocks then contain.
    """

    def unreadable_store(self) -> None:
        self.sysfs.bolt.rmdir()

    def test_the_filesystem_answers_even_when_the_name_is_injecting(self) -> None:
        """First, the part that matters most: the listing is not consulted at
        all while `boltd`'s own directory can be read.  A file name in that
        directory is not a string the device chose."""
        self.sysfs.router(device_name=injecting_name(DEVICE_UUID, "no"))
        self.sysfs.store(DEVICE_UUID)
        run = Run(stdout=named_listing("anything", DEVICE_UUID, "no"))

        observed = self.observe(run=run)

        self.assertIs(observed.enrolled, True)
        self.assertEqual(run.calls, [])
        # The device published a readable name, so it is identified and its
        # name is displayed -- including the id it wrote into that name. See
        # `ADeviceThatNamesItselfAfterItsOwnId` for why that is the device's
        # disclosure rather than a leak this module can prevent.
        self.assertIs(observed.identity_resolved, True)

    def test_a_name_claiming_stored_does_not_enrol_an_unstored_dock(self) -> None:
        """Direction one, and the costlier one: the device's truthful block
        says `stored: no`, its name says yes, and reading yes means a
        genuinely new dock is never offered its prompt."""
        self.sysfs.router()
        self.unreadable_store()
        run = Run(
            stdout=named_listing(
                injecting_name(DEVICE_UUID, "yes"), DEVICE_UUID, "no"
            )
        )

        self.assertIsNone(self.observe(run=run).enrolled)

    def test_a_name_claiming_unstored_does_not_unenrol_a_stored_dock(self) -> None:
        """Direction two: the device is stored, its name says it is not, and
        reading that produces exactly the duplicate enrolment this module says
        it will not guess at."""
        self.sysfs.router()
        self.unreadable_store()
        run = Run(
            stdout=named_listing(
                injecting_name(DEVICE_UUID, "no"), DEVICE_UUID, "yes"
            )
        )

        self.assertIsNone(self.observe(run=run).enrolled)

    def test_an_injection_into_a_real_listing_is_still_ambiguous(self) -> None:
        """The same injection, into the full output shape rather than the
        abbreviated one -- the widened grammar must not have turned a
        fabricated `uuid:`/`stored:` pair into something attributable."""
        self.sysfs.router()
        self.unreadable_store()

        for claimed, truth in (("yes", "no"), ("no", "yes")):
            with self.subTest(claimed=claimed):
                run = Run(
                    stdout=listing(
                        DEVICE_UUID, truth, name=injecting_name(DEVICE_UUID, claimed)
                    )
                )

                self.assertIsNone(self.observe(run=run).enrolled)

    def test_a_fabricated_block_header_does_not_help(self) -> None:
        """The same injection with a bullet, so the fabricated lines open a
        block of their own rather than landing inside the real one. It is a
        well-formed block; it is also the second place one uuid appears."""
        self.sysfs.router()
        self.unreadable_store()

        for stored, truth in (("yes", "no"), ("no", "yes")):
            with self.subTest(claimed=stored):
                run = Run(
                    stdout=named_listing(
                        injecting_name(DEVICE_UUID, stored, header="Fake Dock"),
                        DEVICE_UUID,
                        truth,
                    )
                )

                self.assertIsNone(self.observe(run=run).enrolled)

    def test_one_device_naming_another_device_is_ambiguous(self) -> None:
        """The injection does not have to come from the device being asked
        about: any stored device's name is in the listing, and a second dock
        can write a block for the first."""
        self.sysfs.router()
        self.unreadable_store()
        run = Run(
            stdout=named_listing(
                injecting_name(DEVICE_UUID, "yes", header="Fake Dock"),
                SECOND_UUID,
                "yes",
            )
            + named_listing("Tapex Creek Dock", DEVICE_UUID, "no")
        )

        self.assertIsNone(self.observe(run=run).enrolled)

    def test_the_same_uuid_twice_is_unknown_however_it_got_there(self) -> None:
        """Two identical blocks are not a contradiction and could be a
        `boltctl` printing a device once per domain. It is still two places
        one answer could come from, and picking one is the guess."""
        self.sysfs.router()
        self.unreadable_store()

        for first, second in (("yes", "yes"), ("yes", "no"), ("no", "no")):
            with self.subTest(blocks=(first, second)):
                run = Run(
                    stdout=named_listing("Tapex Creek Dock", DEVICE_UUID, first)
                    + named_listing("Other Dock", DEVICE_UUID, second)
                )

                self.assertIsNone(self.observe(run=run).enrolled)

    def test_two_devices_in_one_block_is_unknown(self) -> None:
        """One header, two `uuid:` lines, in both orders.

        The order matters, and pinning only one of them measured nothing.  With
        the *other* device named first, the block is skipped as somebody else's
        before its ambiguity is ever weighed -- the answer is an abstention
        either way, so that order alone passes whether or not the two-devices
        rule exists at all.  The attached device's own uuid first is the order
        that reaches the rule: skipping the block is no longer available, and
        what is left underneath is a `stored:` line the parser would otherwise
        read as this device's own.

        Both are here because both are shapes the injection can take, and which
        of the two `uuid:` lines a device writes is the device's choice.
        """
        self.sysfs.router()
        self.unreadable_store()

        for first, second in (
            (DEVICE_UUID, SECOND_UUID),
            (SECOND_UUID, DEVICE_UUID),
        ):
            with self.subTest(first="attached" if first == DEVICE_UUID else "other"):
                run = Run(
                    stdout=(
                        " * Tapex Creek Dock\n"
                        f"   |- uuid:     {first}\n"
                        f"   |- uuid:     {second}\n"
                        "   |- stored:   yes\n"
                    )
                )

                self.assertIsNone(self.observe(run=run).enrolled)

    def test_two_stored_lines_in_one_block_is_unknown(self) -> None:
        """The shape the injection takes when it lands inside the real block
        rather than opening one: the device answers for itself twice."""
        self.sysfs.router()
        self.unreadable_store()
        run = Run(
            stdout=(
                " * Tapex Creek Dock\n"
                f"   |- uuid:     {DEVICE_UUID}\n"
                "   |- stored:   yes\n"
                "   |- stored:   no\n"
            )
        )

        self.assertIsNone(self.observe(run=run).enrolled)

    def test_a_stored_line_belonging_to_nothing_is_unknown(self) -> None:
        self.sysfs.router()
        self.unreadable_store()
        run = Run(
            stdout="   |- stored:   yes\n"
            + named_listing("Tapex Creek Dock", DEVICE_UUID, "no")
        )

        self.assertIsNone(self.observe(run=run).enrolled)

    def test_a_stored_line_in_a_block_naming_no_device_is_unknown(self) -> None:
        """The other unattributable `stored`, and the one the case above does
        not reach.  There, the `stored:` line came before any device block had
        opened and the split itself refused.  Here the split succeeds: a
        header opened a block, so there *is* a device above the line -- the
        block just never printed a `uuid:`, so which device is still nothing
        the text says.

        Skipping such a block instead of refusing the listing is the quiet
        version of the failure.  The attached device's own truthful block sits
        right underneath, so a parser that skipped would answer confidently
        from it, in whichever direction the nameless block was not claiming,
        and a listing carrying a fabricated `stored` would have been read as
        though it were clean.

        The control in each round is the same listing without the nameless
        block: it answers yes and no, so what is refused is the ambiguity and
        not the fixture.
        """
        self.sysfs.router()
        self.unreadable_store()
        #: A block `boltctl` opened and never named: the header is where the
        #: device's own name goes, and no `uuid:` line follows it.
        nameless = " * Tapex Creek Dock\n   |- type:     peripheral\n"

        for claimed, truth in (("yes", "no"), ("no", "yes")):
            with self.subTest(claimed=claimed):
                truthful = named_listing(MODEL, DEVICE_UUID, truth)

                self.assertIs(
                    self.observe(run=Run(stdout=truthful)).enrolled,
                    truth == "yes",
                )

                run = Run(
                    stdout=nameless + f"   |- stored:   {claimed}\n" + truthful
                )

                self.assertIsNone(self.observe(run=run).enrolled)

    def test_a_uuid_line_that_is_not_a_uuid_is_unknown(self) -> None:
        """A listing whose structure is not exactly what is expected is not
        partially trusted. `boltctl` prints a uuid there; something else means
        this is not the output being parsed."""
        self.sysfs.router()
        self.unreadable_store()
        run = Run(
            stdout=named_listing("Other Dock", "not-a-uuid", "yes")
            + named_listing("Tapex Creek Dock", DEVICE_UUID, "no")
        )

        self.assertIsNone(self.observe(run=run).enrolled)

    def test_a_header_line_is_a_name_and_never_a_field(self) -> None:
        """The device's name sits on the header, so a name shaped like a field
        must not be read as one. This listing is unambiguous and gets a real
        answer -- refusing here would be the rule over-reaching."""
        self.sysfs.router()
        self.unreadable_store()
        run = Run(stdout=named_listing(f"uuid: {SECOND_UUID}", DEVICE_UUID, "no"))

        self.assertIs(self.observe(run=run).enrolled, False)

    def test_no_line_break_is_invented_that_boltctl_did_not_print(self) -> None:
        """`str.splitlines` breaks on `\\x0b`, `\\x1c` and `\\u2028` as well as
        on newlines. None of those end a line for the program that wrote this
        text, so a parser that split on them would open a second injection
        route of its own making -- one the device gets for free, without ever
        having a newline accepted into its name.

        The listing here is unambiguous once it is read the way it was
        written, so the truthful answer comes back rather than None."""
        self.sysfs.router()
        self.unreadable_store()

        for separator in ("\x0b", "\x1c", " ", "\x85"):
            with self.subTest(separator=repr(separator)):
                fabricated = (
                    f"Tapex Creek Dock{separator}"
                    f"   |- uuid:     {DEVICE_UUID}{separator}"
                    f"   |- stored:   yes{separator}"
                )
                run = Run(stdout=named_listing(fabricated, DEVICE_UUID, "no"))

                self.assertIs(self.observe(run=run).enrolled, False)

    def test_a_listing_padded_past_the_cap_is_unknown(self) -> None:
        """The length of a listing is attacker-chosen too: a device name can
        be three thousand newlines. A partial parse would answer "not stored"
        for every device past the cut, so a listing too long to read whole is
        not read at all."""
        self.sysfs.router()
        self.unreadable_store()
        run = Run(stdout=named_listing("Padded" + "\n" * 3000, DEVICE_UUID, "yes"))

        self.assertIsNone(self.observe(run=run).enrolled)

    def test_an_ordinary_listing_still_answers_both_ways(self) -> None:
        """The parser is strict, not broken: a listing `boltctl` actually
        prints is still read, and still says yes and no."""
        self.sysfs.router()
        self.unreadable_store()

        for stored, expected in (("yes", True), ("no", False)):
            with self.subTest(stored=stored):
                run = Run(stdout=named_listing(MODEL, DEVICE_UUID, stored))

                self.assertIs(self.observe(run=run).enrolled, expected)


class NamesInFrontOfAPlayer(ObserverCase):
    """Sanitizing is a rendering rule, and that is all it is.

    Control characters out, whitespace collapsed, length capped.  What survives
    is whatever the device published, because the content of a descriptor is
    not something this module judges -- see `TheFilterIsGone` for the three
    passes that established it cannot.
    """

    def test_control_characters_are_stripped_out_of_names(self) -> None:
        self.sysfs.router(
            device_name="Tapex\x00Creek\x07\tDock\r\n",
            vendor_name="  Tapex\x1b[31m  Industries  ",
        )

        observed = self.observe()

        self.assertEqual(observed.model, "Tapex Creek Dock")
        self.assertEqual(observed.vendor, "Tapex [31m Industries")

    def test_non_ascii_is_not_passed_through(self) -> None:
        self.sysfs.router(device_name="Tapex \u00e7reek \u4e2d Dock")

        self.assertEqual(self.observe().model, "Tapex reek Dock")

    def test_names_are_capped(self) -> None:
        self.sysfs.router(device_name="W" * 400, vendor_name="V" * 400)

        observed = self.observe()

        self.assertEqual(len(observed.model), MAX_NAME)
        self.assertEqual(len(observed.vendor), MAX_NAME)

    def test_a_long_name_of_hex_letters_is_capped_rather_than_refused(self) -> None:
        """`d`, `c`, `a` and `e` are letters real words are spelled with.
        Forty repetitions of "Dock" used to be refused whole by the content
        filter, which meant a dock named that way was never offered.  The cap
        is what acts on it now, and the device stays identified."""
        self.sysfs.router(device_name="Dock " * 40, vendor_name="CalDigit " * 40)

        observed = self.observe()

        self.assertIs(observed.identity_resolved, True)
        self.assertEqual(len(observed.model), MAX_NAME)
        self.assertTrue(observed.model.startswith("Dock Dock"))

    def test_a_capped_name_does_not_end_in_a_space(self) -> None:
        """"Monitor " is eight characters, so the cap falls exactly on a space
        and the strip afterwards is what removes it."""
        self.sysfs.router(device_name="Monitor " * 9)

        model = self.observe().model

        self.assertEqual(len(model), MAX_NAME - 1)
        self.assertEqual(model, model.strip())
        self.assertTrue(model.endswith("Monitor"))

    def test_a_name_of_nothing_but_control_characters_does_not_identify(self) -> None:
        self.sysfs.router(device_name="\x00\x01\x02")

        observed = self.observe()

        self.assertEqual(observed.model, "")
        self.assertIs(observed.identity_resolved, False)


class TheIdentifierStaysInternal(ObserverCase):
    """`SAFETY_INVARIANTS` #12, and the one form of it that is enforceable.

    Re-Gear never puts the uuid into a payload itself.  `ObservedAttachment`
    carries it in one field, for one purpose -- handing `boltctl` something to
    act on -- and no other field of the reading may contain it.

    "For a normal device" is load-bearing and is stated rather than assumed: a
    device whose product name *is* its own identifier is a different case, and
    `ADeviceThatNamesItselfAfterItsOwnId` says what happens there and why
    nothing here can change it.
    """

    def payload_fields(self, observed: ObservedAttachment) -> list[tuple[str, str]]:
        """Every field of a reading except the internal identifier itself."""
        return [
            (field.name, str(getattr(observed, field.name)))
            for field in dataclasses.fields(observed)
            if field.name != "uuid"
        ]

    def assert_no_identifier_survives(
        self, observed: ObservedAttachment, uuid: str
    ) -> None:
        """No field but `uuid` carries the id, whole or in any real fragment."""
        for name, value in self.payload_fields(observed):
            with self.subTest(field=name):
                self.assertNotIn(uuid, value)
                self.assertNotIn(normalized(uuid), normalized(value))
                self.assertLess(
                    len(surviving_id_run(value, uuid)),
                    LONGEST_COINCIDENCE,
                    f"{value!r} carries a run of the identifier",
                )

    def test_the_uuid_is_in_no_other_field_of_a_normal_reading(self) -> None:
        self.sysfs.router(unique_id=VARIED_UUID)

        observed = self.observe()

        self.assertEqual(observed.uuid, VARIED_UUID)
        self.assert_no_identifier_survives(observed, VARIED_UUID)

    def test_no_identifier_reaches_the_names_of_a_normal_device(self) -> None:
        """A router UUID is a hardware unique identifier, and `serial` is not
        read at all -- not "not shown", not read."""
        router = self.sysfs.router()
        (router / "serial").write_text("SERIALSENTINEL", encoding="utf-8")

        observed = self.observe()

        self.assertNotIn("SERIALSENTINEL", observed.vendor)
        self.assertNotIn("SERIALSENTINEL", observed.model)
        self.assertEqual(observed.model, MODEL)
        self.assertEqual(observed.vendor, VENDOR)

    def test_the_uuid_stays_out_of_the_reading_of_a_real_dock(self) -> None:
        """The same guarantee across the regression corpus, so that a product
        string which happens to contain hex does not quietly become a way for
        an identifier to ride along."""
        for vendor, model, _ in REAL_DOCKS:
            with self.subTest(model=model):
                self.sysfs.router(
                    vendor_name=vendor, device_name=model, unique_id=VARIED_UUID
                )

                observed = self.observe()

                self.assertIs(observed.identity_resolved, True)
                self.assert_no_identifier_survives(observed, VARIED_UUID)


class ADeviceThatNamesItselfAfterItsOwnId(ObserverCase):
    """The residual, pinned so that nobody re-reads it as a bug.

    A device that publishes its own identifier as its product name will have
    that string displayed.  It is the only name the device has; the prompt has
    to name something; and the device disclosed its own id the moment it wrote
    it into `device_name`.  That is a device-authored disclosure, not a Re-Gear
    diagnostic leak.

    Three passes tried to filter it out and every one was both too weak and too
    strong.  Too weak because no rule over attacker-controlled text can win: the
    same id in base32 reduces to thirteen hex-class characters, in base64 to
    seven, and under a nibble-to-`g`..`v` substitution to none, so a hex count
    sees nothing.  Too strong because the arithmetic that catches a uuid also
    catches "Dell Thunderbolt Dock WD19TBS 180W Docking Station", and a refused
    descriptor is not a redacted dialog -- it is *no dialog at all*, because
    `identity_resolved` goes False and the domain declines.

    So the rule went, and the honest statement replaced it.  The cases here
    assert the honest statement, including the part that is uncomfortable: yes,
    the id is in the label.  Asserting it is what stops a fourth pass from
    quietly reintroducing a filter that takes real docks out of the dialog.
    """

    def test_a_device_named_after_its_own_id_is_still_offered(self) -> None:
        """The behaviour that matters: it is named, it is addressable, and it
        gets its prompt.  Refusing would be the failure, not the fix."""
        self.sysfs.router(device_name=DEVICE_UUID)

        observed = self.observe()

        self.assertIs(observed.present, True)
        self.assertIs(observed.identity_resolved, True)
        self.assertEqual(observed.model, DEVICE_UUID)
        self.assertIs(observed.authorized, False)

    def test_the_disclosure_is_the_devices_and_is_not_hidden(self) -> None:
        """Stated out loud rather than left to be discovered: the string the
        device published is the string that leaves."""
        self.sysfs.router(device_name=f"{MODEL} {DEVICE_UUID}")

        observed = self.observe()

        self.assertIn(DEVICE_UUID, observed.model)
        self.assertIs(observed.identity_resolved, True)

    def test_re_gear_still_adds_nothing_of_its_own(self) -> None:
        """The line that is actually Re-Gear's to hold.  The device wrote its
        id into `device_name`; nothing copies the id into `vendor`, and a
        device that published no such name gets no such label."""
        self.sysfs.router(device_name=DEVICE_UUID, vendor_name=VENDOR)

        observed = self.observe()

        self.assertEqual(observed.vendor, VENDOR)
        self.assertNotIn(DEVICE_UUID, observed.vendor)

    def test_reading_such_a_device_still_writes_nothing(self) -> None:
        self.sysfs.router(device_name=DEVICE_UUID)
        before = self.sysfs.snapshot()

        self.observe()

        self.assertEqual(self.sysfs.snapshot(), before)


#: Real shipping Thunderbolt docks, each with the **full legal vendor string**
#: sysfs publishes rather than the brand nickname.  That distinction is the
#: whole reason the old corpus missed this: pairing a long model string with
#: "Kensington" (one hex-class character) hid the refusal that
#: "Kensington Computer Products Group" produces.
#:
#: The third column is what the deleted content filter scored the pair at.  Its
#: limit was twenty, so the first four of these were REFUSED -- named,
#: addressable, unenrolled docks that silently never got a prompt.
REAL_DOCKS = (
    ("Dell Technologies", "Dell Thunderbolt Dock WD19TBS 180W Docking Station", 22),
    (
        "Kensington Computer Products Group",
        "SD5780T Thunderbolt 4 Dual 4K Docking Station",
        20,
    ),
    (
        "Plugable Technologies",
        "TBT4-UDZ Thunderbolt 4 Quad Display Docking Station",
        20,
    ),
    ("Razer Inc.", "Razer Thunderbolt 4 Dock Chroma RC21-01690", 21),
    ("CalDigit, Inc.", "CalDigit TS4 Thunderbolt 4 Dock", 14),
    (
        "Hewlett-Packard Development Company, L.P.",
        "HP Thunderbolt Dock G4",
        18,
    ),
)

#: The limit the deleted rule used. Kept only so the corpus can say which of
#: these docks it refused, and why that was disqualifying.
REMOVED_FILTER_LIMIT = 20


class RealDocksAreNeverRefused(ObserverCase):
    """The corpus that disqualified the content filter, kept permanently.

    Each of these is a dock a player can buy, with the vendor string its sysfs
    entry really publishes.  A refusal of any one of them is not a degraded
    label: `identity_resolved` goes False, the domain declines with
    `identity_unresolved`, and the dock -- named, addressable, unenrolled --
    never gets its prompt.  The player sees nothing and has no way to tell that
    from a bug.

    So this is not a false-positive guard on a threshold.  It is the assertion
    that no threshold exists here at all.
    """

    def test_every_real_dock_is_accepted_with_a_readable_name(self) -> None:
        for vendor, model, _ in REAL_DOCKS:
            with self.subTest(model=model):
                self.sysfs.router(vendor_name=vendor, device_name=model)

                observed = self.observe()

                self.assertIs(observed.present, True)
                self.assertIs(observed.identity_resolved, True)
                self.assertEqual(observed.vendor, vendor)
                self.assertEqual(observed.model, model)
                self.assertTrue(observed.model.strip())

    def test_every_real_dock_gets_as_far_as_a_decision(self) -> None:
        """Identified is not the end of it: the reading has to carry the state
        the domain decides on, for an unenrolled dock that is the prompt."""
        for vendor, model, _ in REAL_DOCKS:
            with self.subTest(model=model):
                self.sysfs.router(vendor_name=vendor, device_name=model)

                observed = self.observe()

                self.assertIs(observed.authorized, False)
                self.assertIs(observed.enrolled, False)
                self.assertEqual(observed.uuid, DEVICE_UUID)

    def test_the_names_fit_inside_the_cap(self) -> None:
        """Otherwise the case above would be measuring the cap rather than
        acceptance, and a truncated label would pass it unnoticed."""
        for vendor, model, _ in REAL_DOCKS:
            with self.subTest(model=model):
                self.assertLessEqual(len(model), MAX_NAME)
                self.assertLessEqual(len(vendor), MAX_NAME)

    def test_the_deleted_filter_would_have_refused_four_of_them(self) -> None:
        """The evidence, recomputed rather than recalled.  These counts are
        why the rule is gone: they are ordinary marketing names, and four of
        them are over a limit that had to stay under a uuid's thirty-two."""
        refused = []
        for vendor, model, expected in REAL_DOCKS:
            with self.subTest(model=model):
                carried = hex_class_length(vendor, model)
                self.assertEqual(carried, expected)
                if carried >= REMOVED_FILTER_LIMIT:
                    refused.append(model)

        self.assertEqual(len(refused), 4)

    def test_the_docks_it_would_have_refused_are_accepted_anyway(self) -> None:
        """The two facts placed side by side, which is the point of the whole
        class: over the old limit, and identified regardless."""
        for vendor, model, carried in REAL_DOCKS:
            if carried < REMOVED_FILTER_LIMIT:
                continue
            with self.subTest(model=model):
                self.sysfs.router(vendor_name=vendor, device_name=model)

                observed = self.observe()

                self.assertIs(observed.identity_resolved, True)
                self.assertEqual(observed.model, model)


class TheFilterIsGone(unittest.TestCase):
    """The rule is deleted, and staying deleted is a property worth pinning.

    Three passes reintroduced a variation of it.  Each one was defended as
    "safety", and each one silently took hardware out of the dialog while
    stopping no attacker -- a uuid re-encoded in base32, base64 or a
    `g`..`v` nibble alphabet reduces to thirteen, seven and zero hex-class
    characters, all far under any limit a real product name can live above.

    So the absence is asserted, not just the behaviour: no helper, no constant,
    and no docstring claiming a guarantee the code does not have.
    """

    def test_the_helper_and_its_constants_are_not_exported(self) -> None:
        for name in ("refuses_hex_shape", "hex_class", "HEX_CLASS", "HEX_CLASS_LIMIT"):
            with self.subTest(name=name):
                self.assertFalse(
                    hasattr(device_authorization_observer, name),
                    f"{name} is back; see RealDocksAreNeverRefused for the cost",
                )

    def test_the_source_carries_no_hex_class_rule(self) -> None:
        source = module_source()

        self.assertNotIn("HEX_CLASS", source)
        self.assertNotIn("refuses_hex_shape", source)

    def test_the_docstring_states_the_residual_rather_than_a_guarantee(self) -> None:
        claim = module_docstring()

        self.assertIn("device-authored disclosure", claim)
        self.assertIn("will have that string displayed", claim)
        self.assertNotIn("bounded by shape", claim)

    def test_the_docstring_still_states_the_guarantee_that_is_kept(self) -> None:
        """What was not thrown out with the filter: Re-Gear does not put the
        identifier into a payload itself, and the outward address is a token."""
        claim = module_docstring()

        self.assertIn("never puts the uuid into a payload itself", claim.casefold())
        self.assertIn("opaque attachment token", claim)


class TheModuleItself(unittest.TestCase):
    """Static guarantees, asserted against the source rather than a run."""

    def test_a_serial_attribute_is_never_read_at_all(self) -> None:
        """Not "not shown" -- not read. The set of sysfs attributes this
        module can reach is pinned, so adding a read of `serial` or of any
        other identifier fails here."""
        tree = ast.parse(module_source())
        appended = {
            node.right.value
            for node in ast.walk(tree)
            if isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and isinstance(node.right, ast.Constant)
            and isinstance(node.right.value, str)
        }

        self.assertEqual(appended, PERMITTED_ATTRIBUTES)

    def test_the_module_calls_no_filesystem_writer(self) -> None:
        """`scripts/check_architecture.py` enforces this repository-wide;
        this pins it for the one adapter whose whole contract is reading."""
        forbidden = {
            "chmod",
            "mkdir",
            "rename",
            "replace",
            "rmdir",
            "symlink_to",
            "touch",
            "unlink",
            "write_bytes",
            "write_text",
        }
        tree = ast.parse(module_source())
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        self.assertEqual(called & forbidden, set())

    def test_the_module_spawns_nothing_itself(self) -> None:
        """The one command it can reach arrives injected. A `subprocess`
        import here would also fail the architecture gate."""
        tree = ast.parse(module_source())
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }

        self.assertNotIn("subprocess", imported)
        self.assertNotIn("os", imported)

    def test_the_reading_is_frozen_and_slotted(self) -> None:
        observed = ObservedAttachment(
            present=True,
            identity_resolved=True,
            authorized=False,
            enrolled=False,
            vendor=VENDOR,
            model=MODEL,
            uuid=DEVICE_UUID,
        )

        with self.assertRaises(FrozenInstanceError):
            observed.present = False  # type: ignore[misc]
        self.assertFalse(hasattr(observed, "__dict__"))

    def test_every_unknown_field_is_none_rather_than_false(self) -> None:
        """The distinction the module exists for, asserted with `is`:
        `assert not x` would have passed for both."""
        observed = ObservedAttachment(
            present=None,
            identity_resolved=False,
            authorized=None,
            enrolled=None,
            vendor="",
            model="",
            uuid="",
        )

        self.assertIsNone(observed.present)
        self.assertIsNone(observed.authorized)
        self.assertIsNone(observed.enrolled)


class WhatTheGateActuallyEnforces(unittest.TestCase):
    """The docstring's claim about `scripts/check_architecture.py`, checked.

    The module used to say that gate enforces the read-only half -- "no adapter
    but `device_removal.py` may write at all".  It bans a list of write
    *attribute names*, which is less than that: a write reached by any other
    name passes it in silence.  This module is read-only anyway, and
    `test_the_module_calls_no_filesystem_writer` and
    `test_observing_writes_nothing` are what establish it.  A docstring that
    credits a gate with more than it delivers teaches the next reader to lean
    on the wrong thing, so the overstatement is pinned out here.
    """

    def gate_constant(self, name: str) -> set[str]:
        """One literal set out of the checker, read without running it."""
        tree = ast.parse(
            (ROOT / "scripts" / "check_architecture.py").read_text(encoding="utf-8")
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets
            ):
                return set(ast.literal_eval(node.value))
        self.fail(f"{name} is no longer a literal in the checker")

    def test_the_gate_bans_names_not_write_operations(self) -> None:
        """The substance behind the corrected wording: these are all writes,
        and the gate's list contains none of them."""
        unbanned = {
            "makedirs",
            "open",
            "remove",
            "removedirs",
            "rmtree",
            "truncate",
            "write",
            "writelines",
        }

        self.assertEqual(self.gate_constant("FORBIDDEN_WRITE_CALLS") & unbanned, set())

    def test_the_docstring_does_not_overstate_the_gate(self) -> None:
        """The false claim, and the fact that replaced it."""
        claim = module_docstring()

        self.assertNotIn("enforces the read-only half", claim)
        self.assertIn("attribute names", claim)

    def test_the_tests_the_docstring_points_at_are_this_file(self) -> None:
        """It names a path. A path that moved would send a reader nowhere."""
        claim = module_docstring()
        named = "tests/test_device_authorization_observer.py"

        self.assertIn(named, claim)
        self.assertTrue((ROOT / named).is_file())


if __name__ == "__main__":
    unittest.main()
