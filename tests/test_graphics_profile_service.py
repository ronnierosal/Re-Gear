"""The milestone proof of concept, end to end, against fake fixtures only.

discover -> read -> validate -> backup -> apply Portable -> verify ->
apply TV Docked -> verify -> restore, with restoration asserted byte-for-byte.
"""

from __future__ import annotations

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
from regear.delivery.graphics_profile_service import (  # noqa: E402
    ApplyResult,
    GameRunState,
    GraphicsProfileService,
    ManagedKeyCatalog,
    RestoreResult,
)
from regear.domain.graphics_profiles import (  # noqa: E402
    GraphicsProfile,
    ManagedKey,
    SupportTier,
    ValueKind,
)
from regear.domain.models import OperatingMode  # noqa: E402


APP = fixtures.PROTON_APP_ID
CATALOG = ManagedKeyCatalog(
    {
        APP: {
            key.address: key
            for key in (
                ManagedKey("Graphics", "TextureQuality", ValueKind.INTEGER, minimum=0, maximum=3),
                ManagedKey("Graphics", "ShadowQuality", ValueKind.INTEGER, minimum=0, maximum=3),
                ManagedKey("Graphics", "FrameRateLimit", ValueKind.INTEGER, minimum=30, maximum=240),
            )
        }
    }
)

PORTABLE = GraphicsProfile(
    APP,
    OperatingMode.PORTABLE,
    fixtures.CONFIG_FILENAME,
    {
        "Graphics/TextureQuality": "1",
        "Graphics/ShadowQuality": "0",
        "Graphics/FrameRateLimit": "40",
    },
)
TV_DOCKED = GraphicsProfile(
    APP,
    OperatingMode.TV_DOCKED,
    fixtures.CONFIG_FILENAME,
    {
        "Graphics/TextureQuality": "3",
        "Graphics/ShadowQuality": "3",
        "Graphics/FrameRateLimit": "120",
    },
)


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.steam_root = fixtures.build_library(self.base)
        self.config = fixtures.proton_config_path(self.steam_root)
        self.original = self.config.read_bytes()
        self.backups = BackupManager(self.base / "backups", limit=4)
        self.service = GraphicsProfileService(
            GraphicsConfigLocator(self.steam_root), self.backups, CATALOG
        )

    def apply(self, profile, run_state=GameRunState.NOT_RUNNING):
        return self.service.apply(profile, fixtures.GAME_CONFIG_DIR, run_state)

    def restore(self, profile=PORTABLE, run_state=GameRunState.NOT_RUNNING, record=None):
        return self.service.restore(profile, fixtures.GAME_CONFIG_DIR, run_state, record)

    def values(self):
        from regear.domain.graphics_config_format import parse_document

        # Bytes, not read_text: universal-newline translation would hide the
        # very CRLF preservation these tests are checking.
        return parse_document(self.config.read_bytes().decode("utf-8")).values()


class ProofOfConceptTests(ServiceTestCase):
    def test_full_sequence_portable_then_tv_docked_then_restore(self):
        located = self.service.discover(PORTABLE, fixtures.GAME_CONFIG_DIR)
        self.assertTrue(located.located)

        portable = self.apply(PORTABLE)
        self.assertIs(portable.result, ApplyResult.APPLIED)
        self.assertIs(portable.tier, SupportTier.MANAGED)
        self.assertEqual(portable.before_digest, digest_of(self.original))
        self.assertEqual(
            self.values()["Graphics/TextureQuality"], "1"
        )
        self.assertEqual(self.values()["Graphics/FrameRateLimit"], "40")

        docked = self.apply(TV_DOCKED)
        self.assertIs(docked.result, ApplyResult.APPLIED)
        self.assertEqual(self.values()["Graphics/TextureQuality"], "3")
        self.assertEqual(self.values()["Graphics/FrameRateLimit"], "120")

        # Restoring the first backup is a return to the untouched original.
        first_backup = self.backups.records(located.location.identity)[0]
        outcome = self.restore(record=first_backup)
        self.assertIs(outcome.result, RestoreResult.RESTORED)
        self.assertTrue(outcome.byte_identical)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_unrelated_settings_survive_both_applications_byte_for_byte(self):
        self.apply(PORTABLE)
        self.apply(TV_DOCKED)
        before = [
            line
            for line in self.original.decode("utf-8").splitlines(keepends=True)
            if not line.lstrip().startswith(("TextureQuality", "ShadowQuality", "FrameRateLimit"))
        ]
        after = [
            line
            for line in self.config.read_bytes().decode("utf-8").splitlines(keepends=True)
            if not line.lstrip().startswith(("TextureQuality", "ShadowQuality", "FrameRateLimit"))
        ]
        self.assertEqual(before, after)
        self.assertEqual(self.values()["Audio/MasterVolume"], "0.8")
        self.assertEqual(self.values()["Display/ResolutionX"], "1280")

    def test_applying_the_same_profile_twice_writes_nothing_the_second_time(self):
        self.apply(PORTABLE)
        after_first = self.config.read_bytes()
        second = self.apply(PORTABLE)
        self.assertIs(second.result, ApplyResult.ALREADY_MATCHES)
        self.assertEqual(self.config.read_bytes(), after_first)
        self.assertEqual(len(self.backups.records("620.proton.graphics.ini")), 1)

    def test_every_write_is_preceded_by_a_backup(self):
        identity = "620.proton.graphics.ini"
        self.assertEqual(self.backups.records(identity), ())
        self.apply(PORTABLE)
        records = self.backups.records(identity)
        self.assertEqual(len(records), 1)
        self.assertEqual(self.backups.payload(records[0]), self.original)
        self.assertEqual(records[0].mode, OperatingMode.PORTABLE.value)

    def test_native_game_path_applies_too(self):
        native_profile = GraphicsProfile(
            fixtures.NATIVE_APP_ID,
            OperatingMode.TV_DOCKED,
            fixtures.CONFIG_FILENAME,
            {"Graphics/TextureQuality": "2"},
        )
        catalog = ManagedKeyCatalog(
            {
                fixtures.NATIVE_APP_ID: {
                    "Graphics/TextureQuality": ManagedKey(
                        "Graphics", "TextureQuality", ValueKind.INTEGER, minimum=0, maximum=3
                    )
                }
            }
        )
        service = GraphicsProfileService(
            GraphicsConfigLocator(self.steam_root), self.backups, catalog
        )
        outcome = service.apply(
            native_profile, fixtures.GAME_CONFIG_DIR, GameRunState.NOT_RUNNING
        )
        self.assertIs(outcome.result, ApplyResult.APPLIED)
        native = fixtures.native_config_path(self.steam_root).read_text(encoding="utf-8")
        self.assertIn("TextureQuality=2", native)
        # The Proton copy of the same game's file was not touched.
        self.assertEqual(self.config.read_bytes(), self.original)


class SafetyTests(ServiceTestCase):
    def test_running_game_is_refused_before_anything_is_read(self):
        outcome = self.apply(PORTABLE, GameRunState.RUNNING)
        self.assertIs(outcome.result, ApplyResult.REFUSED_GAME_RUNNING)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(self.backups.records("620.proton.graphics.ini"), ())

    def test_unknown_run_state_fails_closed(self):
        outcome = self.apply(PORTABLE, GameRunState.UNKNOWN)
        self.assertIs(outcome.result, ApplyResult.REFUSED_RUN_STATE_UNKNOWN)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_restore_refuses_while_the_game_runs(self):
        self.apply(PORTABLE)
        applied = self.config.read_bytes()
        outcome = self.restore(run_state=GameRunState.RUNNING)
        self.assertIs(outcome.result, RestoreResult.REFUSED_GAME_RUNNING)
        self.assertEqual(self.config.read_bytes(), applied)

    def test_unknown_schema_falls_back_to_advisor_without_writing(self):
        odd = self.config.parent / "odd.ini"
        odd.write_text("[Graphics]\nthis line is not a setting\n", encoding="utf-8")
        profile = GraphicsProfile(
            APP, OperatingMode.PORTABLE, "odd.ini", {"Graphics/TextureQuality": "1"}
        )
        before = odd.read_bytes()
        outcome = self.apply(profile)
        self.assertIs(outcome.result, ApplyResult.ADVISOR)
        self.assertIs(outcome.tier, SupportTier.ADVISOR)
        self.assertTrue(outcome.advice)
        self.assertEqual(odd.read_bytes(), before)

    def test_unknown_key_is_advisor_and_leaves_the_file_alone(self):
        profile = GraphicsProfile(
            APP,
            OperatingMode.PORTABLE,
            fixtures.CONFIG_FILENAME,
            {"Graphics/TextureQuality": "1", "Graphics/NotInTheFile": "1"},
        )
        outcome = self.apply(profile)
        self.assertIs(outcome.result, ApplyResult.ADVISOR)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_unlocatable_game_is_an_outcome_not_an_exception(self):
        missing = GraphicsProfile(
            "999999", OperatingMode.PORTABLE, fixtures.CONFIG_FILENAME,
            {"Graphics/TextureQuality": "1"},
        )
        outcome = self.apply(missing)
        self.assertIs(outcome.result, ApplyResult.NOT_LOCATED)

    def test_a_failed_write_rolls_back_to_the_original_bytes(self):
        class FailingStore(GraphicsConfigStore):
            def write(self, path, text):
                raise ConfigIoError("disk is full")

        service = GraphicsProfileService(
            GraphicsConfigLocator(self.steam_root), self.backups, CATALOG, FailingStore()
        )
        outcome = service.apply(PORTABLE, fixtures.GAME_CONFIG_DIR, GameRunState.NOT_RUNNING)
        self.assertIs(outcome.result, ApplyResult.ROLLED_BACK)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(outcome.after_digest, digest_of(self.original))

    def test_a_write_that_does_not_verify_is_rolled_back(self):
        class WrongStore(GraphicsConfigStore):
            def write(self, path, text):
                # Writes something other than what the plan rendered: the
                # verification step, not the plan, has to catch this.
                return super().write(path, text.replace("MasterVolume=0.8", "MasterVolume=0.1"))

        service = GraphicsProfileService(
            GraphicsConfigLocator(self.steam_root), self.backups, CATALOG, WrongStore()
        )
        outcome = service.apply(PORTABLE, fixtures.GAME_CONFIG_DIR, GameRunState.NOT_RUNNING)
        self.assertIs(outcome.result, ApplyResult.ROLLED_BACK)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_backup_failure_prevents_the_write_entirely(self):
        class RefusingBackups(BackupManager):
            def capture(self, identity, source, mode):
                raise ValueError("no room for backups")

        service = GraphicsProfileService(
            GraphicsConfigLocator(self.steam_root),
            RefusingBackups(self.base / "refusing"),
            CATALOG,
        )
        outcome = service.apply(PORTABLE, fixtures.GAME_CONFIG_DIR, GameRunState.NOT_RUNNING)
        self.assertIs(outcome.result, ApplyResult.FAILED)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_restore_with_no_backup_is_reported_not_guessed(self):
        outcome = self.restore()
        self.assertIs(outcome.result, RestoreResult.NOTHING_TO_RESTORE)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_no_path_outside_the_fixture_root_is_touched(self):
        outside = self.base / "outside.ini"
        outside.write_text("untouched\n", encoding="utf-8")
        self.apply(PORTABLE)
        self.apply(TV_DOCKED)
        self.restore()
        self.assertEqual(outside.read_text(encoding="utf-8"), "untouched\n")


class StoreTests(ServiceTestCase):
    def test_write_preserves_the_file_mode(self):
        import os

        os.chmod(self.config, 0o640)
        self.apply(PORTABLE)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)

    def test_write_leaves_no_temporary_files(self):
        self.apply(PORTABLE)
        leftovers = [path.name for path in self.config.parent.iterdir() if path.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_reading_a_non_utf8_file_is_an_io_error(self):
        binary = self.config.parent / "binary.ini"
        binary.write_bytes(b"[G]\nk=\xff\xfe\n")
        with self.assertRaises(ConfigIoError):
            GraphicsConfigStore().read(binary)


if __name__ == "__main__":
    unittest.main()
