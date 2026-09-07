import builtins
from pathlib import Path
import os
import runpy
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class SteamBootstrapTests(unittest.TestCase):
    def run_failure(self, opens, *, mode=stat.S_IFDIR | 0o755):
        original = builtins.__import__
        def importing(name, *args, **kwargs):
            if name == "hdm.delivery.steam_trial_wrapper":
                raise ImportError("simulated missing backend")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=importing), patch.object(sys, "platform", "linux"), \
             patch.object(sys, "path", list(sys.path)), patch.object(os, "O_DIRECTORY", 0, create=True), \
             patch.object(os, "O_NOFOLLOW", 0, create=True), patch.object(os, "O_NONBLOCK", 0, create=True), \
             patch.object(os, "open", side_effect=opens), patch.object(os, "close"), \
             patch.object(os, "fstat", return_value=SimpleNamespace(st_mode=mode, st_uid=0)), \
             patch.object(os, "execve") as execute:
            with self.assertRaises(SystemExit) as result:
                runpy.run_path(str(Path(__file__).resolve().parents[1] / "bin/steam-launcher"))
            return result.exception.code, execute.call_count

    def test_import_failure_only_falls_back_with_authenticated_absence(self):
        self.assertEqual(self.run_failure([10, FileNotFoundError()]), (127, 1))

    def test_present_arm_never_falls_back_after_import_failure(self):
        self.assertEqual(self.run_failure([10, 11, 12, 13, 14, 15]), (78, 0))

    def test_unreadable_or_unsafe_arm_path_never_falls_back(self):
        self.assertEqual(self.run_failure([10, PermissionError()]), (78, 0))
        self.assertEqual(self.run_failure([10], mode=stat.S_IFDIR | 0o777), (78, 0))
