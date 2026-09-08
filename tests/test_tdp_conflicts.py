import json
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.adapters.steamos.tdp_conflicts import KnownTdpControllerScan


class TdpConflictTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proc = self.root / "proc"
        self.plugins = self.root / "homebrew/plugins"
        self.proc.mkdir()
        self.plugins.mkdir(parents=True)
        self.scanner = KnownTdpControllerScan(proc_root=self.proc, plugins_root=self.plugins)

    def process(self, pid, comm="steam", argv=("/usr/bin/steam",)):
        root = self.proc / str(pid)
        root.mkdir()
        (root / "comm").write_text(comm + "\n", encoding="utf-8")
        (root / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
        return root

    def plugin(self, folder, name):
        root = self.plugins / folder
        root.mkdir()
        (root / "plugin.json").write_text(json.dumps({"name": name}), encoding="utf-8")
        return root

    def test_regular_process_and_plugin_are_not_known_conflicts(self):
        self.process(1)
        self.plugin("HandheldDockMode", "Handheld Dock Mode")
        result = self.scanner.scan()
        self.assertTrue(result.complete)
        self.assertEqual(result.conflicts, ())
        self.assertEqual(result.code, "tdp.no_known_conflict")
        with self.assertRaises(FrozenInstanceError):
            result.complete = False

    def test_known_process_executables_and_python_forms(self):
        cases = (
            ("hhd", ("/usr/bin/hhd",), "process.hhd"),
            ("asusd", ("/usr/bin/asusd",), "process.asusd"),
            ("powerstation", ("/usr/bin/powerstation",), "process.powerstation"),
            ("ryzenadj", ("/usr/bin/ryzenadj",), "process.ryzenadj"),
            ("python3", ("/usr/bin/python3", "-m", "hhd"), "process.hhd"),
            ("python3", ("/usr/bin/python3", "-u", "/opt/hhd.py"), "process.hhd"),
            ("python3.13", ("/usr/bin/python3.13", "-W", "ignore", "-m", "hhd.__main__"), "process.hhd"),
            ("python", ("python", "--", "/opt/hhd/__main__.py"), "process.hhd"),
        )
        for pid, (comm, argv, expected) in enumerate(cases, 1):
            with self.subTest(argv=argv):
                root = self.process(pid, comm, argv)
                result = self.scanner.scan()
                self.assertTrue(result.complete)
                self.assertEqual(result.conflicts, (expected,))
                (root / "comm").unlink()
                (root / "cmdline").unlink()
                root.rmdir()

    def test_process_arguments_do_not_become_executable_matches(self):
        self.process(1, "python", ("python", "other.py", "hhd"))
        self.process(2, "python", ("python", "-c", "print('hhd')"))
        self.process(3, "cat", ("cat", "/tmp/hhd"))
        self.assertEqual(self.scanner.scan().conflicts, ())

    def test_installed_plugins_match_folder_or_manifest_variants(self):
        self.plugin("Power_Control", "renamed")
        self.plugin("renamed", "Simple Decky TDP")
        self.plugin("simple-decky-tdp", "renamed")
        result = self.scanner.scan()
        self.assertTrue(result.complete)
        self.assertEqual(result.conflicts, ("plugin.powercontrol", "plugin.simpledeckytdp"))
        self.assertEqual(result.code, "tdp.conflict")

    def test_known_folder_retains_conflict_when_manifest_missing(self):
        (self.plugins / "PowerControl").mkdir()
        result = self.scanner.scan()
        self.assertFalse(result.complete)
        self.assertEqual(result.conflicts, ("plugin.powercontrol",))

    def test_missing_roots_are_unknown(self):
        for proc, plugins in ((self.root / "missing", self.plugins), (self.proc, self.root / "missing")):
            result = KnownTdpControllerScan(proc_root=proc, plugins_root=plugins).scan()
            self.assertFalse(result.complete)
            self.assertEqual(result.code, "tdp.conflict_scan_unavailable")

    def test_missing_process_field_is_unknown_while_process_exists(self):
        root = self.process(1)
        (root / "comm").unlink()
        self.assertFalse(self.scanner.scan().complete)

    def test_vanished_process_is_tolerated(self):
        root = self.process(1)
        original = Path.open
        def vanish(path, *args, **kwargs):
            if path == root / "comm":
                (root / "comm").unlink()
                (root / "cmdline").unlink()
                root.rmdir()
                raise FileNotFoundError()
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", vanish):
            result = self.scanner.scan()
        self.assertTrue(result.complete)

    def test_permission_failure_is_incomplete_and_redacted(self):
        self.process(1)
        with patch.object(Path, "open", side_effect=PermissionError("sensitive process path")):
            result = self.scanner.scan()
        self.assertFalse(result.complete)
        self.assertNotIn("sensitive", repr(result))
        self.assertNotIn(str(self.root), repr(result))

    def test_oversized_process_fields_fail_closed(self):
        root = self.process(1)
        for field, limit in (("comm", self.scanner.MAX_COMM_BYTES), ("cmdline", self.scanner.MAX_CMDLINE_BYTES)):
            with self.subTest(field=field):
                original = (root / field).read_bytes()
                (root / field).write_bytes(b"x" * (limit + 1))
                self.assertFalse(self.scanner.scan().complete)
                (root / field).write_bytes(original)

    def test_invalid_and_oversized_manifests_fail_closed(self):
        root = self.plugin("other", "Other")
        for raw in (b"{", b"[]", b'{"name": 1}', b"x" * (self.scanner.MAX_MANIFEST_BYTES + 1)):
            with self.subTest(size=len(raw)):
                (root / "plugin.json").write_bytes(raw)
                self.assertFalse(self.scanner.scan().complete)

    def test_bounded_scans_mark_incomplete(self):
        self.process(1)
        self.process(2)
        with patch.object(self.scanner, "MAX_PROC_ENTRIES", 1):
            self.assertFalse(self.scanner.scan().complete)
        self.plugin("one", "One")
        self.plugin("two", "Two")
        with patch.object(self.scanner, "MAX_PLUGIN_ENTRIES", 1):
            self.assertFalse(self.scanner.scan().complete)

    def test_scan_does_not_modify_files(self):
        self.process(1)
        self.plugin("other", "Other")
        before = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.scanner.scan()
        after = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
