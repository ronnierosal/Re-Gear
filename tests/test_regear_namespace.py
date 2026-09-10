from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RegearNamespaceTests(unittest.TestCase):
    def test_public_package_and_cli_import_without_repository_helpers(self):
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        entrypoint = metadata["project"]["scripts"]["regear-diagnose"]
        self.assertEqual(entrypoint, "regear.cli:main")
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary)
            shutil.copytree(
                ROOT / "backend" / "regear", package_root / "regear",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            result = subprocess.run(
                [sys.executable, "-I", "-c",
                 "import importlib, sys; sys.path.insert(0, sys.argv[1]); "
                 "import regear; import regear.api; "
                 "module, name = sys.argv[2].split(':'); "
                 "assert callable(getattr(importlib.import_module(module), name))",
                 temporary, entrypoint],
                cwd=temporary, capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
