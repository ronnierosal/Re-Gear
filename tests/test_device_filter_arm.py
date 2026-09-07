from dataclasses import replace
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend.hdm.delivery.device_filter_arm import FilterArm, FilterArmStore, encode_arm, decode_arm


def arm():
    return FilterArm(1, "op", "gamescope-session.service", 1000,
        "a" * 64, "b" * 64, "c" * 64, "d" * 32, 100)


class ArmTests(unittest.TestCase):
    def test_current_arm_requires_new_invocation_and_all_bindings(self):
        record = arm()
        args = dict(unit=record.unit, uid=1000, boot_hash=record.boot_hash,
            topology_hash=record.topology_hash, config_hash=record.config_hash,
            invocation="e" * 32, now=10)
        record.require_current(**args)
        for key, value in (("invocation", "d" * 32), ("now", 100), ("uid", True),
                           ("boot_hash", "f" * 64), ("config_hash", "f" * 64),
                           ("topology_hash", "f" * 64), ("unit", "steam-launcher.service")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                record.require_current(**dict(args, **{key: value}))

    def test_strict_roundtrip_and_duplicate_invalid_records(self):
        raw = encode_arm(arm())
        self.assertEqual(decode_arm(raw), arm())
        for invalid in (raw.replace(b'"schema":1', b'"schema":true'),
                        raw.replace(b'"schema":1', b'"schema":1,"schema":1'),
                        raw.replace(b'"deadline":100', b'"deadline":NaN'),
                        raw[:-1] + b',"extra":1}', b'[]', b'\xff', b'x' * 4097):
            with self.assertRaises(ValueError): decode_arm(invalid)

    def test_no_fixture_permission_relaxation_without_held_directory(self):
        with self.assertRaises(ValueError): FilterArmStore(owner_uid=1000)
        with self.assertRaises(ValueError): FilterArmStore(trusted_directory_fd=7)


@unittest.skipUnless(sys.platform == "linux", "Linux arm filesystem semantics")
class ArmFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.store = FilterArmStore(owner_uid=os.geteuid(), trusted_directory_fd=self.fd)
        self.record = arm()
        self.target = self.root / (self.record.unit + ".json")

    def test_authenticated_absence_and_exclusive_publication(self):
        self.assertIsNone(self.store.read(self.record.unit))
        self.store.arm(self.record)
        self.assertEqual(self.store.read(self.record.unit), self.record)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o644)
        with self.assertRaises(FileExistsError): self.store.arm(replace(self.record, operation="new"))
        self.assertEqual(self.store.read(self.record.unit), self.record)

    def test_failed_write_does_not_publish_partial_arm(self):
        with patch("backend.hdm.delivery.device_filter_arm.os.write", side_effect=OSError("full")):
            with self.assertRaises(OSError): self.store.arm(self.record)
        self.assertIsNone(self.store.read(self.record.unit))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_malformed_symlink_fifo_and_hardlink_do_not_mean_unarmed(self):
        other = self.root / "other"
        other.write_bytes(encode_arm(self.record))
        for create in (lambda: self.target.write_bytes(b'bad'), lambda: self.target.symlink_to(other),
                       lambda: os.mkfifo(self.target), lambda: os.link(other, self.target)):
            create()
            try:
                with self.assertRaises((OSError, ValueError)): self.store.read(self.record.unit)
            finally:
                self.target.unlink()

    def test_unsafe_directory_and_wrong_record_unit_block(self):
        self.root.chmod(0o777)
        try:
            with self.assertRaises(ValueError): self.store.read(self.record.unit)
        finally: self.root.chmod(0o700)
        self.target.write_bytes(encode_arm(replace(self.record, unit="steam-launcher.service")))
        with self.assertRaises(ValueError): self.store.read(self.record.unit)
