"""The milestone proof of concept, end to end, against fake fixtures only.

discover -> read -> validate schema -> provenance -> backup -> apply Portable ->
verify -> apply TV Docked -> verify -> restore, with restoration asserted
byte-for-byte, plus one regression test per primary-review finding.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

import graphics_profile_fixtures as fixtures  # noqa: E402
from regear.delivery.graphics_backup import BackupManager, digest_of  # noqa: E402
from regear.delivery.graphics_config_locator import GraphicsConfigLocator  # noqa: E402
from regear.delivery.graphics_config_store import (  # noqa: E402
    ConfigIoError,
    GraphicsConfigStore,
)
from regear.delivery.graphics_management_state import (  # noqa: E402
    ManagementStateError,
    ManagementStateStore,
)
from regear.delivery.graphics_profile_service import (  # noqa: E402
    ApplyResult,
    GameRunState,
    GraphicsProfileService,
    LaunchDecision,
    ManagedKeyCatalog,
    RestoreResult,
)
from regear.domain.graphics_config_format import parse_document  # noqa: E402
from regear.domain.graphics_profiles import GraphicsProfile, SupportTier  # noqa: E402
from regear.domain.mode_profiles import ExperienceTarget  # noqa: E402
from regear.domain.models import OperatingMode  # noqa: E402


APP = fixtures.PROTON_APP_ID
ADAPTER = fixtures.sample_adapter()
SCHEMA, VALIDATORS = fixtures.sample_schema()
CATALOG = ManagedKeyCatalog({APP: VALIDATORS}, {APP: SCHEMA})

PORTABLE = ADAPTER.profile_for(APP, OperatingMode.PORTABLE, ExperienceTarget.BATTERY)
TV_DOCKED = ADAPTER.profile_for(APP, OperatingMode.TV_DOCKED, ExperienceTarget.QUALITY)
BOOSTED = ADAPTER.profile_for(
    APP, OperatingMode.BOOSTED_HANDHELD, ExperienceTarget.BALANCED
)


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.steam_root = fixtures.build_library(self.base)
        self.config = fixtures.proton_config_path(self.steam_root)
        self.original = self.config.read_bytes()
        self.backups = BackupManager(self.base / "backups", limit=2)
        self.management = ManagementStateStore(self.base / "state")
        self.service = self.build_service()

    def build_service(self, backups=None, management=None, store=None, catalog=CATALOG):
        return GraphicsProfileService(
            GraphicsConfigLocator(self.steam_root),
            backups or self.backups,
            catalog,
            management or self.management,
            store,
        )

    def apply(self, profile, run_state=GameRunState.NOT_RUNNING, service=None):
        return (service or self.service).apply(
            profile, fixtures.GAME_CONFIG_DIR, run_state
        )

    def restore(self, profile=PORTABLE, run_state=GameRunState.NOT_RUNNING, **kwargs):
        return self.service.restore(
            profile, fixtures.GAME_CONFIG_DIR, run_state, **kwargs
        )

    def values(self):
        # Bytes, not read_text: universal-newline translation would hide the
        # very CRLF preservation these tests are checking.
        return parse_document(self.config.read_bytes().decode("utf-8")).values()

    def identity(self):
        return self.service.discover(PORTABLE, fixtures.GAME_CONFIG_DIR).location.identity


class ProofOfConceptTests(ServiceTestCase):
    def test_full_sequence_portable_then_tv_docked_then_restore(self):
        located = self.service.discover(PORTABLE, fixtures.GAME_CONFIG_DIR)
        self.assertTrue(located.located)

        portable = self.apply(PORTABLE)
        self.assertIs(portable.result, ApplyResult.APPLIED)
        self.assertIs(portable.tier, SupportTier.MANAGED)
        self.assertTrue(portable.restoration_available)
        self.assertEqual(portable.before_digest, digest_of(self.original))
        self.assertEqual(self.values()[fixtures.TEXTURE], "1")
        self.assertEqual(self.values()[fixtures.FRAME_LIMIT], "40")

        repeat = self.apply(PORTABLE)
        self.assertIs(repeat.result, ApplyResult.ALREADY_MATCHES)

        docked = self.apply(TV_DOCKED)
        self.assertIs(docked.result, ApplyResult.APPLIED)
        self.assertEqual(self.values()[fixtures.TEXTURE], "3")
        self.assertEqual(self.values()[fixtures.FRAME_LIMIT], "120")

        outcome = self.restore()
        self.assertIs(outcome.result, RestoreResult.RESTORED)
        self.assertTrue(outcome.byte_identical)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_boosted_handheld_translates_from_a_declared_table(self):
        outcome = self.apply(BOOSTED)
        self.assertIs(outcome.result, ApplyResult.APPLIED)
        self.assertEqual(self.values()[fixtures.TEXTURE], "2")

    def test_an_undeclared_mode_target_yields_no_profile_at_all(self):
        self.assertIsNone(
            ADAPTER.profile_for(APP, OperatingMode.PORTABLE, ExperienceTarget.SMOOTH_60)
        )

    def test_unrelated_settings_survive_both_applications_byte_for_byte(self):
        self.apply(PORTABLE)
        self.apply(TV_DOCKED)
        managed_names = ("sg.TextureQuality", "sg.ShadowQuality", "FrameRateLimit")
        before = [
            line
            for line in self.original.decode("utf-8").splitlines(keepends=True)
            if not line.lstrip().startswith(managed_names)
        ]
        after = [
            line
            for line in self.config.read_bytes().decode("utf-8").splitlines(keepends=True)
            if not line.lstrip().startswith(managed_names)
        ]
        self.assertEqual(before, after)
        self.assertEqual(self.values()[fixtures.MASTER_VOLUME], "0.8")
        self.assertEqual(self.values()[fixtures.VIEW_DISTANCE], "3")

    def test_native_game_path_applies_too(self):
        native = ADAPTER.profile_for(
            fixtures.NATIVE_APP_ID, OperatingMode.TV_DOCKED, ExperienceTarget.QUALITY
        )
        service = self.build_service(
            catalog=ManagedKeyCatalog(
                {fixtures.NATIVE_APP_ID: VALIDATORS}, {fixtures.NATIVE_APP_ID: SCHEMA}
            )
        )
        outcome = service.apply(native, fixtures.GAME_CONFIG_DIR, GameRunState.NOT_RUNNING)
        self.assertIs(outcome.result, ApplyResult.APPLIED)
        self.assertIn("sg.TextureQuality=3", fixtures.native_config_path(self.steam_root).read_text())
        # The Proton copy of the same game's file was not touched.
        self.assertEqual(self.config.read_bytes(), self.original)


class PlayerEditTests(ServiceTestCase):
    """Finding 1: intentional player edits must survive apply and restore."""

    def test_a_player_edit_after_apply_blocks_the_next_apply(self):
        self.apply(PORTABLE)
        edited = self.config.read_bytes().replace(
            b"sg.TextureQuality=1", b"sg.TextureQuality=2"
        )
        self.config.write_bytes(edited)
        outcome = self.apply(TV_DOCKED)
        self.assertIs(outcome.result, ApplyResult.CONFLICT)
        self.assertEqual(self.config.read_bytes(), edited)
        self.assertEqual(self.values()[fixtures.TEXTURE], "2")

    def test_a_player_edit_after_apply_blocks_restore(self):
        self.apply(PORTABLE)
        edited = self.config.read_bytes().replace(
            b"MasterVolume=0.8", b"MasterVolume=0.2"
        )
        self.config.write_bytes(edited)
        outcome = self.restore()
        self.assertIs(outcome.result, RestoreResult.CONFLICT)
        self.assertEqual(self.config.read_bytes(), edited)

    def test_the_player_can_explicitly_discard_their_edits(self):
        self.apply(PORTABLE)
        self.config.write_bytes(
            self.config.read_bytes().replace(b"MasterVolume=0.8", b"MasterVolume=0.2")
        )
        outcome = self.restore(accept_player_edits=True)
        self.assertIs(outcome.result, RestoreResult.RESTORED)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_an_unmanaged_file_is_never_a_conflict(self):
        outcome = self.apply(PORTABLE)
        self.assertIs(outcome.result, ApplyResult.APPLIED)

    def test_stop_managing_leaves_the_file_and_blocks_later_writes(self):
        self.apply(PORTABLE)
        applied = self.config.read_bytes()
        record = self.service.stop_managing(PORTABLE, fixtures.GAME_CONFIG_DIR)
        self.assertIsNotNone(record)
        self.assertFalse(record.managing)
        outcome = self.apply(TV_DOCKED)
        self.assertIs(outcome.result, ApplyResult.CONFLICT)
        self.assertEqual(self.config.read_bytes(), applied)
        # The baseline survives opt-out, so Restore My Settings is still offered.
        self.assertTrue(outcome.restoration_available)

    def test_provenance_that_cannot_be_written_undoes_the_write(self):
        class RefusingState(ManagementStateStore):
            def save(self, record):
                raise ManagementStateError("state volume is read-only")

        service = self.build_service(management=RefusingState(self.base / "state2"))
        outcome = self.apply(PORTABLE, service=service)
        self.assertIs(outcome.result, ApplyResult.ROLLED_BACK)
        self.assertEqual(self.config.read_bytes(), self.original)


class BaselineTests(ServiceTestCase):
    """Finding 2: the original must outlive the rotating backups."""

    def test_the_original_survives_more_mode_changes_than_the_limit(self):
        for profile in (PORTABLE, TV_DOCKED, BOOSTED, PORTABLE, TV_DOCKED):
            self.apply(profile)
        records = self.backups.records(self.identity())
        self.assertTrue(any(self.backups.payload(r) == self.original for r in records))
        baseline = self.backups.baseline(self.identity())
        self.assertEqual(self.backups.payload(baseline), self.original)

    def test_default_restore_returns_my_settings_not_the_last_profile(self):
        self.apply(PORTABLE)
        self.apply(TV_DOCKED)
        self.apply(BOOSTED)
        outcome = self.restore()
        self.assertIs(outcome.result, RestoreResult.RESTORED)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_restore_without_any_backup_reports_nothing_to_restore(self):
        outcome = self.restore()
        self.assertIs(outcome.result, RestoreResult.NOTHING_TO_RESTORE)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_a_corrupt_baseline_refuses_rather_than_writing_garbage(self):
        self.apply(PORTABLE)
        applied = self.config.read_bytes()
        baseline = self.backups.baseline(self.identity())
        (self.backups.root / self.identity() / baseline.payload_name).write_bytes(b"junk")
        outcome = self.restore()
        self.assertIs(outcome.result, RestoreResult.FAILED)
        self.assertEqual(self.config.read_bytes(), applied)


class SchemaTests(ServiceTestCase):
    """Finding 3: Managed requires a recognised schema and version."""

    def test_an_unsupported_schema_version_is_unknown_and_writes_nothing(self):
        self.config.write_bytes(self.config.read_bytes().replace(b"Version=5", b"Version=999"))
        before = self.config.read_bytes()
        outcome = self.apply(PORTABLE)
        self.assertIs(outcome.result, ApplyResult.UNSUPPORTED)
        self.assertIs(outcome.tier, SupportTier.UNKNOWN)
        self.assertEqual(self.config.read_bytes(), before)

    def test_a_missing_version_key_is_unknown(self):
        self.config.write_bytes(self.config.read_bytes().replace(b"Version=5\n", b""))
        outcome = self.apply(PORTABLE)
        self.assertIs(outcome.result, ApplyResult.UNSUPPORTED)

    def test_an_unrecognised_current_value_is_never_overwritten(self):
        before = self.config.read_bytes().replace(
            b"sg.TextureQuality=3", b"sg.TextureQuality=NEW_SCHEMA_VALUE"
        )
        self.config.write_bytes(before)
        outcome = self.apply(PORTABLE)
        self.assertIs(outcome.result, ApplyResult.UNSUPPORTED)
        self.assertEqual(self.config.read_bytes(), before)

    def test_a_game_with_no_registered_schema_is_unknown(self):
        service = self.build_service(catalog=ManagedKeyCatalog({APP: VALIDATORS}, {}))
        outcome = self.apply(PORTABLE, service=service)
        self.assertIs(outcome.result, ApplyResult.UNSUPPORTED)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_a_required_key_the_game_dropped_is_unknown(self):
        self.config.write_bytes(
            self.config.read_bytes().replace(b"sg.ViewDistanceQuality = 3\r\n", b"")
        )
        outcome = self.apply(PORTABLE)
        self.assertIs(outcome.result, ApplyResult.UNSUPPORTED)

    def test_malformed_syntax_is_still_unknown(self):
        odd = self.config.parent / "odd.ini"
        odd.write_text("[Graphics]\nthis line is not a setting\n", encoding="utf-8")
        profile = GraphicsProfile(APP, OperatingMode.PORTABLE, "odd.ini", {fixtures.TEXTURE: "1"})
        outcome = self.apply(profile)
        self.assertIs(outcome.result, ApplyResult.UNSUPPORTED)


class FilesystemContainmentTests(ServiceTestCase):
    """Finding 4: real I/O failures become outcomes, never exceptions."""

    def test_a_backup_root_that_is_a_regular_file_is_contained(self):
        blocked = self.base / "not-a-directory"
        blocked.write_text("I am a file\n", encoding="utf-8")
        service = self.build_service(backups=BackupManager(blocked))
        outcome = self.apply(PORTABLE, service=service)
        self.assertIs(outcome.result, ApplyResult.FAILED)
        self.assertEqual(self.config.read_bytes(), self.original)

    @unittest.skipIf(os.geteuid() == 0, "root ignores directory permissions")
    def test_an_unwritable_backup_root_is_contained(self):
        locked = self.base / "locked"
        locked.mkdir()
        os.chmod(locked, 0o500)
        self.addCleanup(os.chmod, locked, 0o700)
        service = self.build_service(backups=BackupManager(locked / "backups"))
        outcome = self.apply(PORTABLE, service=service)
        self.assertIs(outcome.result, ApplyResult.FAILED)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_launch_is_allowed_through_the_caller_contract_on_every_failure(self):
        blocked = self.base / "blocked-root"
        blocked.write_text("not a directory\n", encoding="utf-8")

        class ExplodingStore(GraphicsConfigStore):
            def read(self, path):
                raise RuntimeError("something nobody predicted")

        cases = {
            "backup root unusable": self.build_service(backups=BackupManager(blocked)),
            "reader explodes": self.build_service(store=ExplodingStore()),
            "no schema": self.build_service(catalog=ManagedKeyCatalog({}, {})),
            "healthy": self.service,
        }
        for name, service in cases.items():
            with self.subTest(case=name):
                outcome = service.prepare_for_launch(
                    PORTABLE, fixtures.GAME_CONFIG_DIR, GameRunState.NOT_RUNNING
                )
                self.assertIs(outcome.decision, LaunchDecision.ALLOWED)
                self.assertTrue(outcome.may_launch)

    def test_launch_is_allowed_while_the_game_is_already_running(self):
        outcome = self.service.prepare_for_launch(
            PORTABLE, fixtures.GAME_CONFIG_DIR, GameRunState.RUNNING
        )
        self.assertTrue(outcome.may_launch)
        self.assertIs(outcome.apply_outcome.result, ApplyResult.DEFERRED)

    def test_a_failed_write_rolls_back_to_the_original_bytes(self):
        class FailingStore(GraphicsConfigStore):
            def write(self, path, text):
                raise ConfigIoError("disk is full")

        service = self.build_service(store=FailingStore())
        outcome = self.apply(PORTABLE, service=service)
        self.assertIs(outcome.result, ApplyResult.ROLLED_BACK)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_a_write_that_does_not_verify_is_rolled_back(self):
        class WrongStore(GraphicsConfigStore):
            def write(self, path, text):
                return super().write(path, text.replace("MasterVolume=0.8", "MasterVolume=0.1"))

        service = self.build_service(store=WrongStore())
        outcome = self.apply(PORTABLE, service=service)
        self.assertIs(outcome.result, ApplyResult.ROLLED_BACK)
        self.assertEqual(self.config.read_bytes(), self.original)


class TargetBindingTests(ServiceTestCase):
    """Finding 5: a backup belongs to one exact configuration file."""

    def second_target(self):
        other = self.config.parent.parent / "Config2"
        other.mkdir()
        (other / fixtures.CONFIG_FILENAME).write_text(fixtures.SAMPLE_CONFIG, encoding="utf-8")
        return other / fixtures.CONFIG_FILENAME

    def test_equal_basenames_at_distinct_targets_do_not_share_an_identity(self):
        self.second_target()
        locator = GraphicsConfigLocator(self.steam_root)
        first = locator.locate(
            APP, fixtures.CONFIG_FILENAME, OperatingMode.PORTABLE, fixtures.GAME_CONFIG_DIR
        ).location
        second = locator.locate(
            APP, fixtures.CONFIG_FILENAME, OperatingMode.PORTABLE, "ReGearTestGame/Config2"
        ).location
        self.assertNotEqual(first.identity, second.identity)

    def test_a_backup_from_another_target_is_refused(self):
        other_path = self.second_target()
        self.apply(PORTABLE)
        foreign = self.backups.capture("620.proton.elsewhere", other_path, "portable")
        outcome = self.restore(record=foreign)
        self.assertIs(outcome.result, RestoreResult.FAILED)
        self.assertEqual(self.values()[fixtures.TEXTURE], "1")

    def test_each_target_keeps_its_own_baseline(self):
        other_path = self.second_target()
        self.apply(PORTABLE)
        other_profile = GraphicsProfile(
            APP, OperatingMode.TV_DOCKED, fixtures.CONFIG_FILENAME,
            dict(TV_DOCKED.settings), schema_id=SCHEMA.schema_id,
        )
        self.service.apply(other_profile, "ReGearTestGame/Config2", GameRunState.NOT_RUNNING)
        self.assertEqual(len(self.backups.records(self.identity())), 1)
        self.assertNotEqual(other_path.read_bytes(), self.config.read_bytes())


class ManifestTests(ServiceTestCase):
    """Finding 6: contradictory or ambiguous manifests are refused."""

    def test_a_manifest_naming_another_appid_is_refused(self):
        manifest = self.steam_root / "steamapps" / f"appmanifest_{APP}.acf"
        manifest.write_text(
            manifest.read_text().replace(f'"appid"\t\t"{APP}"', '"appid"\t\t"999999"'),
            encoding="utf-8",
        )
        outcome = self.apply(PORTABLE)
        self.assertIs(outcome.result, ApplyResult.NOT_LOCATED)
        self.assertIn("manifest_contradicts", outcome.detail)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_the_same_appid_in_two_libraries_is_ambiguous(self):
        second = self.base / "sdcard"
        (second / "steamapps" / "common" / fixtures.PROTON_INSTALL_DIR).mkdir(parents=True)
        (second / "steamapps" / f"appmanifest_{APP}.acf").write_text(
            (self.steam_root / "steamapps" / f"appmanifest_{APP}.acf").read_text(),
            encoding="utf-8",
        )
        (self.steam_root / "steamapps" / "libraryfolders.vdf").write_text(
            '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
            % (self.steam_root, second),
            encoding="utf-8",
        )
        outcome = self.apply(PORTABLE)
        self.assertIs(outcome.result, ApplyResult.NOT_LOCATED)
        self.assertIn("ambiguous_install", outcome.detail)


class StoreTests(ServiceTestCase):
    def test_write_preserves_the_file_mode(self):
        os.chmod(self.config, 0o640)
        self.apply(PORTABLE)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)

    def test_write_leaves_no_temporary_files(self):
        self.apply(PORTABLE)
        leftovers = [p.name for p in self.config.parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_reading_a_non_utf8_file_is_an_io_error(self):
        binary = self.config.parent / "binary.ini"
        binary.write_bytes(b"[G]\nk=\xff\xfe\n")
        with self.assertRaises(ConfigIoError):
            GraphicsConfigStore().read(binary)

    def test_no_path_outside_the_fixture_root_is_touched(self):
        outside = self.base / "outside.ini"
        outside.write_text("untouched\n", encoding="utf-8")
        self.apply(PORTABLE)
        self.apply(TV_DOCKED)
        self.restore()
        self.assertEqual(outside.read_text(encoding="utf-8"), "untouched\n")


if __name__ == "__main__":
    unittest.main()
