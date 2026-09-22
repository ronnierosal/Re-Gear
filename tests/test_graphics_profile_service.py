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

import dataclasses  # noqa: E402
import shutil  # noqa: E402

import graphics_profile_fixtures as fixtures  # noqa: E402
from regear.delivery.graphics_backup import BackupManager, digest_of  # noqa: E402
from regear.delivery.graphics_config_locator import GraphicsConfigLocator  # noqa: E402
from regear.delivery.graphics_config_store import (  # noqa: E402
    ConfigChangedError,
    ConfigIoError,
    GraphicsConfigStore,
)
from regear.delivery.graphics_backup import BackupChangedError  # noqa: E402
from regear.delivery.graphics_management_state import (  # noqa: E402
    Lifecycle,
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


class ProvenanceTrustTests(ServiceTestCase):
    """Finding 1: absent, corrupt and trusted provenance are three answers."""

    def state_path(self):
        return self.base / "state" / f"{self.identity()}.json"

    def test_a_deleted_record_does_not_license_an_overwrite(self):
        self.apply(PORTABLE)
        edited = self.config.read_bytes().replace(
            b"sg.TextureQuality=1", b"sg.TextureQuality=2"
        )
        self.config.write_bytes(edited)
        self.state_path().unlink()
        outcome = self.apply(TV_DOCKED)
        self.assertIs(outcome.result, ApplyResult.CONFLICT)
        self.assertEqual(self.config.read_bytes(), edited)

    def test_a_corrupt_record_does_not_license_a_restore(self):
        self.apply(PORTABLE)
        edited = self.config.read_bytes().replace(
            b"MasterVolume=0.8", b"MasterVolume=0.2"
        )
        self.config.write_bytes(edited)
        self.state_path().write_text("{not json", encoding="utf-8")
        outcome = self.restore()
        self.assertIs(outcome.result, RestoreResult.CONFLICT)
        self.assertEqual(self.config.read_bytes(), edited)

    def test_a_lost_record_still_blocks_restore_even_without_an_edit(self):
        # Restoring needs proof of authorship, not merely the absence of a
        # visible edit.
        self.apply(PORTABLE)
        applied = self.config.read_bytes()
        self.state_path().unlink()
        outcome = self.restore()
        self.assertIs(outcome.result, RestoreResult.CONFLICT)
        self.assertEqual(self.config.read_bytes(), applied)

    def test_the_player_can_still_force_a_restore_with_no_record(self):
        self.apply(PORTABLE)
        self.state_path().unlink()
        outcome = self.restore(accept_player_edits=True)
        self.assertIs(outcome.result, RestoreResult.RESTORED)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_first_enrollment_still_works_with_no_provenance_at_all(self):
        # The fix must not make provenance a prerequisite for ever starting.
        self.assertFalse(self.state_path().exists())
        outcome = self.apply(PORTABLE)
        self.assertIs(outcome.result, ApplyResult.APPLIED)


class ReplacementBoundaryTests(ServiceTestCase):
    """Findings 2 and 3: nothing is overwritten that Re-Gear did not write."""

    def racing_store(self, then_fail):
        original = self.original

        class RacingStore(GraphicsConfigStore):
            def write(inner, path, text, expected=None):
                # An external writer lands after the profile was planned and
                # the backup taken, but before the replacement.
                path.write_bytes(
                    path.read_bytes().replace(b"MasterVolume=0.8", b"MasterVolume=0.5")
                )
                if then_fail:
                    raise ConfigIoError("write failed after an external edit landed")
                return super().write(path, text, expected)

        return RacingStore()

    def test_an_edit_arriving_before_the_replacement_is_not_overwritten(self):
        service = self.build_service(store=self.racing_store(then_fail=False))
        outcome = self.apply(PORTABLE, service=service)
        self.assertIs(outcome.result, ApplyResult.CONFLICT)
        self.assertIn(b"MasterVolume=0.5", self.config.read_bytes())

    def test_rollback_never_restores_over_content_re_gear_did_not_write(self):
        service = self.build_service(store=self.racing_store(then_fail=True))
        outcome = self.apply(PORTABLE, service=service)
        self.assertIs(outcome.result, ApplyResult.CONFLICT)
        self.assertIn(b"MasterVolume=0.5", self.config.read_bytes())

    def test_a_file_that_cannot_be_re_read_is_left_alone_not_overwritten(self):
        class UnreadableAfterWrite(GraphicsConfigStore):
            def __init__(inner):
                inner.written = False

            def read(inner, path):
                if inner.written:
                    raise ConfigIoError("the file became unreadable")
                return super().read(path)

            def write(inner, path, text, expected=None):
                inner.written = True
                raise ConfigIoError("write failed")

        service = self.build_service(store=UnreadableAfterWrite())
        outcome = self.apply(PORTABLE, service=service)
        self.assertIs(outcome.result, ApplyResult.FAILED)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_the_store_refuses_a_write_whose_expected_bytes_are_stale(self):
        store = GraphicsConfigStore()
        with self.assertRaises(ConfigChangedError):
            store.write(self.config, "[G]\nk=1\n", expected=b"something else entirely")
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_restore_refuses_when_the_target_changes_at_the_boundary(self):
        self.apply(PORTABLE)
        applied = self.config.read_bytes()
        baseline = self.backups.baseline(self.identity()).record

        with self.assertRaises(Exception) as caught:
            self.backups.restore(baseline, self.config, expected=b"stale expectation")
        self.assertIn("changed", str(caught.exception))
        self.assertEqual(self.config.read_bytes(), applied)


class ProfileBindingTests(ServiceTestCase):
    """Finding 5: a profile must be admitted, not merely recorded."""

    def test_a_profile_for_another_schema_is_refused_before_any_write(self):
        foreign = dataclasses.replace(PORTABLE, schema_id="unrelated-schema")
        outcome = self.apply(foreign)
        self.assertIs(outcome.result, ApplyResult.UNSUPPORTED)
        self.assertIs(outcome.tier, SupportTier.UNKNOWN)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(self.backups.records(self.identity()), ())

    def test_an_unaccepted_profile_version_is_refused(self):
        future = dataclasses.replace(PORTABLE, profile_version=999)
        outcome = self.apply(future)
        self.assertIs(outcome.result, ApplyResult.UNSUPPORTED)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_a_declared_accepted_version_is_admitted(self):
        catalog = ManagedKeyCatalog({APP: VALIDATORS}, {APP: SCHEMA}, {APP: (1, 2)})
        service = self.build_service(catalog=catalog)
        outcome = self.apply(dataclasses.replace(PORTABLE, profile_version=2), service=service)
        self.assertIs(outcome.result, ApplyResult.APPLIED)

    def test_a_game_with_no_schema_refuses_a_schema_bound_profile(self):
        service = self.build_service(catalog=ManagedKeyCatalog({APP: VALIDATORS}, {}))
        outcome = self.apply(PORTABLE, service=service)
        self.assertIs(outcome.result, ApplyResult.UNSUPPORTED)


class BaselineTests(ServiceTestCase):
    """Finding 2: the original must outlive the rotating backups."""

    def test_the_original_survives_more_mode_changes_than_the_limit(self):
        for profile in (PORTABLE, TV_DOCKED, BOOSTED, PORTABLE, TV_DOCKED):
            self.apply(profile)
        records = self.backups.records(self.identity())
        self.assertTrue(any(self.backups.payload(r) == self.original for r in records))
        baseline = self.backups.baseline(self.identity())
        self.assertTrue(baseline.verified)
        self.assertEqual(self.backups.payload(baseline.record), self.original)

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

    def corrupt_the_baseline(self):
        baseline = self.backups.baseline(self.identity())
        (self.backups.root / self.identity() / baseline.record.payload_name).write_bytes(b"junk")

    def test_a_corrupt_baseline_refuses_rather_than_writing_garbage(self):
        self.apply(PORTABLE)
        applied = self.config.read_bytes()
        self.corrupt_the_baseline()
        outcome = self.restore()
        self.assertIs(outcome.result, RestoreResult.FAILED)
        self.assertEqual(self.config.read_bytes(), applied)

    def test_a_corrupt_baseline_blocks_further_managed_writes(self):
        self.apply(PORTABLE)
        applied = self.config.read_bytes()
        self.corrupt_the_baseline()
        outcome = self.apply(TV_DOCKED)
        self.assertIs(outcome.result, ApplyResult.FAILED)
        self.assertFalse(outcome.restoration_available)
        self.assertEqual(self.config.read_bytes(), applied)

    def test_losing_the_baseline_record_does_not_promote_a_rotating_copy(self):
        self.apply(PORTABLE)
        identity = self.identity()
        baseline = self.backups.baseline(identity)
        stem = baseline.record.payload_name[: -len(".bak")]
        (self.backups.root / identity / f"{stem}.json").unlink()
        # The original is gone; the next capture must not christen itself one.
        outcome = self.apply(TV_DOCKED)
        self.assertIs(outcome.result, ApplyResult.FAILED)
        self.assertFalse(self.backups.baseline(identity).verified)


class LostBaselineTests(ServiceTestCase):
    """Finding 1: a previously managed target's NONE is lost, not new."""

    def test_losing_every_backup_file_blocks_writes_and_the_fake_original(self):
        self.apply(PORTABLE)
        managed = self.config.read_bytes()
        shutil.rmtree(self.backups.root / self.identity())

        outcome = self.apply(TV_DOCKED)
        self.assertIs(outcome.result, ApplyResult.FAILED)
        self.assertFalse(outcome.restoration_available)
        self.assertEqual(self.config.read_bytes(), managed)
        # Nothing was captured, so the managed bytes were not christened the
        # player's original.
        self.assertEqual(self.backups.records(self.identity()), ())

    def test_restore_after_losing_every_backup_never_returns_managed_bytes(self):
        self.apply(PORTABLE)
        managed = self.config.read_bytes()
        shutil.rmtree(self.backups.root / self.identity())
        outcome = self.restore(accept_player_edits=True)
        self.assertIs(outcome.result, RestoreResult.NOTHING_TO_RESTORE)
        self.assertNotEqual(managed, self.original)
        self.assertEqual(self.config.read_bytes(), managed)

    def test_a_valid_but_foreign_baseline_is_refused(self):
        self.apply(PORTABLE)
        identity = self.identity()
        shutil.rmtree(self.backups.root / identity)
        # A perfectly valid backup of the right target, but not the original
        # this target was enrolled with.
        self.backups.capture(identity, self.config, "portable")
        self.assertTrue(self.backups.baseline(identity).verified)
        outcome = self.apply(TV_DOCKED)
        self.assertIs(outcome.result, ApplyResult.FAILED)
        self.assertIn("not the one this target was enrolled with", outcome.detail)

    def replacement_baseline(self):
        """Wipe the store, then capture a valid backup of the MANAGED bytes."""
        identity = self.identity()
        shutil.rmtree(self.backups.root / identity)
        self.backups.capture(identity, self.config, "portable")
        self.assertTrue(self.backups.baseline(identity).verified)

    def test_default_restore_refuses_a_replacement_baseline(self):
        # Apply already refused this; Restore My Settings must too, or it hands
        # back a Re-Gear profile while calling it the player's own settings.
        self.apply(PORTABLE)
        managed = self.config.read_bytes()
        self.replacement_baseline()
        outcome = self.restore()
        self.assertIs(outcome.result, RestoreResult.FAILED)
        self.assertFalse(outcome.byte_identical)
        self.assertEqual(self.config.read_bytes(), managed)
        self.assertNotEqual(managed, self.original)

    def test_discarding_player_edits_does_not_authorise_a_replacement_baseline(self):
        # The override discards edits; it does not redefine "the original".
        self.apply(PORTABLE)
        managed = self.config.read_bytes()
        self.replacement_baseline()
        outcome = self.restore(accept_player_edits=True)
        self.assertIs(outcome.result, RestoreResult.FAILED)
        self.assertEqual(self.config.read_bytes(), managed)

    def test_an_intact_store_still_restores_the_enrolled_original(self):
        self.apply(PORTABLE)
        self.apply(TV_DOCKED)
        outcome = self.restore()
        self.assertIs(outcome.result, RestoreResult.RESTORED)
        self.assertTrue(outcome.byte_identical)
        self.assertTrue(outcome.restored_enrolled_baseline)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_an_explicitly_chosen_older_backup_is_reported_as_not_the_original(self):
        # Explicit historical restoration stays possible, but it is not allowed
        # to claim it returned the settings the target was enrolled with.
        self.apply(PORTABLE)
        self.apply(TV_DOCKED)
        records = self.backups.records(self.identity())
        rotating = [record for record in records if not record.baseline]
        self.assertTrue(rotating)
        outcome = self.restore(record=rotating[-1], accept_player_edits=True)
        self.assertIs(outcome.result, RestoreResult.RESTORED)
        self.assertFalse(outcome.restored_enrolled_baseline)
        self.assertNotEqual(self.config.read_bytes(), self.original)

    def test_a_first_enrollment_with_no_history_still_proceeds(self):
        outcome = self.apply(PORTABLE)
        self.assertIs(outcome.result, ApplyResult.APPLIED)


class LifecycleTests(ServiceTestCase):
    """Finding 2: completed operations are known states, not lost records."""

    def record(self):
        return self.management.load(self.identity()).record

    def test_a_transient_write_failure_can_be_retried_through_the_launch_path(self):
        class FailOnce(GraphicsConfigStore):
            def __init__(inner):
                inner.fail = True

            def write(inner, path, text, expected=None):
                if inner.fail:
                    raise ConfigIoError("transient write failure")
                return super().write(path, text, expected)

        store = FailOnce()
        service = self.build_service(store=store)
        first = self.apply(PORTABLE, service=service)
        self.assertIs(first.result, ApplyResult.ROLLED_BACK)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertIs(self.record().lifecycle, Lifecycle.ROLLED_BACK)

        store.fail = False
        retry = service.prepare_for_launch(
            PORTABLE, fixtures.GAME_CONFIG_DIR, GameRunState.NOT_RUNNING
        )
        self.assertTrue(retry.may_launch)
        self.assertIs(retry.apply_outcome.result, ApplyResult.APPLIED)
        self.assertIs(self.record().lifecycle, Lifecycle.MANAGED)

    def test_apply_restore_apply_is_an_ordinary_re_enrollment(self):
        self.apply(PORTABLE)
        restored = self.restore()
        self.assertIs(restored.result, RestoreResult.RESTORED)
        self.assertIs(self.record().lifecycle, Lifecycle.RESTORED)
        again = self.apply(TV_DOCKED)
        self.assertIs(again.result, ApplyResult.APPLIED)

    def test_an_edit_after_a_restore_is_still_a_conflict(self):
        # Re-enrollment follows from the recorded digest, not from the mere
        # fact that a restore happened.
        self.apply(PORTABLE)
        self.restore()
        edited = self.config.read_bytes().replace(b"MasterVolume=0.8", b"MasterVolume=0.3")
        self.config.write_bytes(edited)
        outcome = self.apply(TV_DOCKED)
        self.assertIs(outcome.result, ApplyResult.CONFLICT)
        self.assertEqual(self.config.read_bytes(), edited)

    def test_stop_managing_needs_an_explicit_resume(self):
        self.apply(PORTABLE)
        self.service.stop_managing(PORTABLE, fixtures.GAME_CONFIG_DIR)
        self.assertIs(self.apply(TV_DOCKED).result, ApplyResult.CONFLICT)

        resumed = self.service.resume_managing(PORTABLE, fixtures.GAME_CONFIG_DIR)
        self.assertIsNotNone(resumed)
        self.assertIs(self.apply(TV_DOCKED).result, ApplyResult.APPLIED)

    def test_resuming_a_target_nobody_stopped_does_nothing(self):
        self.apply(PORTABLE)
        self.assertIsNone(self.service.resume_managing(PORTABLE, fixtures.GAME_CONFIG_DIR))

    def test_a_genuinely_lost_record_is_still_a_conflict(self):
        # The lifecycle states must not weaken detection of a lost record.
        self.apply(PORTABLE)
        (self.base / "state" / f"{self.identity()}.json").unlink()
        self.assertIs(self.apply(TV_DOCKED).result, ApplyResult.CONFLICT)


class VanishedTargetTests(ServiceTestCase):
    """Finding 3: a deleted target is a change, not an invitation to create."""

    def test_restore_does_not_recreate_a_target_deleted_at_the_boundary(self):
        self.apply(PORTABLE)
        chosen = self.backups.baseline(self.identity()).record
        original_write = BackupManager._write_atomic

        def racing(target, payload, expected=None):
            if expected is not None:
                Path(target).unlink()
            return original_write(target, payload, expected)

        BackupManager._write_atomic = staticmethod(racing)
        self.addCleanup(setattr, BackupManager, "_write_atomic", staticmethod(original_write))
        outcome = self.restore()
        self.assertIs(outcome.result, RestoreResult.CONFLICT)
        self.assertFalse(self.config.exists())

    def test_the_backup_writer_refuses_a_missing_expected_target(self):
        self.apply(PORTABLE)
        chosen = self.backups.baseline(self.identity()).record
        self.config.unlink()
        with self.assertRaises(BackupChangedError):
            self.backups.restore(chosen, self.config, expected=b"anything")
        self.assertFalse(self.config.exists())

    def test_the_config_store_refuses_a_missing_expected_target(self):
        payload = self.config.read_bytes()
        self.config.unlink()
        with self.assertRaises(ConfigChangedError):
            GraphicsConfigStore().write(self.config, "[G]\nk=1\n", expected=payload)
        self.assertFalse(self.config.exists())

    def test_creating_a_new_backup_file_still_works_without_an_expectation(self):
        # The refusal must not break writes whose job is to create a file.
        outcome = self.apply(PORTABLE)
        self.assertIs(outcome.result, ApplyResult.APPLIED)
        self.assertTrue(self.backups.baseline(self.identity()).verified)


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
            def write(self, path, text, expected=None):
                raise ConfigIoError("disk is full")

        service = self.build_service(store=FailingStore())
        outcome = self.apply(PORTABLE, service=service)
        self.assertIs(outcome.result, ApplyResult.ROLLED_BACK)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_a_write_that_does_not_verify_is_rolled_back(self):
        class WrongStore(GraphicsConfigStore):
            def write(self, path, text, expected=None):
                return super().write(
                    path, text.replace("MasterVolume=0.8", "MasterVolume=0.1"), expected
                )

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
