from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import build_plugin, check_plugin_package


class PackagedProbeTests(unittest.TestCase):
    def test_extracted_probe_import_and_help_need_only_packaged_files(self):
        # Exercise the real archive writer without a release reservation or
        # persistent artifact. Do not mock included_files: that is the contract.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "test.zip"
            with (
                patch.dict(sys.modules, {"release_coordination": __import__(
                    "scripts.release_coordination", fromlist=["reserve"])}),
                patch("scripts.release_coordination.reserve") as reserve,
                patch.object(build_plugin, "OUTPUT", output),
                patch.object(build_plugin, "source_revision", return_value="a" * 40),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(build_plugin.main(), 0)
                reserve.assert_called_once_with(build_plugin.PACKAGE_VERSION)
            with zipfile.ZipFile(output) as archive:
                script_names = {name for name in archive.namelist()
                                if name.startswith("Re-Gear/scripts/")}
                self.assertEqual(script_names, {
                    "Re-Gear/scripts/probe_safe_undock_readiness.py"})
                archive.extractall(root / "extracted")
            plugin = root / "extracted" / "Re-Gear"
            # -I excludes checkout/PYTHONPATH fallback. Both module locations
            # and constructor traps prove this stays in the extracted tree and
            # does not begin collection while importing or parsing --help.
            smoke = r'''
import pathlib, runpy, sys
from unittest.mock import patch
plugin = pathlib.Path(sys.argv[1]).resolve()
probe = plugin / "scripts" / "probe_safe_undock_readiness.py"
def reject_hardware(event, args):
    if event in {"subprocess.Popen", "os.system", "socket.connect"}:
        raise AssertionError(event)
    if event in {"open", "os.listdir", "os.scandir"} and args:
        path = str(args[0]).replace("\\", "/")
        if path in {"/proc", "/sys", "/dev"} or path.startswith(("/proc/", "/sys/", "/dev/")):
            raise AssertionError("hardware access: " + path)
sys.addaudithook(reject_hardware)
module = runpy.run_path(str(probe), run_name="packaged_probe")
for name, loaded in list(sys.modules.items()):
    if name == "hdm" or name.startswith("hdm."):
        assert pathlib.Path(loaded.__file__).resolve().is_relative_to(plugin)
with patch.object(module["SteamOsDiscovery"], "__init__", side_effect=AssertionError("discovery")), \
     patch.object(module["SteamOsPeripheralObservationAdapter"], "__init__", side_effect=AssertionError("peripherals")), \
     patch.object(module["SnapshotService"], "observe", side_effect=AssertionError("snapshot")):
    runpy.run_path(str(probe), run_name="packaged_probe")
    sys.argv = [str(probe), "--help"]
    try:
        runpy.run_path(str(probe), run_name="__main__")
    except SystemExit as result:
        assert result.code == 0
    else:
        raise AssertionError("help did not exit")
'''
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", smoke, str(plugin)],
                cwd=root, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("--exit-on", result.stdout)

    def test_package_checker_requires_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with patch.object(sys, "argv", ["check", directory]), contextlib.redirect_stdout(output):
                self.assertEqual(check_plugin_package.main(), 1)
            self.assertIn("missing scripts/probe_safe_undock_readiness.py", output.getvalue())


if __name__ == "__main__":
    unittest.main()
