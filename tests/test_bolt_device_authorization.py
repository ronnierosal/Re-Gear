"""Enrolling one named device, and refusing everything that is not one.

The UUID is the only caller-supplied value that reaches a command line in this
feature, so most of this is about the boundary refusing rather than quoting.
The rest is that a zero exit is reported as *accepted*, never as verified --
`boltctl` returning 0 says the request was taken, not that the device is now
trusted.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.commands import (  # noqa: E402
    BoltDeviceAuthorizationRunner,
)


#: The dock's real id, as `boltctl list` prints it.
VALID = "b9010000-0072-741e-03c4-fed98ab0a808"


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
        "b9010000_0072_741e_03c4_fed98ab0a808",
        None,
        1,
        b"b9010000-0072-741e-03c4-fed98ab0a808",
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


if __name__ == "__main__":
    unittest.main()
