from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from test_emulator_metadata_inventory import SECRET, fixture_bytes, fixture_rows  # noqa: E402
from regear.adapters import emulator_metadata_capture as capture  # noqa: E402
from regear.domain.emulator_metadata_inventory import (  # noqa: E402
    MAX_FILE_BYTES, MetadataError, Origin, Reason, Role,
)


class FixtureTests(unittest.TestCase):
    def test_fixture_has_no_io_and_cannot_relabel_origin(self):
        with patch("builtins.open", side_effect=AssertionError("unexpected open")), \
             patch.object(capture.os, "open", side_effect=AssertionError("unexpected descriptor")), \
             patch.object(capture.os, "lstat", side_effect=AssertionError("unexpected stat")):
            result = capture.inventory_from_fixture(fixture_bytes())
        self.assertIsNone(result.failure)
        self.assertIs(result.inventory.origin, Origin.FIXTURE)
        self.assertTrue(all(item.origin is Origin.FIXTURE for item in result.inventory.sources))
        self.assertEqual(result.inventory.game.physical_directory, "ULUS12345DATA00")
        self.assertEqual(result.inventory.launch.carrier_app_id, "1118310")
        self.assertFalse(hasattr(result.inventory, "manifest"))
        self.assertFalse(hasattr(result.inventory, "plan"))

    def test_fixture_rejects_origin_override_unknown_schema_and_type_coercion(self):
        for value in ({"schema": 1, "records": fixture_rows(), "origin": "local_metadata"},
                      {"schema": True, "records": fixture_rows()},
                      {"schema": 2, "records": fixture_rows()},
                      {"schema": 1, "records": "private"}):
            result = capture.inventory_from_fixture(json.dumps(value).encode())
            self.assertIsNotNone(result.failure)

    def test_fixture_does_not_execute_commands_or_write_or_connect(self):
        with patch("subprocess.run", side_effect=AssertionError("subprocess")), \
             patch("socket.socket", side_effect=AssertionError("network")), \
             patch.object(Path, "write_bytes", side_effect=AssertionError("write")), \
             patch.object(Path, "write_text", side_effect=AssertionError("write")), \
             patch.object(capture.os, "mkdir", side_effect=AssertionError("mkdir")), \
             patch.object(capture.os, "unlink", side_effect=AssertionError("unlink")):
            result = capture.inventory_from_fixture(fixture_bytes())
        self.assertIsNone(result.failure)

    def test_fixture_rejects_duplicate_keys_nonfinite_bad_encoding_and_deep_json(self):
        for value in (b'{"schema":1,"schema":1,"records":[]}', b'{"schema":NaN,"records":[]}',
                      b'\xff', b'{"schema":1,"records":' + b'[' * 2000 + b']' * 2000 + b'}',
                      b'\x00'):
            self.assertIsNotNone(capture.inventory_from_fixture(value).failure)

    def test_fixture_rejects_bounds_and_duplicate_roles(self):
        self.assertIs(capture.inventory_from_fixture(b" " * (MAX_FILE_BYTES + 1)).failure, Reason.LIMIT_EXCEEDED)
        self.assertIsNotNone(capture.inventory_from_fixture(fixture_bytes([])).failure)
        self.assertIsNotNone(capture.inventory_from_fixture(fixture_bytes(fixture_rows() * 5)).failure)
        self.assertIs(capture.inventory_from_fixture(fixture_bytes([fixture_rows()[0]] * 2)).failure,
                      Reason.AMBIGUOUS_METADATA)

    def test_fixture_rejects_identity_lies_and_preserves_unknown_ps2_membership(self):
        rows = fixture_rows()
        for key, value in (("unit_id", "Renamed-ROM"), ("confirmed", 1), ("game_ids", "ULUS12345")):
            changed = json.loads(json.dumps(rows))
            changed[3]["payload"][key] = value
            self.assertIsNotNone(capture.inventory_from_fixture(fixture_bytes(changed)).failure)
        ps2 = [{"role": "identity", "payload": {"system": "ps2", "unit_kind": "ps2_whole_card",
                 "unit_id": "shared-card", "selected_slots": ["slot1", "slot2"]}}]
        result = capture.inventory_from_fixture(fixture_bytes(ps2))
        self.assertEqual(result.inventory.game.game_ids, ())
        self.assertIn(Reason.PS2_MEMBERSHIP_UNKNOWN, result.inventory.reasons)

    def test_cloud_rule_source_and_nested_overrides_are_retained_private(self):
        rows = [{"role": "cloud_rules", "payload": {"app_id": "1118310", "source_uri": "https://publisher.example/" + SECRET,
                 "source_category": "steam_cache", "freshness": "stale", "platform": "linux",
                 "root": SECRET, "subdirectory": "SAVEDATA", "pattern": "*", "recursive": True,
                 "root_overrides": [["AppInstall", "linux", SECRET, ".", False]],
                 "byte_quota": 100000, "file_quota": 512, "shared_app_id": "0"}}]
        result = capture.inventory_from_fixture(fixture_bytes(rows))
        self.assertIsNone(result.failure)
        self.assertIsInstance(result.inventory.rules.root_overrides, tuple)
        self.assertIn(Reason.CLOUD_RULES_UNKNOWN, result.inventory.reasons)
        self.assertNotIn(SECRET, json.dumps(result.public_summary()))

    def test_quoted_appmanifest_parses_only_installation_facts(self):
        payload = capture._manifest(b'"AppState" { "appid" "1118310" "buildid" "555" "installdir" "RetroArch" '
                                    b'"InstalledDepots" { "123" { "manifest" "123456" } } }\n')
        self.assertEqual(payload, {"app_id": "1118310", "build_id": "555", "install_directory": "RetroArch"})
        for value in (b'"AppState" { "appid" "999" }', b'"AppState" { "appid" "1118310" } }',
                      b'"AppState" { "appid" "1118310" "appid" "1118310" }',
                      b'"AppState" { "appid" "1118310"', b'"AppState" "not-an-object"'):
            with self.assertRaises(MetadataError):
                capture._manifest(value)

    def test_native_ini_and_cfg_declarations_do_not_discover_or_resolve_paths(self):
        with patch.object(capture.os, "lstat", side_effect=AssertionError("no resolution")):
            psp = capture._config(("[General]\nMemStickDirectory=/home/" + SECRET + "\nOther=ignored\n").encode(), "ppsspp.ini")
            ps2 = capture._config(b'[Folders]\nMemoryCards=/private/cards\n[MemoryCards]\nSlot1_Filename=shared.ps2\nSlot2_Enable=true\n', "PCSX2.ini")
            ra = capture._config(b'savefile_directory = "/private/saves"\nsavestate_directory = "/private/states"\n', "retroarch.cfg")
        self.assertIn(("general.memstickdirectory", "/home/" + SECRET), psp)
        self.assertIn(("memorycards.slot1_filename", "shared.ps2"), ps2)
        self.assertIn(("savestate_directory", "/private/states"), ra)
        for data, name in ((b"invalid private contents", "ppsspp.ini"),
                           (b'savefile_directory = "a"\nsavefile_directory = "b"', "retroarch.cfg")):
            with self.assertRaises(MetadataError):
                capture._config(data, name)


class ExplicitCaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.roots = (str(self.root),)
        self.metadata = self.root / "emulator-metadata.json"
        self.metadata.write_bytes(json.dumps(fixture_rows()[1]["payload"]).encode())
        self.item = capture.MetadataInput(Role.EMULATOR, str(self.metadata))

    def test_unsupported_platform_performs_no_file_or_save_root_reads(self):
        with patch.object(capture, "safe_open_supported", return_value=False), \
             patch.object(capture.os, "open", side_effect=AssertionError("must defer")), \
             patch.object(capture.os, "lstat", side_effect=AssertionError("must defer")):
            result = capture.capture_metadata(self.roots, (self.item,), (str(self.root / "saves"),))
        self.assertIs(result.failure, Reason.UNSUPPORTED_SAFE_OPEN)

    def test_regular_metadata_capture_has_local_provenance_and_unknown_cloud(self):
        result = capture.capture_metadata(self.roots, (self.item,))
        if not capture.safe_open_supported():
            self.assertIs(result.failure, Reason.UNSUPPORTED_SAFE_OPEN)
            return
        self.assertIsNone(result.failure)
        self.assertIs(result.inventory.origin, Origin.LOCAL_METADATA)
        self.assertEqual(result.inventory.emulator.version, "1.19.3")
        self.assertEqual(result.inventory.sources[0].private_path, str(self.metadata))
        self.assertEqual(result.public_summary()["cloud_coverage"], "unknown")

    def test_descriptor_admission_and_post_read_changes_defer_in_memory(self):
        # Exercise POSIX descriptor decisions even on Windows without touching a descriptor.
        def info(*, inode=1000, size=2, mode=stat.S_IFREG | 0o600):
            return SimpleNamespace(st_dev=1, st_ino=inode, st_mode=mode, st_nlink=1,
                                   st_size=size, st_mtime_ns=1, st_ctime_ns=1)
        for mutation in ("admission", "post_read", "named_file", "ancestor"):
            descriptor_calls = 0
            name_calls = {}

            def fake_stat(name, **_kwargs):
                name_calls[name] = name_calls.get(name, 0) + 1
                if name == self.metadata.name:
                    return info(inode=1001 if mutation == "named_file" and name_calls[name] > 1 else 1000)
                return info(inode=3 if mutation == "ancestor" and name_calls[name] > 1 else 2,
                            mode=stat.S_IFDIR | 0o700)

            def fake_fstat(descriptor):
                nonlocal descriptor_calls
                if descriptor != 999:
                    return info(inode=2, mode=stat.S_IFDIR | 0o700)
                descriptor_calls += 1
                return info(size=3 if mutation == "post_read" and descriptor_calls > 1 else 2,
                            inode=1001 if mutation == "admission" else 1000)

            with self.subTest(mutation=mutation), \
                 patch.object(capture, "safe_open_supported", return_value=True), \
                 patch.object(capture.os, "O_NOFOLLOW", 0x20000, create=True), \
                 patch.object(capture.os, "O_DIRECTORY", 0x10000, create=True), \
                 patch.object(capture.os, "O_NONBLOCK", 0x800, create=True), \
                 patch.object(capture.os, "open", side_effect=lambda name, *_args, **_kwargs: 999 if name == self.metadata.name else 100) as opens, \
                 patch.object(capture.os, "stat", side_effect=fake_stat), \
                 patch.object(capture.os, "fstat", side_effect=fake_fstat), \
                 patch.object(capture.os, "read", side_effect=[b"{}", b""]) as reads, \
                 patch.object(capture.os, "close"):
                with self.assertRaises(MetadataError) as caught:
                    capture._read_regular(self.metadata, set())
                self.assertIs(caught.exception.reason, Reason.INPUT_CHANGED)
                leaf = [call for call in opens.call_args_list if call.args[0] == self.metadata.name][0]
                self.assertTrue(leaf.args[1] & 0x20000)
                if mutation == "admission":
                    reads.assert_not_called()

    def test_relative_escape_prefix_sibling_and_overlapping_roots_reject_before_reads(self):
        for roots, path in ((self.roots, str(self.root / ".." / "outside" / self.metadata.name)),
                            (self.roots, str(self.root) + "-sibling/" + self.metadata.name),
                            (("relative-root",), str(self.metadata)),
                            ((str(self.root), str(self.root / "child")), str(self.metadata)),
                            ((str(self.root),) * 2, str(self.metadata))):
            with patch.object(capture, "_read_regular", side_effect=AssertionError("must reject before read")):
                with self.assertRaises(MetadataError):
                    capture.read_metadata_file(capture.MetadataInput(Role.EMULATOR, path), roots)

    def test_binary_or_arbitrary_filename_never_opens(self):
        for name in ("appinfo.vdf", "shortcuts.vdf", "save.ps2", "SAVE.DAT", "private.json"):
            with patch.object(capture, "_read_regular", side_effect=AssertionError("not allowlisted")):
                with self.assertRaises(MetadataError) as caught:
                    capture.read_metadata_file(capture.MetadataInput(Role.EMULATOR, str(self.root / name)), self.roots)
            self.assertIs(caught.exception.reason, Reason.UNSUPPORTED_FILE)
            self.assertNotIn(name, str(caught.exception))

    def test_duplicate_roles_aliases_and_limits_defer_without_read(self):
        cases = ((self.roots, (self.item, self.item)),
                 (self.roots * 9, (self.item,)), (self.roots, (self.item,) * 17))
        for roots, inputs in cases:
            with patch.object(capture, "read_metadata_file", side_effect=AssertionError("pre-admission")):
                result = capture.capture_metadata(roots, inputs)
            self.assertIsNotNone(result.failure)

    def test_metadata_within_selected_save_root_is_not_opened(self):
        with patch.object(capture, "safe_open_supported", return_value=True), \
             patch.object(capture, "read_metadata_file", side_effect=AssertionError("save overlap")):
            result = capture.capture_metadata(self.roots, (self.item,), (str(self.metadata),))
        self.assertIs(result.failure, Reason.UNSAFE_PATH)

    def test_metadata_within_save_root_alias_is_not_opened(self):
        if not capture.safe_open_supported():
            self.assertIs(capture.capture_metadata(self.roots, (self.item,)).failure, Reason.UNSUPPORTED_SAFE_OPEN)
            return
        target = self.root / "synthetic-save-target"
        target.mkdir()
        link = self.root / "synthetic-save-link"
        link.symlink_to(target.name, target_is_directory=True)
        item = capture.MetadataInput(Role.EMULATOR, str(target / self.metadata.name))
        with patch.object(capture, "read_metadata_file", side_effect=AssertionError("save alias payload")):
            result = capture.capture_metadata(self.roots, (item,), (str(link),))
        self.assertIs(result.failure, Reason.UNSAFE_PATH)

    def test_unsafe_save_root_defers_before_any_metadata_open(self):
        with patch.object(capture, "safe_open_supported", return_value=True), \
             patch.object(capture, "_save_root", return_value=capture.SaveRootEvidence(str(self.root / "save"), reason=Reason.UNSAFE_LINK)), \
             patch.object(capture, "read_metadata_file", side_effect=AssertionError("unsafe save path")):
            result = capture.capture_metadata(self.roots, (self.item,), (str(self.root / "save"),))
        self.assertIs(result.failure, Reason.UNSAFE_LINK)

    def test_missing_file_error_has_no_private_value_or_exception_context(self):
        if not capture.safe_open_supported():
            self.assertIs(capture.capture_metadata(self.roots, (self.item,)).failure, Reason.UNSUPPORTED_SAFE_OPEN)
            return
        self.metadata.unlink()
        with self.assertRaises(MetadataError) as caught:
            capture.read_metadata_file(self.item, self.roots)
        self.assertIs(caught.exception.reason, Reason.READ_UNAVAILABLE)
        self.assertIsNone(caught.exception.__context__)
        self.assertNotIn(str(self.metadata), repr(caught.exception))

    def test_symlinked_metadata_and_parent_are_not_read(self):
        if not capture.safe_open_supported():
            self.assertIs(capture.capture_metadata(self.roots, (self.item,)).failure, Reason.UNSUPPORTED_SAFE_OPEN)
            return
        actual = self.root / "actual"
        actual.mkdir()
        target = actual / self.metadata.name
        self.metadata.rename(target)
        self.metadata.symlink_to(target)
        with patch.object(capture.os, "read", side_effect=AssertionError("linked payload")):
            result = capture.capture_metadata(self.roots, (self.item,))
        self.assertIs(result.failure, Reason.UNSAFE_LINK)
        self.metadata.unlink()
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(actual, target_is_directory=True)
        with patch.object(capture.os, "read", side_effect=AssertionError("linked ancestor")):
            result = capture.capture_metadata(self.roots, (capture.MetadataInput(Role.EMULATOR, str(linked_parent / target.name)),))
        self.assertIs(result.failure, Reason.UNSAFE_LINK)

    def test_hardlink_alias_and_nonregular_file_do_not_reach_read(self):
        if not capture.safe_open_supported():
            self.assertIs(capture.capture_metadata(self.roots, (self.item,)).failure, Reason.UNSUPPORTED_SAFE_OPEN)
            return
        alias = self.root / "alias"
        os.link(self.metadata, alias)
        with patch.object(capture.os, "read", side_effect=AssertionError("hardlinked file")):
            result = capture.capture_metadata(self.roots, (self.item,))
        self.assertIs(result.failure, Reason.UNSAFE_LINK)
        alias.unlink()
        self.metadata.unlink()
        os.mkfifo(self.metadata)
        # The wrapping mock changes callable identity, so preserve the original
        # descriptor-support capability in the test's patched support registry.
        with patch.object(capture.os, "open", wraps=capture.os.open) as opens, \
             patch.object(capture.os, "supports_dir_fd", capture.os.supports_dir_fd | {opens}), \
             patch.object(capture.os, "read", side_effect=AssertionError("FIFO")):
            result = capture.capture_metadata(self.roots, (self.item,))
        self.assertIs(result.failure, Reason.UNSAFE_LINK)
        self.assertFalse(any(call.args[0] == self.metadata.name for call in opens.call_args_list))

    def test_oversize_input_does_not_reach_read(self):
        if not capture.safe_open_supported():
            self.assertIs(capture.capture_metadata(self.roots, (self.item,)).failure, Reason.UNSUPPORTED_SAFE_OPEN)
            return
        self.metadata.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
        with patch.object(capture.os, "read", side_effect=AssertionError("oversize")):
            result = capture.capture_metadata(self.roots, (self.item,))
        self.assertIs(result.failure, Reason.LIMIT_EXCEEDED)

    def test_mutated_mtime_during_read_is_deferred(self):
        if not capture.safe_open_supported():
            self.assertIs(capture.capture_metadata(self.roots, (self.item,)).failure, Reason.UNSUPPORTED_SAFE_OPEN)
            return
        original_read = os.read
        changed = False

        def mutate(descriptor, size):
            nonlocal changed
            data = original_read(descriptor, size)
            if not changed:
                info = self.metadata.stat()
                os.utime(self.metadata, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000))
                changed = True
            return data

        with patch.object(capture.os, "read", side_effect=mutate):
            result = capture.capture_metadata(self.roots, (self.item,))
        self.assertIs(result.failure, Reason.INPUT_CHANGED)

    def test_replaced_name_during_read_is_deferred(self):
        if not capture.safe_open_supported():
            self.assertIs(capture.capture_metadata(self.roots, (self.item,)).failure, Reason.UNSUPPORTED_SAFE_OPEN)
            return
        replacement = self.root / "replacement"
        replacement.write_bytes(self.metadata.read_bytes())
        original_read = os.read
        changed = False

        def mutate(descriptor, size):
            nonlocal changed
            data = original_read(descriptor, size)
            if not changed:
                replacement.replace(self.metadata)
                changed = True
            return data

        with patch.object(capture.os, "read", side_effect=mutate):
            result = capture.capture_metadata(self.roots, (self.item,))
        self.assertIs(result.failure, Reason.INPUT_CHANGED)

    def test_aggregate_budget_is_enforced(self):
        if not capture.safe_open_supported():
            self.assertIs(capture.capture_metadata(self.roots, (self.item,)).failure, Reason.UNSUPPORTED_SAFE_OPEN)
            return
        with patch.object(capture, "MAX_TOTAL_BYTES", 1):
            result = capture.capture_metadata(self.roots, (self.item,))
        self.assertIs(result.failure, Reason.LIMIT_EXCEEDED)

    def test_capture_appmanifest_never_becomes_rule_evidence(self):
        manifest = self.root / "appmanifest_1118310.acf"
        manifest.write_bytes(b'"AppState" { "appid" "1118310" "buildid" "555" "installdir" "RetroArch" }')
        result = capture.capture_metadata(self.roots, (capture.MetadataInput(Role.INSTALL, str(manifest)),))
        if not capture.safe_open_supported():
            self.assertIs(result.failure, Reason.UNSUPPORTED_SAFE_OPEN)
            return
        self.assertEqual(result.inventory.installation.build_id, "555")
        self.assertIsNone(result.inventory.rules)
        self.assertIn(Reason.CLOUD_RULES_UNKNOWN, result.inventory.reasons)

    def test_save_root_stat_evidence_opens_nothing(self):
        selected = self.root / "synthetic-save-root"
        selected.mkdir()
        with patch.object(capture.os, "open", side_effect=AssertionError("save target open")), \
             patch("builtins.open", side_effect=AssertionError("payload open")):
            evidence = capture._save_root(selected, (self.root,))
        self.assertIs(evidence.reason, Reason.SAVE_PATH_UNVERIFIED)

    def test_absolute_outside_and_loop_save_links_defer_without_target_open(self):
        if not capture.safe_open_supported():
            self.assertIs(capture.capture_metadata(self.roots, (self.item,)).failure, Reason.UNSUPPORTED_SAFE_OPEN)
            return
        link = self.root / "save-link"
        for target in (str(self.root / "target"), "../outside", "save-link"):
            link.symlink_to(target)
            with patch.object(capture.os, "open", side_effect=AssertionError("save target open")):
                evidence = capture._save_root(link, (self.root,))
            self.assertIs(evidence.reason, Reason.UNSAFE_LINK)
            link.unlink()

    def test_missing_and_excessive_save_link_evidence_defer(self):
        self.assertIs(capture._save_root(self.root / "missing", (self.root,)).reason, Reason.READ_UNAVAILABLE)
        links = [self.root / ("link" + str(index)) for index in range(17)]
        if not capture.safe_open_supported():
            self.assertIs(capture.capture_metadata(self.roots, (self.item,)).failure, Reason.UNSUPPORTED_SAFE_OPEN)
            return
        for index in range(16):
            links[index].symlink_to(links[index + 1].name)
        with patch.object(capture.os, "open", side_effect=AssertionError("save target open")):
            evidence = capture._save_root(links[0], (self.root,))
        self.assertIs(evidence.reason, Reason.UNSAFE_LINK)
        self.assertEqual(len(evidence.link_targets), 16)

    def test_sixteen_save_link_hops_inspect_terminal_and_seventeen_defer(self):
        # In-memory lstat/readlink evidence exercises the boundary on every OS.
        for count, expected in ((16, Reason.SAVE_PATH_UNVERIFIED), (17, Reason.UNSAFE_LINK)):
            links = [self.root / ("bounded-link" + str(index)) for index in range(count)]
            terminal = self.root / "bounded-terminal"
            targets = {str(link): (links[index + 1].name if index + 1 < count else terminal.name)
                       for index, link in enumerate(links)}

            def fake_lstat(path):
                mode = stat.S_IFLNK if str(path) in targets else stat.S_IFDIR
                return SimpleNamespace(st_mode=mode, st_file_attributes=0)

            with self.subTest(count=count), \
                 patch.object(capture.os, "lstat", side_effect=fake_lstat) as stats, \
                 patch.object(capture.os, "readlink", side_effect=lambda path: targets[str(path)]) as reads, \
                 patch.object(capture.os, "open", side_effect=AssertionError("save target open")), \
                 patch("builtins.open", side_effect=AssertionError("save payload open")):
                evidence = capture._save_root(links[0], (self.root,))
                self.assertIs(evidence.reason, expected)
                self.assertEqual(len(evidence.link_targets), 16)
                self.assertEqual(reads.call_count, 16)
                inspected = [call.args[0] for call in stats.call_args_list]
                if count == 16:
                    self.assertIn(terminal, inspected)
                else:
                    self.assertIn(links[16], inspected)
                    self.assertNotIn(terminal, inspected)


if __name__ == "__main__":
    unittest.main()
