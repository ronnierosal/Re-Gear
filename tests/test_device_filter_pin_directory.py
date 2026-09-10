import stat
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from backend.regear.delivery.device_filter_lifecycle import LaunchBinding
from backend.regear.delivery import device_filter_pin_directory as pins


class FilterPinDirectoryTests(unittest.TestCase):
    def test_pin_identity_changes_with_boot_and_launch(self):
        binding = LaunchBinding("a"*64, "trial", "gamescope-session.service",
            "b"*32, 1000, 50, 100, 29, 1234, "c"*64, 30.0)
        original = pins.pin_token(binding)
        self.assertEqual(len(original), 64)
        for field, value in (("boot_hash", "d"*64), ("operation", "other"),
                             ("unit", "steam-launcher.service"), ("invocation", "e"*32)):
            self.assertNotEqual(original, pins.pin_token(replace(binding, **{field:value})))

    def test_non_root_or_non_linux_cannot_open(self):
        with patch.object(pins.sys, "platform", "linux"), \
             patch.object(pins.os, "geteuid", return_value=1000, create=True), \
             patch.object(pins.os, "open") as opened:
            with self.assertRaises(ValueError):
                pins.FilterPinDirectory()
            opened.assert_not_called()

    def test_untrusted_mode_or_owner_rejected(self):
        for uid, mode, private in ((1000, 0o755, False), (0, 0o777, False), (0, 0o755, True)):
            with patch.object(pins.os, "fstat", return_value=SimpleNamespace(st_uid=uid, st_mode=stat.S_IFDIR|mode)):
                with self.assertRaises(ValueError):
                    pins._root_directory(5, private=private)

    def test_wrong_filesystem_stops_before_directory_creation(self):
        with patch.object(pins.sys, "platform", "linux"), \
             patch.object(pins.os, "geteuid", return_value=0, create=True), \
             patch.object(pins.os, "O_DIRECTORY", 0x10000, create=True), \
             patch.object(pins.os, "O_NOFOLLOW", 0x20000, create=True), \
             patch.object(pins.os, "open", side_effect=[10,11,12,13]), \
             patch.object(pins, "_root_directory"), \
             patch.object(pins, "_bpffs", side_effect=ValueError("wrong filesystem")), \
             patch.object(pins.os, "mkdir") as mkdir, \
             patch.object(pins.os, "close") as close:
            with self.assertRaises(ValueError):
                pins.FilterPinDirectory(create=True)
            mkdir.assert_not_called()
            self.assertEqual([c.args[0] for c in close.call_args_list], [10,11,12,13])
