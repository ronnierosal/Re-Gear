from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import build_plugin, check_plugin_package


LAUNCHER = b'#!/usr/bin/python3\n"""Launcher fixture."""\nprint("ready")\n'


class LauncherPackagingTests(unittest.TestCase):
    def test_bin_files_are_explicitly_pinned_to_lf(self):
        attributes = (build_plugin.ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("bin/** text eol=lf", attributes.splitlines())

    def test_repository_launcher_is_linux_executable_text(self):
        build_plugin.validate_launcher_bytes(
            (build_plugin.ROOT / "bin" / "gamescope").read_bytes()
        )

    def test_raw_launcher_validation_rejects_crlf_bom_and_bad_shebang(self):
        for content in (
            LAUNCHER.replace(b"\n", b"\r\n"),
            LAUNCHER + b"# bare carriage return\r",
            b"\xef\xbb\xbf" + LAUNCHER,
            LAUNCHER.replace(b"/usr/bin/python3", b"/usr/bin/unknown"),
            b"#!/usr/bin/python3",
        ):
            with self.subTest(content=content):
                with self.assertRaisesRegex(ValueError, "LF-only"):
                    build_plugin.validate_launcher_bytes(content)

    def test_non_launcher_bytes_are_not_transformed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "other.py"
            content = b"# keep original bytes\r\n"
            path.write_bytes(content)
            self.assertEqual(build_plugin.archive_bytes(path), content)

    def test_windows_checkout_build_has_canonical_launcher_and_provenance(self):
        # Exercise the real ZIP writer/post-write verification without touching
        # repository inputs or depending on an optional pre-existing out/ ZIP.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrapper = root / "bin" / "gamescope"
            wrapper.parent.mkdir()
            manifest = root / "plugin.json"
            manifest.write_bytes(b'{"flags":["root"]}')
            output = root / "plugin.zip"
            revision = "a" * 40
            archives = []
            for source in (LAUNCHER, LAUNCHER.replace(b"\n", b"\r\n")):
                wrapper.write_bytes(source)
                output = root / f"plugin-{len(archives)}.zip"
                with (
                    patch("release_coordination.reserve"),
                    patch.object(build_plugin, "ROOT", root),
                    patch.object(build_plugin, "OUTPUT", output),
                    patch.object(build_plugin, "included_files", return_value=(manifest, wrapper)),
                    patch.object(build_plugin, "source_revision", return_value=revision),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(build_plugin.main(), 0)
                self.assertEqual(wrapper.read_bytes(), source, "packaging must not edit checkout")
                archives.append(output.read_bytes())
                with zipfile.ZipFile(output) as archive:
                    name = f"{build_plugin.PLUGIN_DIRECTORY}/bin/gamescope"
                    self.assertEqual(archive.read(name), LAUNCHER)
                    self.assertEqual(archive.getinfo(name).external_attr >> 16, 0o100755)
                    info = json.loads(archive.read(
                        f"{build_plugin.PLUGIN_DIRECTORY}/{build_plugin.BUILD_INFO_FILENAME}"
                    ))
                    self.assertEqual(info["revision"], revision)
                    self.assertEqual(info["version"], build_plugin.PACKAGE_VERSION)
            self.assertEqual(archives[0], archives[1], "LF and CRLF checkouts must build identically")

    def test_packaging_refuses_bare_cr_in_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrapper = root / "bin" / "gamescope"
            wrapper.parent.mkdir()
            wrapper.write_bytes(LAUNCHER + b"# malformed\r")
            with patch.object(build_plugin, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "LF-only"):
                    build_plugin.archive_bytes(wrapper)

    def test_package_checker_checks_raw_launcher_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrapper = root / "bin" / "gamescope"
            wrapper.parent.mkdir()
            for content, expected in (
                (LAUNCHER, 0),
                (LAUNCHER.replace(b"\n", b"\r\n"), 1),
                (LAUNCHER + b"# malformed\r", 1),
                (b"\xef\xbb\xbf" + LAUNCHER, 1),
            ):
                with self.subTest(content=content):
                    wrapper.write_bytes(content)
                    output = io.StringIO()
                    with (
                        patch.object(check_plugin_package, "REQUIRED_FILES", ("bin/gamescope",)),
                        patch("sys.argv", ["check_plugin_package.py", str(root)]),
                        contextlib.redirect_stdout(output),
                    ):
                        self.assertEqual(check_plugin_package.main(), expected)
                    if expected:
                        self.assertIn("LF-only", output.getvalue())


if __name__ == "__main__":
    unittest.main()
