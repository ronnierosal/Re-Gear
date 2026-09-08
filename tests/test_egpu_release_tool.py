from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.egpu_release import (  # noqa: E402
    egpu_functions,
    holder_units,
    main,
    restart_commands,
)


TOOL = ROOT / "backend/hdm/egpu_release.py"


class FunctionDerivationTests(unittest.TestCase):
    """Audio is derived from the GPU address so the two cannot disagree."""

    def test_audio_is_the_next_function(self) -> None:
        self.assertEqual(
            egpu_functions("0000:08:00.0"), ("0000:08:00.0", "0000:08:00.1")
        )

    def test_a_non_zero_gpu_function_still_derives(self) -> None:
        self.assertEqual(
            egpu_functions("0000:64:00.5"), ("0000:64:00.5", "0000:64:00.6")
        )


class RestartCommandTests(unittest.TestCase):
    def test_commands_are_produced_in_plan_order(self) -> None:
        commands = restart_commands(
            ("wireplumber.service", "gamescope-session.target"), 1000
        )
        self.assertEqual(len(commands), 2)
        self.assertIn("wireplumber.service", commands[0])
        self.assertIn("gamescope-session.target", commands[1])

    def test_commands_target_the_given_session_user(self) -> None:
        self.assertIn("/run/user/1042", restart_commands(("a.service",), 1042)[0])

    def test_no_units_produces_no_commands(self) -> None:
        self.assertEqual(restart_commands((), 1000), ())


class HolderScanTests(unittest.TestCase):
    def test_a_proc_tree_without_holders_reports_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "1").mkdir()
            (root / "1" / "fd").mkdir()
            (root / "1" / "cgroup").write_text("0::/init.scope", encoding="utf-8")
            self.assertEqual(
                holder_units(("/dev/dri/renderD129",), proc_root=root), ()
            )

    def test_non_numeric_entries_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "self").mkdir()
            self.assertEqual(holder_units(("/dev/dri/card1",), proc_root=root), ())


class BoundaryTests(unittest.TestCase):
    """The tool must not open a second process-spawning path."""

    def test_the_tool_never_spawns_a_process(self) -> None:
        source = TOOL.read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            self.assertFalse(
                stripped.startswith(("import subprocess", "from subprocess")),
                "the tool must not import subprocess",
            )
        self.assertNotIn("os.system", source)
        self.assertNotIn("Popen", source)

    def test_the_tool_never_removes_a_device(self) -> None:
        """Clearing holders is not removal authority."""
        source = TOOL.read_text(encoding="utf-8")
        self.assertNotIn("device_removal", source)
        self.assertNotIn("/remove", source)
        self.assertNotIn("rescan", source)

    def test_the_tool_states_that_recovery_is_not_durable(self) -> None:
        source = TOOL.read_text(encoding="utf-8")
        self.assertIn("not durable recovery", source)


class DryRunTests(unittest.TestCase):
    """Without --arm nothing is loaded or attached, on any hardware."""

    def _run(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(argv)
        return code, buffer.getvalue()

    def test_absent_hardware_reports_incomplete_discovery(self) -> None:
        code, output = self._run(["--gpu", "0000:ff:00.0"])
        self.assertEqual(code, 1)
        self.assertIn("discovery incomplete", output)

    def test_arming_without_root_is_refused(self) -> None:
        import os
        from unittest.mock import patch

        # geteuid is POSIX-only; create it so this runs on any platform.
        with patch.object(os, "geteuid", return_value=1000, create=True):
            code, output = self._run(["--arm"])
        self.assertEqual(code, 2)
        self.assertIn("needs root", output)

    def test_default_is_a_plan_not_an_action(self) -> None:
        source = TOOL.read_text(encoding="utf-8")
        self.assertIn('"--arm"', source)
        self.assertIn("action=\"store_true\"", source)


if __name__ == "__main__":
    unittest.main()
