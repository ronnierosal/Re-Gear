"""The feature as it is actually wired, with only its two real seams faked.

Every layer below this file already has a unit suite, and each of those suites
is honest about what it is.  `tests/test_device_authorization_observer.py`
reads a temporary sysfs tree.  `tests/test_device_authorization_service.py`
drives the latch in front of a recording port.
`tests/test_device_authorization_facade.py` hands the facade a reading the
observer never took.  `tests/test_bolt_device_authorization.py` checks the argv
a runner builds out of a uuid a test handed it.  All four are green with a fake
in the middle, and the fake in the middle is exactly what makes them unable to
answer the one question this file exists to ask: **is the uuid the executor
receives the uuid the observer read?**

Nothing in those suites can say.  In each of them the device id is supplied by
the test on both sides of the boundary, so a service that bound its token to an
id nobody observed, a facade that dispatched the other grant, or a runner
handed the attachment token in place of the device would leave all four suites
passing.  That is not a gap in any of them; it is what a unit test is.

So nothing here is faked in the middle.  The observer is the real adapter over
a temporary tree, the service is the real one, the executor is the real
`BoltDeviceAuthorizationRunner`, and the facade is built with two positional
arguments and no opt-in.

**Nothing outside `tests/` constructs that facade at all.**  This feature is
not wired: no RPC surface builds one, root's `main.py` forwards nothing to it,
and there is no production call site for this file to be copying.  So the claim
this docstring used to make -- that the facade is constructed the way
production constructs it -- was not true of this tree, and saying that plainly
is better than a comparison there is nothing to compare against.  What `setUp`
composes is the arrangement the wiring is *intended* to build, and that is
exactly why composing it in a test before the wiring exists is worth doing: the
argument list, the ownership and the ordering are settled here, by the only
caller there currently is, so wiring written later against a different shape
has a failing test to answer to rather than a docstring to disagree with.

The seams are the two places this feature genuinely meets the machine: the
filesystem, which is a per-test temporary directory, and `subprocess.run`,
which is mocked at the boundary and then read for the argv it was actually
handed.  The runner's effective-uid probe is injected as well, through the same
`runner()` helper the bolt suite uses -- it is that runner's own constructor
argument rather than a stand-in for a layer, and without it every case here
would stop at `root_required` on a developer's machine instead of reaching a
command line at all.

**Every scenario below asserts on that argv, and none of them spells the id.**
A return code proves that some command succeeded; it does not prove which
device was named, which verb was sent, or that exactly one command ran.  Those
are the composition facts, and the mocked boundary is the only place they are
visible.  The id every one of those assertions expects is read back out of the
sysfs tree -- `uuid_on_the_bus`, captured by `armed()` at the instant the
prompt is drawn -- rather than named from a fixture constant, so the two sides
of each comparison arrive by different routes: one through `Path.read_text`,
the other through the observer, the service and the runner.  A constant on the
expected side would be the test agreeing with itself.

Nothing here restates a rule a unit suite already owns, and the fixtures, the
synthetic ids and the guards are borrowed from those suites rather than rebuilt
-- a parallel sysfs writer or a second set of fake uuids is a second thing to
keep true.  The five cases are the five places where two layers have to agree
about a device, each written as the journey a player actually takes.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.device_authorization import (  # noqa: E402
    DeviceAuthorizationService,
)
from regear.delivery.device_authorization_facade import (  # noqa: E402
    DeviceAuthorizationFacade,
)

from tests.test_bolt_device_authorization import (  # noqa: E402
    Completed,
    runner,
)
from tests.test_device_authorization_facade import (  # noqa: E402
    ALREADY_OFFERED,
    NO_DEVICE,
    NOT_OFFERED,
    SCAN_UNREADABLE,
    offer,
)
from tests.test_device_authorization_observer import (  # noqa: E402
    DEVICE_UUID,
    MODEL,
    VARIED_UUID,
    VENDOR,
    ObserverCase,
)


#: The one-shot grant's accepted code, spelled out rather than imported for the
#: reason the facade suite spells out its own: a guard that takes its
#: expectation from the thing it is guarding cannot notice the thing changing.
ACCEPTED = "device_authorization.authorize_accepted_unverified"
#: The two ways a confirmation is refused, named apart rather than collected
#: into a set.  Which one arrives says *which layer* refused, and for some of
#: the cases below that is the entire claim: `token_stale` is the attachment
#: having been retired out from under the prompt, and `attachment_changed` is
#: the identity binding itself, which is reachable only while the token is
#: still live.  A membership test against both cannot tell them apart, so it
#: cannot notice one of the two layers being removed while the other refuses.
TOKEN_STALE = "device_authorization.token_stale"
ATTACHMENT_CHANGED = "device_authorization.attachment_changed"
#: What must never appear in an argv built for a one-shot grant. `--policy` and
#: `auto` would ask `boltd` to remember a decision the player was told would not
#: be remembered; `--chain` would trust parents nobody was shown.
FORBIDDEN_ARGUMENTS = ("--policy", "auto", "--chain")


def granted(uuid: str) -> tuple[str, ...]:
    """The exact argv a one-shot grant for `uuid` has to be.

    Written out here rather than asked of `BoltDeviceAuthorizationRunner`,
    because the claim under test is that this composition produces this command
    line for the device on the bus -- and a claim that builds its own
    expectation from the builder it is checking has nothing left to check.
    """
    return ("/usr/bin/boltctl", "authorize", uuid)


def race(workers: int, work):
    """Run `work` on `workers` real threads released together, and collect.

    The service's own suite races its lock directly.  What is raced here is the
    whole composition, where observing, reading the generation and acting are
    three separate calls from the delivery layer with two gaps between them,
    and a second presser can land in either one.
    """
    barrier = threading.Barrier(workers)
    results: list = []
    guard = threading.Lock()

    def run(index: int) -> None:
        barrier.wait()
        value = work(index)
        with guard:
            results.append(value)

    threads = [
        threading.Thread(target=run, args=(index,)) for index in range(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    if any(thread.is_alive() for thread in threads):
        raise AssertionError("a racing caller never returned")
    return results


class ComposedCase(ObserverCase):
    """Observer, service, facade and runner, assembled as production would.

    `ObserverCase` supplies the isolated temporary tree and the `Sysfs` writer,
    so the bytes a dock publishes are written by the fixture that already knows
    the shape of a real tree -- domain entry, host router and all.
    """

    def setUp(self) -> None:
        super().setUp()
        # The real executor. `runner()` injects only the uid probe.
        self.service = DeviceAuthorizationService(runner())
        # Two positional arguments and nothing else: the remembered grant is
        # not on offer from an object built this way, so every case below is
        # testing the arrangement the wiring is meant to build rather than a
        # fixture that happens to be more permissive than it.
        self.facade = DeviceAuthorizationFacade(
            self.sysfs.observer(), self.service
        )
        #: The id of the dock `armed()` drew the prompt for, read out of the
        #: tree rather than named. Empty until a prompt has been armed.
        self.attached = ""
        patcher = patch.object(subprocess, "run", return_value=Completed(0))
        self.run = patcher.start()
        self.addCleanup(patcher.stop)

    @property
    def argvs(self) -> list[tuple[str, ...]]:
        """Every command line the boundary actually received, in order."""
        return [call.args[0] for call in self.run.call_args_list]

    def uuid_on_the_bus(self, name: str = "0-1") -> str:
        """The device's own id, read back out of the tree the observer read.

        Reading it from the filesystem rather than naming the constant is the
        point: the assertion then compares two values that travelled by
        different routes, this one through `Path.read_text` and the other
        through the observer, the service and the runner.
        """
        path = self.sysfs.thunderbolt / name / "unique_id"
        return path.read_text(encoding="utf-8").strip()

    def armed(self) -> str:
        """One unauthorized, unenrolled dock, offered and acknowledged.

        The id is read off the bus here and kept as `self.attached`, because
        the argv assertions need it *after* the cases that stop the tree
        publishing it -- an unlinked `unique_id`, a dock replaced mid-act.
        Read at the instant the prompt is drawn, which is the instant those
        claims are about, and still never named by the test.
        """
        self.sysfs.router()
        token = offer(self.facade)
        self.facade.acknowledge(token)
        self.attached = self.uuid_on_the_bus()
        return token


class TheCommandNamesTheDeviceTheObserverRead(ComposedCase):
    """Scenario one: what reaches `boltctl`, and for which device.

    The uuid in this argv was never handed in by the test.  It was written into
    a sysfs file, read by the real observer, carried through the service's
    identity binding and validated by the real runner.  That chain is the whole
    claim, and the mocked boundary is the only place it can be seen.
    """

    def test_the_command_is_the_one_shot_grant_for_the_id_in_the_tree(self):
        token = self.armed()
        payload = self.facade.confirm(token, consent=True, action="authorize")
        self.assertTrue(payload["requested"])
        self.assertEqual(
            self.argvs,
            [granted(self.uuid_on_the_bus())],
            "the executor was not run once for the device on the bus",
        )
        self.assertEqual(self.uuid_on_the_bus(), DEVICE_UUID)

    def test_no_policy_no_auto_and_no_chain_reach_the_command_line(self):
        """A one-shot grant that stored a policy is a different promise."""
        token = self.armed()
        self.facade.confirm(token, consent=True, action="authorize")
        argv = self.argvs[0]
        self.assertEqual(argv[1], "authorize")
        for argument in FORBIDDEN_ARGUMENTS:
            with self.subTest(argument=argument):
                self.assertNotIn(argument, argv)
        self.assertEqual(len(argv), 3)

    def test_the_runners_own_code_travels_out_and_says_unverified(self):
        """Accepted is not trusted, all the way from the exit status out.

        The tree still reads `authorized` as "0" after the command, because a
        mocked `boltctl` changes no hardware.  That is the honest answer here:
        the request was accepted, the re-read found the device untrusted, and
        the payload says both rather than rounding one into the other.
        """
        token = self.armed()
        payload = self.facade.confirm(token, consent=True, action="authorize")
        self.assertIs(payload["requested"], True)
        self.assertEqual(payload["code"], ACCEPTED)
        self.assertIs(payload["verified"], False)


class TheRememberedGrantNeverReachesTheCommandLine(ComposedCase):
    """Scenario one, other half: the action the shipped facade will not send.

    Refused before the executor is reachable, and it costs the player nothing:
    the prompt they were actually going to be asked is still answerable
    afterwards, and the command that then runs is the one-shot one.
    """

    def test_enroll_is_refused_on_a_live_prompt_and_runs_no_command(self):
        token = self.armed()
        refused = self.facade.confirm(token, consent=True, action="enroll")
        self.assertIs(refused["requested"], False)
        self.assertEqual(refused["code"], NOT_OFFERED)
        self.assertEqual(self.argvs, [], "a remembered grant reached boltd")
        accepted = self.facade.confirm(token, consent=True, action="authorize")
        self.assertTrue(accepted["requested"])
        self.assertEqual(self.argvs, [granted(self.attached)])


class ADifferentDeviceUnderTheSamePromptIsNeverGranted(ComposedCase):
    """Scenario two: the dock is swapped between the prompt and the yes.

    What this guards is a grant of direct memory access handed to a device the
    player was never shown, under a dialog raised for one they were.
    """

    def swap(self):
        """Rewrite the one attachable router as a different device."""
        return self.sysfs.router(
            unique_id=VARIED_UUID, device_name="Other Dock"
        )

    def test_a_swapped_attachment_is_refused_and_grants_nothing(self):
        token = self.armed()
        self.swap()
        payload = self.facade.confirm(token, consent=True, action="authorize")
        self.assertIs(payload["requested"], False)
        self.assertEqual(
            payload["code"],
            TOKEN_STALE,
            "the swap was refused by something other than the retired token",
        )
        self.assertIsNone(payload["verified"])
        self.assertEqual(
            self.argvs,
            [],
            "a grant was attributed to one of the two devices",
        )

    def test_the_replacement_gets_its_own_prompt_and_its_own_token(self):
        """And the grant that does run names the device in front of us."""
        token = self.armed()
        attachment = self.facade.status()["generation"]
        self.swap()
        # Read off the bus like every other expectation here, and checked to be
        # a different id, so the argv assertion below cannot pass on a swap
        # that never happened.
        replacement = self.uuid_on_the_bus()
        self.assertNotEqual(replacement, self.attached)
        self.facade.confirm(token, consent=True, action="authorize")
        status = self.facade.status()
        self.assertEqual(status["state"], "offered")
        self.assertTrue(status["token"])
        self.assertNotEqual(status["token"], token)
        self.assertFalse(status["already_offered"])
        self.assertGreater(
            status["generation"],
            attachment,
            "a different device was not treated as a different attachment",
        )
        payload = self.facade.confirm(
            status["token"], consent=True, action="authorize"
        )
        self.assertTrue(payload["requested"])
        self.assertEqual(self.argvs, [granted(replacement)])


class AFailedScanIsNotAnEmptyPortAndLosesNoPrompt(ComposedCase):
    """Scenario three: the thunderbolt root stops being readable for a poll.

    Two things have to survive it.  The reading has to stay unknown rather than
    becoming an absence, because an absence retires the attachment; and the
    prompt already on screen has to still be there afterwards, neither dropped
    nor replaced by a second one.
    """

    @contextlib.contextmanager
    def blip(self, *, shape: str = "missing"):
        """The scan fails for the duration, then the tree comes back.

        Two shapes, because the adapter treats them as one fact and should: a
        root that is gone and a root that is not a directory are both the look
        not having happened.
        """
        root = self.sysfs.thunderbolt
        moved = root.parent / "thunderbolt-unreadable"
        root.rename(moved)
        if shape == "file":
            root.write_text("not a directory", encoding="utf-8")
        try:
            yield
        finally:
            if shape == "file":
                root.unlink()
            moved.rename(root)

    def test_the_scan_reads_as_unknown_rather_than_as_an_empty_port(self):
        self.sysfs.router()
        for shape in ("missing", "file"):
            with self.subTest(shape=shape), self.blip(shape=shape):
                self.assertIsNone(
                    self.sysfs.observer().observe().present,
                    "a failed scan claimed to know the port was empty",
                )
                status = self.facade.status()
                self.assertEqual(status["code"], SCAN_UNREADABLE)
                self.assertNotEqual(status["code"], NO_DEVICE)

    def test_a_yes_taken_during_the_blip_is_refused_by_the_identity_binding(
        self,
    ):
        """The one refusal the retire cannot produce, named as itself.

        The swapped-dock scenario earlier in this file is refused a layer
        before this one: a reading of another dock retires the attachment,
        which drops the token, so `token_stale` is the answer and the identity
        binding is never the reason anything was refused.  That is why it now
        asserts `TOKEN_STALE` by name.  Here nothing is retired -- a scan says
        nothing, so the attachment, the generation and the token all survive
        it, as the test below this one spells out -- and the caller's reading
        still cannot name the device the service observed.  That leaves the
        binding in `_confirm_locked` as the only thing standing between a
        blind yes and a grant of direct memory access, and the code it emits
        is the evidence that it is what refused.  Asserting membership of
        {token_stale, attachment_changed} here would pass either way and could
        not tell the two layers apart.
        """
        token = self.armed()
        with self.blip():
            payload = self.facade.confirm(
                token, consent=True, action="authorize"
            )
        self.assertIs(payload["requested"], False)
        self.assertEqual(
            payload["code"],
            ATTACHMENT_CHANGED,
            "the blind yes was refused by some other layer, or not at all",
        )
        self.assertIsNone(payload["verified"])
        self.assertEqual(self.argvs, [], "a yes nobody could bind reached boltd")

        # Nothing was spent and nothing was retired: the same prompt is still
        # the live one, which is what makes the refusal above the binding's
        # rather than the retire's.
        back = self.facade.status()
        self.assertEqual(back["token"], token)
        self.assertEqual(back["code"], ALREADY_OFFERED)
        payload = self.facade.confirm(token, consent=True, action="authorize")
        self.assertTrue(payload["requested"])
        self.assertEqual(self.argvs, [granted(self.attached)])

    def test_an_open_prompt_survives_the_blip_whole(self):
        token = self.armed()
        opened = self.facade.status()
        self.assertTrue(opened["confirmation_open"])
        attachment = opened["generation"]

        with self.blip():
            blind = self.facade.status()
        self.assertEqual(blind["code"], SCAN_UNREADABLE)
        self.assertEqual(
            blind["token"], token, "a blind poll dropped the open prompt"
        )
        self.assertEqual(blind["generation"], attachment)
        self.assertTrue(blind["already_offered"])
        self.assertTrue(blind["confirmation_open"])

        back = self.facade.status()
        self.assertEqual(back["state"], "unavailable")
        self.assertEqual(
            back["code"],
            ALREADY_OFFERED,
            "the blip re-armed a prompt that had already been offered",
        )
        self.assertEqual(back["token"], token, "the blip minted a second prompt")
        self.assertEqual(back["generation"], attachment)

        payload = self.facade.confirm(token, consent=True, action="authorize")
        self.assertTrue(payload["requested"])
        self.assertEqual(self.argvs, [granted(self.attached)])


class OnePromptIsOneCommandHoweverOftenItIsPressed(ComposedCase):
    """Scenario four: the same yes, twice -- sequentially and at once.

    A sequential double press proves the token is consumable.  It does not
    prove that two callers arriving together cannot both get through the
    delivery layer's observe-read-act sequence, which is three calls and two
    gaps, so that one is raced on real threads.
    """

    def test_the_same_token_confirmed_twice_runs_one_command(self):
        token = self.armed()
        first = self.facade.confirm(token, consent=True, action="authorize")
        second = self.facade.confirm(token, consent=True, action="authorize")
        self.assertIs(first["requested"], True)
        self.assertIs(second["requested"], False)
        self.assertEqual(
            self.argvs,
            [granted(self.attached)],
            "one prompt reached boltd more than once",
        )

    def test_confirmations_racing_on_real_threads_run_one_command(self):
        token = self.armed()

        def accepted(*_args, **_kwargs):
            # A real grant is not instant. The pause is what gives the other
            # seven callers a window to be inside the composition during it.
            time.sleep(0.05)
            return Completed(0)

        self.run.side_effect = accepted
        payloads = race(
            8,
            lambda _index: self.facade.confirm(
                token, consent=True, action="authorize"
            ),
        )
        self.assertEqual(len(payloads), 8)
        self.assertEqual(
            [payload["requested"] for payload in payloads].count(True), 1
        )
        self.assertEqual(
            self.argvs,
            [granted(self.attached)],
            "eight racing presses reached boltd more than once",
        )


class AnAcceptedGrantIsNotAVerifiedOne(ComposedCase):
    """Scenario five: the command succeeded and the re-read cannot say more.

    `verified` is tri-state for one reason: a re-read that could not establish
    which device it was looking at is not a re-read that found the device
    untrusted.  `False` there is a claim nobody is in a position to make, and it
    is the claim a panel renders as "it did not work".
    """

    def act_while(self, mutate):
        """Confirm, with the tree changing underneath the running command.

        The mutation happens inside the mocked `subprocess.run`, which is the
        honest place for it: that is the instant the grant is being made, and
        it is the window in which a dock can be pulled or swapped.
        """
        token = self.armed()

        def accepted(*_args, **_kwargs):
            mutate()
            return Completed(0)

        self.run.side_effect = accepted
        return self.facade.confirm(token, consent=True, action="authorize")

    def unreadable_identity(self) -> None:
        router = self.sysfs.thunderbolt / "0-1"
        (router / "authorized").write_text("1", encoding="utf-8")
        (router / "unique_id").unlink()

    def replaced(self) -> None:
        self.sysfs.router(
            unique_id=VARIED_UUID, device_name="Other Dock", authorized="1"
        )

    def unnamed_but_addressable(self) -> None:
        """The dock stops publishing a name; its id stays perfectly readable.

        Deliberately not `unreadable_identity`, which unlinks `unique_id` and
        so empties the uuid.  An empty uuid is refused by `record_verification`
        itself, which means that case never reaches -- and therefore never
        checks -- the delivery layer's own decision to withhold an id that a
        reading could not resolve.  This shape is the one that does: readable
        id, no name, so `identity_resolved` is False while the uuid is there
        to be handed over.
        """
        router = self.sysfs.thunderbolt / "0-1"
        (router / "authorized").write_text("1", encoding="utf-8")
        (router / "device_name").unlink()

    def unreadable_trust_state(self) -> None:
        """The one attribute the readback exists to read stops reading.

        Every other half of the readback is intact -- present, named,
        addressable, the same dock at the same generation -- so the tri-state
        on `authorized` is the only thing left that can answer.
        """
        (self.sysfs.thunderbolt / "0-1" / "authorized").unlink()

    def test_a_readback_of_a_dock_nobody_could_name_verifies_nothing(self):
        """`identity_resolved` False with a uuid still sitting there.

        The trap is that this reads `authorized` as trusted, so anything that
        forwards the uuid to `record_verification` gets a confident
        `verified=True` for a device the re-read could not identify -- which is
        exactly the claim a panel renders as "your dock is now trusted".
        """
        payload = self.act_while(self.unnamed_but_addressable)
        readback = self.sysfs.observer().observe()
        self.assertFalse(
            readback.identity_resolved,
            "the fixture did not produce an unresolved identity",
        )
        self.assertTrue(
            readback.uuid,
            "the uuid emptied, so the readback's own empty-id guard answers "
            "this and the delivery layer's is never reached",
        )
        self.assertIs(readback.authorized, True)
        self.assertIs(payload["requested"], True)
        self.assertIsNone(
            payload["verified"],
            "a dock nobody could name was reported as verified",
        )
        self.assertEqual(self.argvs, [granted(self.attached)])

    def test_a_readback_that_could_not_read_the_state_verifies_nothing(self):
        """The purest "nobody managed to look", and it is not a `False`.

        `False` is a panel saying the grant did not work; `None` is a panel
        saying nobody can tell yet.  The outcome's own field documents them as
        different facts, and a readback whose `authorized` is itself unreadable
        is the one case where only the tri-state can keep them apart.
        """
        payload = self.act_while(self.unreadable_trust_state)
        readback = self.sysfs.observer().observe()
        self.assertTrue(
            readback.identity_resolved,
            "the fixture broke the identity as well, so this case is the "
            "one above rather than an unreadable trust state",
        )
        self.assertIsNone(readback.authorized)
        self.assertIs(payload["requested"], True)
        self.assertIsNone(
            payload["verified"],
            "an unreadable trust state was reported as untrusted",
        )
        self.assertEqual(self.argvs, [granted(self.attached)])

    def test_an_unreadable_identity_on_the_readback_verifies_nothing(self):
        payload = self.act_while(self.unreadable_identity)
        self.assertIs(payload["requested"], True)
        self.assertIsNone(
            payload["verified"],
            "an unidentifiable re-read answered True or False",
        )
        self.assertEqual(payload["vendor"], VENDOR)
        self.assertEqual(payload["model"], MODEL)
        self.assertEqual(self.argvs, [granted(self.attached)])

    def test_a_device_replaced_during_the_act_verifies_nothing(self):
        payload = self.act_while(self.replaced)
        self.assertIs(payload["requested"], True)
        self.assertIsNone(
            payload["verified"],
            "somebody else's device answered for the one that was acted on",
        )
        self.assertEqual(
            payload["model"],
            MODEL,
            "the payload named the device that arrived, not the one acted on",
        )
        self.assertEqual(self.argvs, [granted(self.attached)])
        self.assertNotIn(VARIED_UUID, self.argvs[0])

    def test_a_readback_of_the_device_that_was_acted_on_still_verifies(self):
        """So that `None` above is a refusal and not simply the only answer."""
        payload = self.act_while(
            lambda: (self.sysfs.thunderbolt / "0-1" / "authorized").write_text(
                "1", encoding="utf-8"
            )
        )
        self.assertIs(payload["requested"], True)
        self.assertIs(payload["verified"], True)
        self.assertEqual(self.argvs, [granted(self.attached)])


if __name__ == "__main__":
    unittest.main()
