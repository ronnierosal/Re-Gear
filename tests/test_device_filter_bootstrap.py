from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import PurePosixPath
import sys
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from backend.hdm.delivery import device_filter_bootstrap as bootstrap


def archive_bytes(manifest):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        archive.writestr("manifest.json", manifest)
    return result.getvalue()


_SYSTEM_FLAGS = sys.flags
_ROOT_READER = bootstrap._read_root_file


class FlagView:
    def __init__(self, isolated): self.isolated = isolated
    def __getattr__(self, name): return getattr(_SYSTEM_FLAGS, name)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.native = b"#!/bin/bash\nfixture"
        self.raw = archive_bytes(json.dumps(dict(schema=1, session_sha256=hashlib.sha256(self.native).hexdigest())))
        self.digest = hashlib.sha256(self.raw).hexdigest()
        self.path = bootstrap.ROOT + "/" + self.digest + "/runtime.pyz"
        self.stack.enter_context(patch.object(sys, "platform", "linux"))
        self.stack.enter_context(patch.object(sys, "flags", FlagView(1)))
        self.argv = self.stack.enter_context(patch.object(sys, "argv", [self.path, "session"]))
        self.reader = self.stack.enter_context(patch.object(bootstrap, "_read_root_file",
            side_effect=[self.raw, bootstrap.shim_bytes(self.path), self.native]))
        self.execute = self.stack.enter_context(patch.object(bootstrap.os, "execve"))
        self.stack.enter_context(patch.object(bootstrap, "Path", PurePosixPath))
        self.latch = self.stack.enter_context(patch(
            "backend.hdm.delivery.device_filter_wrapper.latch_filter_arm", return_value=None))

    def test_armed_session_withholds_before_native_script_and_cannot_exec(self):
        from backend.hdm.delivery.device_filter_session_withhold import SessionEntryWithheld
        arm = object()
        self.latch.return_value = arm
        prefix = "backend.hdm.delivery."
        for outcome in (SessionEntryWithheld("withheld"), RuntimeError("unexpected failure"), None):
            with self.subTest(outcome=outcome):
                self.reader.side_effect = [self.raw]
                with patch.dict(bootstrap.os.environ, {"HDM_STATE_ROOT": "/state", "INVOCATION_ID": "fixture"}), \
                     patch(prefix + "gamescope_wrapper._boot_identity", return_value=("boot", "hash")), \
                     patch(prefix + "gamescope_wrapper._load_config", return_value="config"), \
                     patch(prefix + "device_filter_session_withhold.withhold_session_entry", side_effect=outcome) as helper:
                    self.assertEqual(bootstrap.main(), 78)
                self.execute.assert_not_called()
                self.assertEqual(helper.call_args.args, (arm,))
                self.assertEqual(str(helper.call_args.kwargs["state_root"]), "/state")
                self.assertEqual(helper.call_args.kwargs["raw_boot_id"], "boot")
                self.assertEqual(helper.call_args.kwargs["candidate_config"], "config")

    def test_arm_read_error_or_malformed_record_never_executes_native_session(self):
        for error in (OSError("unreadable"), ValueError("malformed")):
            self.reader.side_effect = [self.raw]
            self.latch.side_effect = error
            self.assertEqual(bootstrap.main(), 78)
            self.execute.assert_not_called()

    def test_armed_context_failure_never_executes_or_requests_preparation(self):
        self.latch.return_value = object()
        prefix = "backend.hdm.delivery."
        for root, failure in (("relative", None), ("/state", OSError("boot unreadable"))):
            self.reader.side_effect = [self.raw]
            with patch.dict(bootstrap.os.environ, {"HDM_STATE_ROOT": root}), \
                 patch(prefix + "gamescope_wrapper._boot_identity", side_effect=failure), \
                 patch(prefix + "device_filter_session_withhold.withhold_session_entry") as helper:
                self.assertEqual(bootstrap.main(), 78)
            helper.assert_not_called()
            self.execute.assert_not_called()

    def test_armed_config_read_failure_never_requests_preparation(self):
        self.latch.return_value = object()
        self.reader.side_effect = [self.raw]
        prefix = "backend.hdm.delivery."
        with patch.dict(bootstrap.os.environ, {"HDM_STATE_ROOT": "/state"}), \
             patch(prefix + "gamescope_wrapper._boot_identity", return_value=("boot", "hash")), \
             patch(prefix + "gamescope_wrapper._load_config", side_effect=OSError("unreadable")), \
             patch(prefix + "device_filter_session_withhold.withhold_session_entry") as helper:
            self.assertEqual(bootstrap.main(), 78)
        helper.assert_not_called()
        self.execute.assert_not_called()

    def test_verified_session_uses_stable_shim_path_and_fixed_native_script(self):
        with patch.dict(bootstrap.os.environ, {"PATH": "/plugin/bin:/foreign"}):
            self.assertEqual(bootstrap.main(), 127)
        path, argv, environment = self.execute.call_args.args
        self.assertEqual(path, bootstrap.SESSION)
        self.assertEqual(argv, (bootstrap.SESSION,))
        self.assertTrue(environment["PATH"].startswith(self.path.rsplit("/", 1)[0] + "/bin:"))
        self.assertNotIn("/plugin", environment["PATH"])
        self.latch.assert_called_once_with("gamescope-session.service")
        self.assertIs(self.reader.call_args_list[1].kwargs["executable"], True)

    def test_archive_shim_or_os_script_change_stops_before_exec(self):
        for reads in ([b"bad"], [self.raw, b"changed shim"],
                      [self.raw, bootstrap.shim_bytes(self.path), b"changed OS"]):
            self.reader.side_effect = reads
            self.assertEqual(bootstrap.main(), 78)
            self.execute.assert_not_called()

    def test_no_plugin_import_fallback_for_steam_role(self):
        sys.argv = [self.path, "steam"]
        self.reader.side_effect = [self.raw]
        with patch("backend.hdm.delivery.steam_trial_wrapper.main", side_effect=ImportError("missing")):
            self.assertEqual(bootstrap.main(), 78)
        self.execute.assert_not_called()

    def test_invalid_role_or_unisolated_python_rejected(self):
        sys.argv = [self.path, "steam", "foreign"]
        self.reader.side_effect = [self.raw]
        self.assertEqual(bootstrap.main(), 78)
        with patch.object(sys, "flags", FlagView(0)):
            self.assertEqual(bootstrap.main(), 78)
        self.execute.assert_not_called()

    def test_strict_runtime_path_and_manifest(self):
        self.assertEqual(bootstrap.runtime_identity(self.path), self.digest)
        for path in ("/plugin/runtime.pyz", self.path.replace("runtime.pyz", "../runtime.pyz")):
            with self.assertRaises(ValueError): bootstrap.runtime_identity(path)
        for manifest in ('{"schema":true,"session_sha256":"' + "a" * 64 + '"}',
                         '{"schema":1,"schema":1,"session_sha256":"' + "a" * 64 + '"}', '[]'):
            raw = archive_bytes(manifest)
            with self.assertRaises(ValueError): bootstrap.manifest_from_bytes(raw, hashlib.sha256(raw).hexdigest())

    def test_nonexecutable_or_unsafe_shim_is_rejected_before_read(self):
        prefix = "backend.hdm.delivery.device_filter_bootstrap.os."
        directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
        for mode, uid, links in ((0o444, 0, 1), (0o777, 0, 1), (0o755, 1000, 1), (0o755, 0, 2)):
            file = SimpleNamespace(st_mode=stat.S_IFREG | mode, st_uid=uid, st_nlink=links, st_size=20)
            with patch(prefix+"O_DIRECTORY", create=True, new=0), patch(prefix+"O_NOFOLLOW", create=True, new=0), \
                 patch(prefix+"O_NONBLOCK", create=True, new=0), patch(prefix+"open", side_effect=[10, 11, 12]), \
                 patch(prefix+"fstat", side_effect=[directory, directory, file]), patch(prefix+"read") as read, \
                 patch(prefix+"close"):
                # Bypass the main fixture's read mock to exercise its original helper.
                with self.assertRaises(ValueError):
                    _ROOT_READER("/stable/file", 100, executable=True)
                read.assert_not_called()
