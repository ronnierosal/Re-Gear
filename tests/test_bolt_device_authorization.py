"""Granting trust to one named device, and refusing everything that is not one.

The UUID is the only caller-supplied value that reaches a command line in this
feature, so most of this is about the boundary refusing rather than quoting.
The rest is that a zero exit is reported as *accepted*, never as verified --
`boltctl` returning 0 says the request was taken, not that the device is now
trusted.

There are two grants. `enroll` stores the device with the `auto` policy;
`authorize` trusts it for this attachment and stores nothing. They now share
one subprocess boundary, so the tests below the enrolment ones are mostly
about the DIFFERENCE between them -- an argv or an outcome code belonging to
one action leaking into the other is what a shared helper makes easy.
"""

from __future__ import annotations

import dataclasses
import inspect
import os
import subprocess
import sys
import unittest
from dataclasses import fields
from pathlib import Path
from typing import Protocol, get_type_hints, runtime_checkable
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.commands import (  # noqa: E402
    BoltDeviceAuthorizationRunner,
)
from regear.ports.device_authorization import (  # noqa: E402
    DeviceAuthorizationPort,
    DeviceEnrollmentResult,
)


#: Synthetic, and deliberately so. A Thunderbolt router UUID is a hardware
#: unique id, which SAFETY_INVARIANTS #12 requires redacted -- committing a
#: real one as a fixture would put the maintainer's own dock in the repo.
VALID = "0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d"


class Completed:
    def __init__(self, returncode):
        self.returncode = returncode
        self.stdout = b""
        self.stderr = b""


def runner(uid=0, **kwargs):
    return BoltDeviceAuthorizationRunner(effective_uid=lambda: uid, **kwargs)


class TheArgvIsFixedExceptTheDevice(unittest.TestCase):
    def test_it_enrolls_with_the_auto_policy(self):
        """`auto` is what Desktop Mode stores, so behaviour matches afterwards."""
        self.assertEqual(
            BoltDeviceAuthorizationRunner.argv(VALID),
            ("/usr/bin/boltctl", "enroll", "--policy", "auto", VALID),
        )

    def test_it_never_passes_chain(self):
        """`--chain` would trust parents the player was never shown."""
        self.assertNotIn("--chain", BoltDeviceAuthorizationRunner.argv(VALID))

    def test_it_uses_an_absolute_binary_path(self):
        self.assertTrue(
            BoltDeviceAuthorizationRunner.argv(VALID)[0].startswith("/")
        )


class AnythingThatIsNotADeviceIdIsRefused(unittest.TestCase):
    REJECTED = (
        "",
        "not-a-uuid",
        VALID.upper(),
        VALID + " --chain",
        VALID + "\nenroll",
        "; rm -rf /",
        VALID[:-1],
        VALID + "0",
        " " + VALID,
        VALID + " ",
        "0a1b2c3d_4e5f_6a7b_8c9d_0e1f2a3b4c5d",
        None,
        1,
        b"0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d",
        ["--policy", "manual"],
    )

    def test_argv_raises_rather_than_quoting(self):
        for value in self.REJECTED:
            with self.subTest(uuid=repr(value)):
                with self.assertRaises(ValueError):
                    BoltDeviceAuthorizationRunner.argv(value)

    def test_enroll_refuses_without_running_anything(self):
        for value in self.REJECTED:
            with self.subTest(uuid=repr(value)):
                with patch.object(subprocess, "run") as run:
                    result = runner().enroll(value)
                self.assertFalse(result.enrolled)
                self.assertEqual(result.code, "device_authorization.uuid_invalid")
                run.assert_not_called()

    def test_a_valid_uuid_is_accepted(self):
        self.assertEqual(BoltDeviceAuthorizationRunner.argv(VALID)[-1], VALID)


class ItNeedsRootAndSaysSo(unittest.TestCase):
    def test_a_non_root_process_refuses_without_running_anything(self):
        with patch.object(subprocess, "run") as run:
            result = runner(uid=1000).enroll(VALID)
        self.assertFalse(result.enrolled)
        self.assertEqual(result.code, "device_authorization.root_required")
        run.assert_not_called()

    def test_the_uuid_is_checked_before_privilege(self):
        """A bad id is refused even for root, and names the real problem."""
        self.assertEqual(
            runner(uid=1000).enroll("nonsense").code,
            "device_authorization.uuid_invalid",
        )


class TheOutcomeIsHonest(unittest.TestCase):
    def test_a_zero_exit_is_accepted_not_verified(self):
        with patch.object(subprocess, "run", return_value=Completed(0)):
            result = runner().enroll(VALID)
        self.assertTrue(result.enrolled)
        self.assertEqual(
            result.code, "device_authorization.enroll_accepted_unverified"
        )

    def test_a_nonzero_exit_is_a_failure(self):
        with patch.object(subprocess, "run", return_value=Completed(1)):
            result = runner().enroll(VALID)
        self.assertFalse(result.enrolled)
        self.assertEqual(result.code, "device_authorization.enroll_failed")

    def test_a_timeout_is_reported_as_itself(self):
        with patch.object(
            subprocess, "run", side_effect=subprocess.TimeoutExpired("boltctl", 15)
        ):
            result = runner().enroll(VALID)
        self.assertFalse(result.enrolled)
        self.assertEqual(result.code, "device_authorization.enroll_timeout")

    def test_a_missing_binary_is_unavailable_not_failed(self):
        with patch.object(subprocess, "run", side_effect=OSError("no boltctl")):
            result = runner().enroll(VALID)
        self.assertFalse(result.enrolled)
        self.assertEqual(result.code, "device_authorization.enroll_unavailable")


class ThePortDeclaresBothGrants(unittest.TestCase):
    """The boundary the runner is measured against, not the runner itself.

    `authorize` is the one-shot grant that stores nothing, and it exists on the
    port so a caller can offer "just this once" without inventing a second
    interface. The runner now implements both; that it does, and that its
    signatures match what is declared here, is asserted by
    `TheRunnerSatisfiesTheAuthorizationPort` further down. This class stays
    about the port itself -- the boundary the runner is measured against.
    """

    def test_the_protocol_names_enroll_and_authorize(self):
        """Both grants, declared here, each taking one device and answering
        the honest result type.

        This used to assert `callable(getattr(Port, name))`, which nothing
        could fail: `getattr` raises before the assertion on a name that is
        gone, and anything it does find on a Protocol class is callable by
        construction, so the assertion itself measured nothing. What a caller
        dispatching on the player's chosen action actually depends on is the
        shape -- the name being declared on this Protocol rather than
        inherited from the Protocol machinery, exactly one `uuid` parameter
        after `self` with no default that would let a call omit the device,
        and `DeviceEnrollmentResult` coming back. A grant renamed, dropped, or
        given a second parameter fails here now.
        """
        for name in ("enroll", "authorize"):
            with self.subTest(grant=name):
                declared = vars(DeviceAuthorizationPort).get(name)
                self.assertIsNotNone(
                    declared, f"the port no longer declares {name}"
                )
                self.assertTrue(inspect.isfunction(declared))

                # `eval_str` because the port module uses postponed
                # annotations, so every annotation here is a string until it
                # is resolved against that module's own globals.
                signature = inspect.signature(declared, eval_str=True)

                self.assertEqual(
                    [parameter for parameter in signature.parameters],
                    ["self", "uuid"],
                )
                uuid = signature.parameters["uuid"]
                self.assertIs(uuid.annotation, str)
                self.assertIs(uuid.kind, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                self.assertIs(uuid.default, inspect.Parameter.empty)
                self.assertIs(
                    signature.return_annotation, DeviceEnrollmentResult
                )

    def test_both_grants_answer_with_the_same_honest_result_type(self):
        """Accepted-not-verified is the promise for either action."""
        for name in ("enroll", "authorize"):
            with self.subTest(action=name):
                hints = get_type_hints(getattr(DeviceAuthorizationPort, name))
                self.assertIs(hints["return"], DeviceEnrollmentResult)
                self.assertIs(hints["uuid"], str)

    def test_the_runner_returns_that_result_type(self):
        with patch.object(subprocess, "run", return_value=Completed(0)):
            result = runner().enroll(VALID)
        self.assertIsInstance(result, DeviceEnrollmentResult)


class TheSubprocessCallIsSafe(unittest.TestCase):
    def test_no_shell_and_a_clean_environment(self):
        with patch.object(subprocess, "run", return_value=Completed(0)) as run:
            runner().enroll(VALID)
        _, kwargs = run.call_args
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["env"]["PATH"], "/usr/bin:/bin")
        self.assertIn("timeout", kwargs)

    def test_the_argv_passed_is_the_validated_tuple(self):
        with patch.object(subprocess, "run", return_value=Completed(0)) as run:
            runner().enroll(VALID)
        args, _ = run.call_args
        self.assertEqual(args[0], BoltDeviceAuthorizationRunner.argv(VALID))



# ---------------------------------------------------------------------------
# The one-shot grant, and the difference between the two grants.
#
# Everything above this line was written when `enroll` was the only grant.
# Everything below is about `authorize` -- and, more to the point, about the
# DIFFERENCE, because the two now share one subprocess boundary and a shared
# helper is exactly where one action's argv or one action's outcome code leaks
# into the other.
# ---------------------------------------------------------------------------


GRANTS = ("enroll", "authorize")

#: The two argv builders, keyed by the grant they belong to. Captured off the
#: class so a test can drive both through the same loop and name which one it
#: was looking at when it failed.
BUILDERS = {
    "enroll": BoltDeviceAuthorizationRunner.argv,
    "authorize": BoltDeviceAuthorizationRunner.authorize_argv,
}

#: What `argv` returned BEFORE the one-shot grant landed, written out as a
#: literal rather than derived from the class under test. Preserving enrolment
#: unchanged is the requirement that this whole change was allowed under, and
#: a regression test that builds its expectation by calling the code it is
#: testing cannot notice that code changing.
ENROLMENT_ARGV_BEFORE_THE_ONE_SHOT_GRANT = (
    "/usr/bin/boltctl",
    "enroll",
    "--policy",
    "auto",
    "0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d",
)

#: And what the one-shot grant must be: the verb, the device, nothing else.
ONE_SHOT_ARGV = (
    "/usr/bin/boltctl",
    "authorize",
    "0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d",
)

#: Every value that is not a device id. Both builders must refuse each of
#: these rather than quote it: with `shell=False` a stray argument cannot be
#: reinterpreted by a shell, but it would still arrive at `boltctl` as its own
#: word, and a `--chain` smuggled in that way would authorize parent devices
#: the player was never shown.
#:
#: The second half of this tuple is what makes the match a `fullmatch` rather
#: than a `search`; see `ADeviceIdWithAnythingAroundItIsRefused` for which of
#: these actually carry that weight.
NOT_A_DEVICE_ID = (
    # Nothing resembling a device id anywhere in the value.
    "",
    "not-a-uuid",
    VALID.upper(),
    "; rm -rf /",
    VALID[:-1],
    "0a1b2c3d_4e5f_6a7b_8c9d_0e1f2a3b4c5d",
    None,
    1,
    b"0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d",
    ["--policy", "manual"],
    # A well-formed device id, with something else attached to it.
    VALID + " --chain",
    VALID + "\nenroll",
    VALID + "0",
    " " + VALID,
    VALID + " ",
    VALID + "\x00",
    "\x00" + VALID,
    VALID + "\x00--chain",
)

#: One `subprocess.run` behaviour per outcome, the code suffix the grant must
#: report for it, and whether the request counts as accepted. Driven over both
#: grants so that a code belonging to one action showing up on the other is a
#: failure rather than a coincidence nobody looked at.
OUTCOMES = (
    ("accepted_unverified", True, {"return_value": Completed(0)}, "a zero exit"),
    ("failed", False, {"return_value": Completed(1)}, "a non-zero exit"),
    ("failed", False, {"return_value": Completed(127)}, "a not-found exit"),
    ("failed", False, {"return_value": Completed(-9)}, "a killed command"),
    (
        "timeout",
        False,
        {"side_effect": subprocess.TimeoutExpired("boltctl", 15)},
        "a timeout",
    ),
    (
        "unavailable",
        False,
        {"side_effect": OSError("no boltctl")},
        "a missing binary",
    ),
    (
        "unavailable",
        False,
        {"side_effect": subprocess.SubprocessError("boltd went away")},
        "a subprocess error",
    ),
    (
        "unavailable",
        False,
        {"side_effect": subprocess.CalledProcessError(1, "boltctl")},
        "a called-process error",
    ),
)


class TheOneShotArgvIsTheAuthorizeVerbAndNothingElse(unittest.TestCase):
    """`boltctl authorize <uuid>` -- three words, and each one is load-bearing."""

    def test_it_is_exactly_the_binary_the_verb_and_the_device(self):
        self.assertEqual(
            BoltDeviceAuthorizationRunner.authorize_argv(VALID), ONE_SHOT_ARGV
        )

    def test_it_carries_no_policy_at_all(self):
        """Policy is a property of a STORED device.

        Passing one here would ask `boltd` to remember a decision the player
        was told would not be remembered, which is the entire difference
        between this grant and enrolment. Checked as substrings as well as
        whole words, because `--policy=auto` would satisfy a membership test
        while still storing the device.
        """
        argv = BoltDeviceAuthorizationRunner.authorize_argv(VALID)
        self.assertNotIn("--policy", argv)
        self.assertNotIn("auto", argv)
        for word in argv:
            with self.subTest(word=word):
                self.assertNotIn("--policy", word)
                self.assertNotIn("policy", word)
                self.assertNotIn("auto", word)

    def test_neither_grant_ever_chains_to_parent_devices(self):
        """`--chain` would trust hardware the player was never shown.

        It is absent from enrolment for that reason and must stay absent from
        the one-shot grant for the same one -- a "just this once" that quietly
        authorized the hub the dock is plugged into would be a worse promise
        than the one it replaced.
        """
        for action, build in BUILDERS.items():
            argv = build(VALID)
            with self.subTest(grant=action):
                self.assertNotIn("--chain", argv)
                for word in argv:
                    self.assertNotIn("--chain", word)
                    self.assertNotIn("chain", word)

    def test_it_uses_the_same_absolute_binary_as_enrolment(self):
        argv = BoltDeviceAuthorizationRunner.authorize_argv(VALID)
        self.assertEqual(argv[0], BoltDeviceAuthorizationRunner.argv(VALID)[0])
        self.assertTrue(argv[0].startswith("/"))

    def test_every_word_is_a_string(self):
        """A stray bytes or int word would reach `execve` as a type error at
        the worst possible moment -- with root, on the player's hardware."""
        for word in BoltDeviceAuthorizationRunner.authorize_argv(VALID):
            with self.subTest(word=repr(word)):
                self.assertIsInstance(word, str)


class TheEnrolmentGrantIsUnchanged(unittest.TestCase):
    """The regression that matters most: enrolment was required preserved.

    The one-shot grant was added by routing `enroll` through a shared helper.
    That is the edit most likely to have moved enrolment by accident, so this
    pins what enrolment was before it, from a literal.
    """

    def test_the_argv_is_what_it_was_before_the_one_shot_grant_landed(self):
        self.assertEqual(
            BoltDeviceAuthorizationRunner.argv(VALID),
            ENROLMENT_ARGV_BEFORE_THE_ONE_SHOT_GRANT,
        )

    def test_the_literal_above_still_describes_this_device(self):
        """Keeps the pinned tuple honest if `VALID` is ever re-rolled."""
        self.assertEqual(ENROLMENT_ARGV_BEFORE_THE_ONE_SHOT_GRANT[-1], VALID)

    def test_it_is_still_callable_without_an_instance(self):
        """`argv` is a classmethod, and callers reach for it that way."""
        self.assertIsInstance(
            inspect.getattr_static(BoltDeviceAuthorizationRunner, "argv"),
            classmethod,
        )
        self.assertIsInstance(
            inspect.getattr_static(
                BoltDeviceAuthorizationRunner, "authorize_argv"
            ),
            classmethod,
        )

    def test_its_outcome_codes_still_say_enroll(self):
        for suffix, accepted, behaviour, why in OUTCOMES:
            with self.subTest(outcome=why):
                with patch.object(subprocess, "run", **behaviour):
                    result = runner().enroll(VALID)
                self.assertIs(result.enrolled, accepted)
                self.assertEqual(
                    result.code, f"device_authorization.enroll_{suffix}"
                )


class TheTwoGrantsDifferOnlyInTheGrant(unittest.TestCase):
    """The difference, pinned as a difference rather than as two constants.

    Asserting each argv separately would still pass if someone gave the
    one-shot grant a policy and updated its expected tuple to match. These
    compare the two.
    """

    def test_the_verb_is_the_difference(self):
        enrol = BoltDeviceAuthorizationRunner.argv(VALID)
        one_shot = BoltDeviceAuthorizationRunner.authorize_argv(VALID)
        self.assertEqual(enrol[1], "enroll")
        self.assertEqual(one_shot[1], "authorize")
        self.assertNotEqual(enrol[1], one_shot[1])

    def test_only_enrolment_carries_a_policy(self):
        enrol = set(BoltDeviceAuthorizationRunner.argv(VALID))
        one_shot = set(BoltDeviceAuthorizationRunner.authorize_argv(VALID))
        self.assertEqual(enrol - one_shot, {"enroll", "--policy", "auto"})
        self.assertEqual(one_shot - enrol, {"authorize"})

    def test_the_one_shot_grant_is_the_shorter_of_the_two(self):
        self.assertEqual(
            len(BoltDeviceAuthorizationRunner.authorize_argv(VALID)), 3
        )
        self.assertEqual(len(BoltDeviceAuthorizationRunner.argv(VALID)), 5)

    def test_the_device_is_last_in_both_and_appears_once(self):
        for action, build in BUILDERS.items():
            argv = build(VALID)
            with self.subTest(grant=action):
                self.assertEqual(argv[-1], VALID)
                self.assertEqual(list(argv).count(VALID), 1)


class BothGrantsRefuseAnythingThatIsNotADeviceId(unittest.TestCase):
    """The refusal is the same refusal, not two that happen to agree today."""

    def test_both_builders_raise_rather_than_quoting(self):
        for value in NOT_A_DEVICE_ID:
            for action, build in BUILDERS.items():
                with self.subTest(uuid=repr(value), grant=action):
                    with self.assertRaises(ValueError):
                        build(value)

    def test_both_builders_refuse_identically(self):
        """Same exception type, same message -- one validation, not two.

        Compared against each other rather than against a literal, so the
        wording stays free to change as long as it changes for both.
        """
        for value in NOT_A_DEVICE_ID:
            with self.subTest(uuid=repr(value)):
                with self.assertRaises(ValueError) as enrolment:
                    BoltDeviceAuthorizationRunner.argv(value)
                with self.assertRaises(ValueError) as one_shot:
                    BoltDeviceAuthorizationRunner.authorize_argv(value)
                self.assertIs(
                    type(enrolment.exception), type(one_shot.exception)
                )
                self.assertEqual(
                    str(enrolment.exception), str(one_shot.exception)
                )

    def test_neither_grant_runs_anything_for_one(self):
        for value in NOT_A_DEVICE_ID:
            for action in GRANTS:
                with self.subTest(uuid=repr(value), grant=action):
                    with patch.object(subprocess, "run") as run:
                        result = getattr(runner(), action)(value)
                    self.assertFalse(result.enrolled)
                    self.assertEqual(
                        result.code, "device_authorization.uuid_invalid"
                    )
                    run.assert_not_called()

    def test_the_device_is_checked_before_privilege_on_both(self):
        """A bad id names the real problem even when the process is not root."""
        for action in GRANTS:
            with self.subTest(grant=action):
                result = getattr(runner(uid=1000), action)("nonsense")
                self.assertEqual(
                    result.code, "device_authorization.uuid_invalid"
                )


class ADeviceIdWithAnythingAroundItIsRefused(unittest.TestCase):
    """The match is anchored at BOTH ends, and this is what proves it.

    Mutation-tested. A scratch copy of the adapter with `UUID.fullmatch`
    changed to `UUID.search` in both builders is killed by every value in this
    class and by nothing else in `NOT_A_DEVICE_ID`: each of these contains a
    well-formed device id that `search` finds and then hands to `boltctl` with
    the rest of the string still attached, while the values that contain no
    device id at all -- the empty string, uppercase hex, a truncated id, the
    non-`str` values -- are refused by the pattern or by the type check either
    way and so say nothing about anchoring. Those are worth keeping; they are
    just not this evidence.

    `\\x00` matters on its own: the argv reaches `execve`, which reads a NUL
    as the end of the argument, so a value the validator accepted and a value
    the kernel acts on would be different strings. CPython raises on an
    embedded NUL today, but that is CPython's guard, not this boundary's.
    """

    ANCHORED = (
        (VALID + " --chain", "a smuggled flag"),
        (VALID + "\nenroll", "an embedded newline"),
        (" " + VALID, "a leading space"),
        (VALID + " ", "a trailing space"),
        (VALID + "0", "a trailing character"),
        (VALID + "\x00", "a trailing NUL byte"),
        ("\x00" + VALID, "a leading NUL byte"),
        (VALID + "\x00--chain", "a flag hidden behind a NUL byte"),
    )

    def test_every_one_of_these_contains_a_real_device_id(self):
        """Otherwise the class below would be proving something easier."""
        for value, why in self.ANCHORED:
            with self.subTest(rejected=why):
                self.assertIn(VALID, value)

    def test_neither_builder_accepts_one(self):
        for value, why in self.ANCHORED:
            for action, build in BUILDERS.items():
                with self.subTest(rejected=why, grant=action):
                    with self.assertRaises(ValueError):
                        build(value)

    def test_neither_grant_runs_anything_for_one(self):
        for value, why in self.ANCHORED:
            for action in GRANTS:
                with self.subTest(rejected=why, grant=action):
                    with patch.object(subprocess, "run") as run:
                        result = getattr(runner(), action)(value)
                    self.assertEqual(
                        result.code, "device_authorization.uuid_invalid"
                    )
                    run.assert_not_called()


class TheOneShotGrantReportsWhatHappenedToTheCommand(unittest.TestCase):
    def test_each_outcome_has_its_own_code(self):
        for suffix, accepted, behaviour, why in OUTCOMES:
            with self.subTest(outcome=why):
                with patch.object(subprocess, "run", **behaviour):
                    result = runner().authorize(VALID)
                self.assertIs(result.enrolled, accepted)
                self.assertEqual(
                    result.code, f"device_authorization.authorize_{suffix}"
                )

    def test_a_timeout_is_not_swallowed_as_unavailable(self):
        """`TimeoutExpired` IS a `SubprocessError`.

        The handler that reports `unavailable` catches `SubprocessError`, so
        the two clauses only stay distinguishable while the timeout clause is
        written first. Reordering them turns "the dock did not answer in
        fifteen seconds" into "boltctl is missing", which sends the player to
        reinstall something that was never broken.
        """
        with patch.object(
            subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("boltctl", 15),
        ):
            result = runner().authorize(VALID)
        self.assertEqual(result.code, "device_authorization.authorize_timeout")

    def test_an_invalid_device_id_is_refused_before_anything_runs(self):
        with patch.object(subprocess, "run") as run:
            result = runner().authorize("not-a-uuid")
        self.assertFalse(result.enrolled)
        self.assertEqual(result.code, "device_authorization.uuid_invalid")
        run.assert_not_called()

    def test_a_non_root_process_is_refused_before_anything_runs(self):
        with patch.object(subprocess, "run") as run:
            result = runner(uid=1000).authorize(VALID)
        self.assertFalse(result.enrolled)
        self.assertEqual(result.code, "device_authorization.root_required")
        run.assert_not_called()

    def test_it_answers_the_honest_result_type(self):
        with patch.object(subprocess, "run", return_value=Completed(0)):
            result = runner().authorize(VALID)
        self.assertIsInstance(result, DeviceEnrollmentResult)


class NeitherGrantWearsTheOthersCode(unittest.TestCase):
    """The obvious defect in a shared helper, looked for directly.

    `_grant` takes the action name as an argument and formats every outcome
    code from it. Passing the wrong one at either call site -- or hardcoding
    one action's name inside the helper -- compiles, runs, and reports the
    player's one-shot grant as an enrolment.
    """

    def test_every_outcome_names_the_action_that_produced_it(self):
        for suffix, accepted, behaviour, why in OUTCOMES:
            for action in GRANTS:
                other = "authorize" if action == "enroll" else "enroll"
                with self.subTest(outcome=why, grant=action):
                    with patch.object(subprocess, "run", **behaviour):
                        result = getattr(runner(), action)(VALID)
                    self.assertEqual(
                        result.code, f"device_authorization.{action}_{suffix}"
                    )
                    self.assertNotIn(other, result.code)

    def test_the_two_grants_never_produce_the_same_outcome_code(self):
        for suffix, accepted, behaviour, why in OUTCOMES:
            with self.subTest(outcome=why):
                codes = set()
                for action in GRANTS:
                    with patch.object(subprocess, "run", **behaviour):
                        codes.add(getattr(runner(), action)(VALID).code)
                self.assertEqual(len(codes), len(GRANTS))

    def test_the_refusals_before_the_command_name_no_action_at_all(self):
        """`uuid_invalid` and `root_required` are shared on purpose.

        Nothing was attempted, so there is no action to report -- and the
        caller distinguishes them by the action it asked for, not by the code.
        """
        shared = {
            "device_authorization.uuid_invalid": lambda action: getattr(
                runner(), action
            )("not-a-uuid"),
            "device_authorization.root_required": lambda action: getattr(
                runner(uid=1000), action
            )(VALID),
        }
        for expected, call in shared.items():
            for action in GRANTS:
                with self.subTest(code=expected, grant=action):
                    with patch.object(subprocess, "run"):
                        result = call(action)
                    self.assertEqual(result.code, expected)
                    self.assertNotIn("enroll", result.code)
                    self.assertNotIn("authorize", result.code)


class TheSubprocessCallIsSafeForBothGrants(unittest.TestCase):
    """One code path now serves both grants, so a regression hits both.

    Every assertion here is driven over `enroll` and `authorize` for that
    reason: checking the shared boundary through one grant only would leave
    the other untested by argument, and "it is the same code" is the claim
    under test rather than a reason not to test it.
    """

    def _call(self, action, **construction):
        with patch.object(
            subprocess, "run", return_value=Completed(0)
        ) as run:
            getattr(runner(**construction), action)(VALID)
        run.assert_called_once()
        return run.call_args

    def test_no_shell_no_text_no_raise_and_output_captured(self):
        for action in GRANTS:
            with self.subTest(grant=action):
                _, kwargs = self._call(action)
                self.assertIs(kwargs["shell"], False)
                self.assertIs(kwargs["text"], False)
                self.assertIs(kwargs["check"], False)
                self.assertIs(kwargs["capture_output"], True)

    def test_the_environment_is_the_clean_one_and_nothing_inherited(self):
        """`os.environ` must not reach a root subprocess.

        `LD_PRELOAD` is the concrete reason: inherited into a command running
        as root it chooses what code that command loads. The sentinel proves
        absence of inheritance rather than merely presence of the three
        variables, which `{**os.environ, **CLEAN_ENVIRONMENT}` would also
        satisfy.
        """
        for action in GRANTS:
            with self.subTest(grant=action):
                with patch.dict(
                    os.environ,
                    {
                        "REGEAR_LEAKED": "yes",
                        "LD_PRELOAD": "/tmp/not-a-real-library.so",
                    },
                ):
                    _, kwargs = self._call(action)
                self.assertEqual(
                    kwargs["env"],
                    {"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
                )
                self.assertNotIn("REGEAR_LEAKED", kwargs["env"])
                self.assertNotIn("LD_PRELOAD", kwargs["env"])

    def test_the_environment_handed_over_is_a_copy(self):
        """A callee that mutated it would poison every later grant."""
        for action in GRANTS:
            with self.subTest(grant=action):
                _, kwargs = self._call(action)
                self.assertIsNot(
                    kwargs["env"],
                    BoltDeviceAuthorizationRunner.CLEAN_ENVIRONMENT,
                )
                kwargs["env"]["PATH"] = "/tmp"
                self.assertEqual(
                    BoltDeviceAuthorizationRunner.CLEAN_ENVIRONMENT["PATH"],
                    "/usr/bin:/bin",
                )

    def test_the_configured_timeout_is_the_one_passed(self):
        for action in GRANTS:
            with self.subTest(grant=action):
                _, kwargs = self._call(action, timeout_seconds=7.5)
                self.assertEqual(kwargs["timeout"], 7.5)
                _, default = self._call(action)
                self.assertEqual(default["timeout"], 15.0)

    def test_the_argv_passed_is_that_grants_validated_tuple(self):
        for action in GRANTS:
            with self.subTest(grant=action):
                args, _ = self._call(action)
                self.assertEqual(len(args), 1)
                self.assertEqual(args[0], BUILDERS[action](VALID))
                self.assertIsInstance(args[0], tuple)

    def test_the_one_shot_grant_does_not_run_the_enrolment_argv(self):
        """The mistake a shared helper invites: the wrong builder passed in."""
        args, _ = self._call("authorize")
        self.assertEqual(args[0], ONE_SHOT_ARGV)
        self.assertNotEqual(
            args[0], ENROLMENT_ARGV_BEFORE_THE_ONE_SHOT_GRANT
        )

    def test_exactly_one_command_is_run_per_grant(self):
        for action in GRANTS:
            with self.subTest(grant=action):
                with patch.object(
                    subprocess, "run", return_value=Completed(0)
                ) as run:
                    getattr(runner(), action)(VALID)
                self.assertEqual(run.call_count, 1)


class TheRunnerSatisfiesTheAuthorizationPort(unittest.TestCase):
    """Both grants, with the shape the port declares.

    The port is a plain `Protocol`, so nothing checks this at import time and
    a runner that grew `authorize(self, uuid, policy)` would be accepted by
    every type-free call site until one of them passed only a device.
    """

    def test_both_grants_are_implemented_here_not_inherited(self):
        for name in GRANTS:
            with self.subTest(grant=name):
                implemented = vars(BoltDeviceAuthorizationRunner).get(name)
                self.assertIsNotNone(
                    implemented, f"the runner does not implement {name}"
                )
                self.assertTrue(inspect.isfunction(implemented))

    def test_both_grants_match_the_signature_the_port_declares(self):
        for name in GRANTS:
            with self.subTest(grant=name):
                declared = inspect.signature(
                    vars(DeviceAuthorizationPort)[name], eval_str=True
                )
                implemented = inspect.signature(
                    vars(BoltDeviceAuthorizationRunner)[name], eval_str=True
                )
                self.assertEqual(
                    list(implemented.parameters), list(declared.parameters)
                )
                uuid = implemented.parameters["uuid"]
                self.assertIs(uuid.annotation, str)
                self.assertIs(uuid.default, inspect.Parameter.empty)
                self.assertIs(
                    implemented.return_annotation, DeviceEnrollmentResult
                )

    def test_an_instance_presents_both_grants(self):
        @runtime_checkable
        class _BothGrants(DeviceAuthorizationPort, Protocol):
            pass

        self.assertIsInstance(runner(), _BothGrants)

    def test_it_works_when_called_through_the_port(self):
        def grant(port: DeviceAuthorizationPort, action: str):
            return getattr(port, action)(VALID)

        for name in GRANTS:
            with self.subTest(grant=name):
                with patch.object(
                    subprocess, "run", return_value=Completed(0)
                ):
                    result = grant(runner(), name)
                self.assertIsInstance(result, DeviceEnrollmentResult)


class TheResultCannotBeEditedAfterTheFact(unittest.TestCase):
    """An outcome is a record of what happened, not a mutable opinion.

    `DeviceEnrollmentResult` travels from the executor out through the service
    and into a payload.  If a later layer could rewrite `enrolled`, the honest
    distinction this whole feature rests on -- that a request was accepted is
    not that a device is trusted -- would be one assignment away from being
    lost, and nothing would record that it had been.

    Pinned because dropping `frozen=True` left the entire suite green.
    """

    def test_the_outcome_is_frozen(self):
        result = DeviceEnrollmentResult(True, "device_authorization.ok")
        for field, value in (("enrolled", False), ("code", "tampered")):
            with self.subTest(field=field):
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    setattr(result, field, value)
        self.assertIs(result.enrolled, True)
        self.assertEqual(result.code, "device_authorization.ok")

    def test_the_outcome_is_hashable_so_it_can_be_recorded(self):
        first = DeviceEnrollmentResult(True, "device_authorization.ok")
        second = DeviceEnrollmentResult(True, "device_authorization.ok")
        self.assertEqual(hash(first), hash(second))
        self.assertEqual({first, second}, {first})


class AcceptedIsNeverVerified(unittest.TestCase):
    """A zero exit says the request was taken. It says nothing else.

    This matters more on the one-shot grant than on enrolment, because
    `enrolled=True` coming back from `authorize` reads like "the device was
    enrolled" to anyone skimming, and it means neither that nor "the device is
    now trusted".
    """

    def test_a_zero_exit_is_reported_as_requested_on_both_grants(self):
        for action in GRANTS:
            with self.subTest(grant=action):
                with patch.object(
                    subprocess, "run", return_value=Completed(0)
                ) as run:
                    result = getattr(runner(), action)(VALID)
                self.assertIs(result.enrolled, True)
                self.assertTrue(result.code.endswith("_accepted_unverified"))
                # It did not go and look: verifying is the caller's job, and a
                # second command here would be this boundary deciding it knows.
                self.assertEqual(run.call_count, 1)

    def test_the_result_carries_no_field_claiming_trust(self):
        self.assertEqual(
            [field.name for field in fields(DeviceEnrollmentResult)],
            ["enrolled", "code"],
        )

    def test_no_outcome_code_claims_the_device_is_trusted(self):
        for suffix, accepted, behaviour, why in OUTCOMES:
            for action in GRANTS:
                with self.subTest(outcome=why, grant=action):
                    with patch.object(subprocess, "run", **behaviour):
                        code = getattr(runner(), action)(VALID).code
                    self.assertNotIn("trusted", code)
                    self.assertNotIn("verified", code.replace("unverified", ""))

    def test_an_accepted_one_shot_grant_stored_nothing(self):
        """`enrolled=True` from `authorize` is a statement about the command.

        The proof that nothing was stored is the argv that actually ran: no
        `enroll`, no `--policy`.
        """
        with patch.object(subprocess, "run", return_value=Completed(0)) as run:
            result = runner().authorize(VALID)
        self.assertIs(result.enrolled, True)
        argv = run.call_args.args[0]
        self.assertEqual(argv, ONE_SHOT_ARGV)
        self.assertNotIn("enroll", argv)
        self.assertNotIn("--policy", argv)

if __name__ == "__main__":
    unittest.main()
