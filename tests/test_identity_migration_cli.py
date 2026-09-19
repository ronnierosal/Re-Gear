from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "migrate_regear_identity", ROOT / "scripts/migrate_regear_identity.py"
)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


class IdentityMigrationCliTests(unittest.TestCase):
    def test_gamescope_environment_requires_one_exact_current_identity(self):
        current = "/home/deck/.local/share/regear"
        self.assertEqual(
            tool._classify_gamescope_environment({"REGEAR_STATE_ROOT": current}),
            "current",
        )
        self.assertEqual(
            tool._classify_gamescope_environment(
                {"REGEAR_STATE_ROOT": current, "HDM_STATE_ROOT": "/former"}
            ),
            "ambiguous",
        )
        self.assertEqual(
            tool._classify_gamescope_environment({"HDM_STATE_ROOT": "/former"}),
            "former",
        )
        self.assertEqual(tool._classify_gamescope_environment({}), "missing")
        self.assertEqual(
            tool._classify_gamescope_environment({"REGEAR_STATE_ROOT": "/edited"}),
            "unexpected",
        )

    def test_apply_guard_refuses_loader_or_runtime_process(self):
        with (
            patch.object(tool, "_plugin_loader_active", return_value=True),
            patch.object(tool, "_active_processes") as processes,
            self.assertRaisesRegex(tool.IdentityMigrationError, "plugin_loader"),
        ):
            tool.require_offline()
        processes.assert_not_called()

        with (
            patch.object(tool, "_plugin_loader_active", return_value=False),
            patch.object(tool, "_active_processes", return_value=("gamescope",)),
            self.assertRaisesRegex(tool.IdentityMigrationError, "gamescope"),
        ):
            tool.require_offline()

    def test_guard_is_read_only_and_tool_has_no_service_or_hardware_mutation(self):
        source = (ROOT / "scripts/migrate_regear_identity.py").read_text(encoding="utf-8")
        self.assertIn('"is-active", "--quiet", "plugin_loader.service"', source)
        for forbidden in (
            '"stop"',
            '"start"',
            '"restart"',
            "shutdown",
            "suspend",
            "/sys/",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
