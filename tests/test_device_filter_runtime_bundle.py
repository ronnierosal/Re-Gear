import hashlib
import io
import json
import unittest
import subprocess
import sys
import tempfile
from pathlib import Path
import zipfile
from collections.abc import Mapping

from backend.hdm.delivery.device_filter_runtime_bundle import build_runtime_bundle, MAX_SOURCE_BYTES


class RuntimeBundleTests(unittest.TestCase):
    def setUp(self):
        self.sources = {"hdm/delivery/" + name: b"# fixture\n" for name in (
            "device_filter_bootstrap.py", "gamescope_wrapper.py", "steam_trial_wrapper.py", "device_filter_wrapper.py")}
        self.sources["hdm/__init__.py"] = b""
        self.sources["hdm/delivery/__init__.py"] = b""

    def build(self, sources=None, **kwargs):
        return build_runtime_bundle(self.sources if sources is None else sources,
                                    session_sha256=kwargs.get("session_sha256", "a" * 64))

    def test_order_independent_and_content_addressed(self):
        value = self.build()
        self.assertEqual(value, self.build(dict(reversed(list(self.sources.items())))))
        self.assertEqual(value.digest, hashlib.sha256(value.archive).hexdigest())
        self.assertEqual(value.path, f"/var/lib/regear/filter-runtime/{value.digest}/runtime.pyz")
        changed = dict(self.sources)
        changed["hdm/__init__.py"] = b"# changed"
        self.assertNotEqual(value.digest, self.build(changed).digest)
        self.assertNotEqual(value.digest, self.build(session_sha256="b" * 64).digest)

    def test_archive_manifest_main_and_fixed_metadata(self):
        with zipfile.ZipFile(io.BytesIO(self.build().archive)) as archive:
            self.assertEqual(archive.namelist(), sorted([*self.sources, "__main__.py", "manifest.json"]))
            self.assertEqual(json.loads(archive.read("manifest.json")), {"schema": 1, "session_sha256": "a" * 64})
            self.assertEqual(archive.read("__main__.py"), b"from hdm.delivery.device_filter_bootstrap import main\nraise SystemExit(main())\n")
            for info in archive.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(info.external_attr >> 16, 0o100644)

    def test_launchers_only_reference_absolute_stable_runtime(self):
        value = self.build()
        self.assertEqual(value.gamescope_shim,
            f'#!/bin/sh\nexec /usr/bin/python3 -I {value.path} gamescope "$@"\n'.encode())
        self.assertEqual(value.steam_argv, ("/usr/bin/python3", "-I", value.path, "steam"))
        self.assertEqual(value.session_argv, ("/usr/bin/python3", "-I", value.path, "session"))
        self.assertNotIn(b"\r", value.gamescope_shim)
        self.assertNotIn(b"homebrew", value.gamescope_shim)
        self.assertNotIn(b"plugin", value.gamescope_shim)

    def test_invalid_paths_and_values_rejected(self):
        for name in ("/hdm/a.py", "hdm/../a.py", "hdm/./a.py", "hdm//a.py",
                     "hdm\\a.py", "hdm/a.py\0", "hdm/a.py/", "hdm/a.txt", "__main__.py",
                     "manifest.json", "hdm/a-b.py", 1):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.build(dict(self.sources, **{name: b""}) if type(name) is str else {**self.sources, name: b""})
        with self.assertRaises(ValueError):
            self.build({**self.sources, "hdm/a.py": "text"})
        with self.assertRaises(ValueError):
            self.build({**self.sources, "hdm/a.py": bytes(MAX_SOURCE_BYTES + 1)})

    def test_missing_required_and_missing_verified_hash(self):
        for name in tuple(self.sources):
            copy = dict(self.sources)
            del copy[name]
            with self.assertRaises(ValueError):
                self.build(copy)
        for value in (None, "", "A" * 64, "a" * 63, True):
            with self.assertRaises(ValueError):
                self.build(session_sha256=value)
        with self.assertRaises(TypeError):
            build_runtime_bundle(self.sources)

    def test_actual_source_archive_imports_without_plugin_path(self):
        root = Path(__file__).resolve().parents[1] / "backend" / "hdm"
        sources = {"hdm/" + path.relative_to(root).as_posix(): path.read_bytes()
                   for path in root.rglob("*.py")}
        bundle = self.build(sources)
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "runtime.pyz"
            archive.write_bytes(bundle.archive)
            code = """import sys
sys.path.insert(0, sys.argv[1])
import hdm.delivery.gamescope_wrapper
import hdm.delivery.steam_trial_wrapper
import hdm.delivery.device_filter_wrapper
for name, module in tuple(sys.modules.items()):
    if name == 'hdm' or name.startswith('hdm.'):
        assert module.__file__.startswith(sys.argv[1]), (name, module.__file__)
"""
            result = subprocess.run([sys.executable, "-I", "-c", code, str(archive)],
                cwd=directory, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            # Uninstalled/untrusted location must preserve the failure status.
            result = subprocess.run([sys.executable, "-I", str(archive), "steam"],
                cwd=directory, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 78, result.stderr)

    def test_custom_mapping_duplicate_items_rejected(self):
        class DuplicateMapping(Mapping):
            def __len__(self): return 2
            def __iter__(self): return iter(("hdm/a.py", "hdm/a.py"))
            def __getitem__(self, key): return b""
        with self.assertRaises(ValueError):
            self.build(DuplicateMapping())


if __name__ == "__main__":
    unittest.main()
