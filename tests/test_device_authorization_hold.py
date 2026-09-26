"""Remembered-trust hold: fixed boltctl policy calls and durable binding."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.adapters.steamos.commands import BoltDeviceAuthorizationRunner
from regear.delivery.device_authorization_hold import (
    DeviceAuthorizationHold,
    DeviceAuthorizationHoldStore,
)
from regear.delivery.whole_dock_claim import WholeDockClaimStore
UUID = "0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d"


class Completed:
    def __init__(self, returncode=0, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = b""


class BoltPolicyCommandTests(unittest.TestCase):
    def setUp(self):
        self.runner = BoltDeviceAuthorizationRunner(effective_uid=lambda: 0)

    def test_policy_argv_is_fixed_and_policy_is_allowlisted(self):
        self.assertEqual(
            self.runner.policy_argv(UUID),
            ("/usr/bin/boltctl", "config", UUID, "device.policy"),
        )
        self.assertEqual(
            self.runner.set_policy_argv(UUID, "manual"),
            ("/usr/bin/boltctl", "config", UUID, "device.policy", "manual"),
        )
        for value in ("default", "auto; authorize", "", None):
            with self.assertRaises(ValueError):
                self.runner.set_policy_argv(UUID, value)

    def test_policy_read_accepts_only_bounded_exact_values(self):
        for output, expected in (
            (b"auto\n", "auto"),
            (b"manual\n", "manual"),
            (b"default\n", None),
            (b"auto extra\n", None),
            (b"x" * 65, None),
        ):
            with self.subTest(output=output), patch.object(
                subprocess, "run", return_value=Completed(stdout=output)
            ) as run:
                self.assertEqual(self.runner.policy(UUID), expected)
                self.assertFalse(run.call_args.kwargs["shell"])
                self.assertEqual(
                    run.call_args.kwargs["env"], self.runner.CLEAN_ENVIRONMENT
                )

    def test_policy_write_never_authorizes_or_enrolls(self):
        with patch.object(subprocess, "run", return_value=Completed()) as run:
            self.assertTrue(self.runner.set_policy(UUID, "manual"))
        argv = run.call_args.args[0]
        self.assertEqual(argv, self.runner.set_policy_argv(UUID, "manual"))
        self.assertNotIn("authorize", argv)
        self.assertNotIn("enroll", argv)


@unittest.skipUnless(
    sys.platform == "linux", "Linux descriptor-relative filesystem required"
)
class HoldStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.claims = WholeDockClaimStore(
            self.root, owner_uid=os.geteuid(), trusted_directory_fd=self.fd
        )
        self.store = DeviceAuthorizationHoldStore(
            self.root, owner_uid=os.geteuid(), trusted_directory_fd=self.fd
        )
        self.claims.claim("operation", "binding", "generation")
        for stage in (
            "release_intent", "gpu_removed", "prepared", "usb_remove_intent",
            "usb_removed", "tunnel_remove_intent",
        ):
            self.claims.record("operation", stage)

    def tearDown(self):
        os.close(self.fd)
        self.temp.cleanup()

    def test_hold_is_bound_to_exact_tunnel_intent_and_advances_once(self):
        hold = self.store.prepare(
            "operation", "binding", "generation", UUID, lambda: True
        )
        self.assertEqual(
            hold, DeviceAuthorizationHold("operation", "binding", "generation", UUID)
        )
        marked = self.store.mark_manual(hold, lambda: True)
        self.assertEqual(marked.state, "manual")
        self.assertEqual(self.store.load_hold(), marked)
        self.assertIsNone(self.store.prepare(
            "other", "binding", "generation", UUID, lambda: True
        ))

    def test_absence_clear_requires_exact_record_and_guard(self):
        hold = self.store.prepare(
            "operation", "binding", "generation", UUID, lambda: True
        )
        hold = self.store.mark_manual(hold, lambda: True)
        self.assertFalse(self.store.clear_after_absence(hold, lambda: False))
        self.assertEqual(self.store.load_hold(), hold)
        self.assertTrue(self.store.clear_after_absence(hold, lambda: True))
        self.assertIsNone(self.store.load_hold())
