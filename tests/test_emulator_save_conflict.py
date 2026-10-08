from __future__ import annotations

import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.domain.emulator_save_conflict import (
    BaselineState, LastSyncedBaseline, ReconciliationEvidence,
    ReconciliationKind as Kind, plan_save_reconciliation,
)
from regear.domain.emulator_save_inventory import (
    SaveBinding, SaveDataKind, SaveUnitKind, build_save_manifest,
)


def manifest(data=b"base", *, complete=True, **changes):
    values = dict(
        kind=SaveUnitKind.PSP_GAME_DIRECTORY, unit_id="ULUS00001",
        game_ids=("ULUS00001",), emulator="ppsspp", emulator_version="fixture-v1",
        native_format="psp-savedata", format_version="fixture-format")
    values.update(changes)
    return build_save_manifest(SaveBinding(**values), {"DATA": data}, complete=complete)


def confirmed(value):
    return LastSyncedBaseline(BaselineState.CONFIRMED, value, "fixture-receipt")


def evidence(native, carrier):
    return ReconciliationEvidence(True, True, native.sha256, carrier.sha256)


class EmulatorSaveConflictTests(unittest.TestCase):
    def test_three_way_matrix_preserves_all_copies_and_never_advances_baseline(self):
        base = manifest()
        cases = (
            (b"base", b"base", Kind.UNCHANGED),
            (b"new", b"new", Kind.UNCHANGED),
            (b"base", b"new", Kind.IMPORT_CANDIDATE),
            (b"new", b"base", Kind.EXPORT_CANDIDATE),
            (b"native-new", b"carrier-new", Kind.CONFLICT),
        )
        prior = confirmed(base)
        for native_data, carrier_data, expected in cases:
            native, carrier = manifest(native_data), manifest(carrier_data)
            with self.subTest(expected=expected):
                result = plan_save_reconciliation(native, carrier, prior, evidence(native, carrier))
                self.assertEqual(result.kind, expected)
                self.assertTrue(result.preserve_both)
                self.assertTrue(result.fixture_only)
                self.assertEqual(result.requires_user_choice, expected is Kind.CONFLICT)
                self.assertEqual(result.native_sha256, native.sha256)
                self.assertEqual(prior.manifest, base)
                self.assertEqual(prior.confirmation_id, "fixture-receipt")
                with self.assertRaises(FrozenInstanceError):
                    result.preserve_both = False
                with self.assertRaises(ValueError):
                    replace(result, preserve_both=False)
                with self.assertRaises(ValueError):
                    replace(result, fixture_only=False)

    def test_missing_corrupt_unconfirmed_baselines_defer_even_equal_copies(self):
        value = manifest()
        for baseline in (
            None, LastSyncedBaseline(BaselineState.UNKNOWN),
            LastSyncedBaseline(BaselineState.CORRUPT, value, "fixture-receipt"),
            LastSyncedBaseline(BaselineState.CONFIRMED, value),
            LastSyncedBaseline(BaselineState.CONFIRMED, None, "fixture-receipt"),
        ):
            with self.subTest(baseline=baseline):
                result = plan_save_reconciliation(value, value, baseline, evidence(value, value))
                self.assertEqual(result.kind, Kind.DEFERRED)
                self.assertEqual(result.reason, "baseline_unconfirmed")

    def test_missing_copy_is_not_deletion_or_first_sync(self):
        value = manifest()
        for native, carrier in ((None, value), (value, None), (None, None)):
            result = plan_save_reconciliation(native, carrier, confirmed(value), ReconciliationEvidence())
            self.assertEqual(result.kind, Kind.DEFERRED)
            self.assertEqual(result.reason, "copy_missing")
            self.assertTrue(result.preserve_both)

    def test_partial_native_carrier_or_baseline_defer(self):
        value, partial = manifest(), manifest(complete=False)
        for native, carrier, prior in ((partial, value, value), (value, partial, value), (value, value, partial)):
            result = plan_save_reconciliation(native, carrier, confirmed(prior), evidence(native, carrier))
            self.assertEqual(result.reason, "save_unit_incomplete")
            self.assertEqual(result.kind, Kind.DEFERRED)

    def test_missing_psp_member_never_becomes_a_deletion_candidate(self):
        unit = manifest().binding
        prior = build_save_manifest(unit, {"PARAM.SFO": b"metadata", "DATA": b"save"}, complete=True)
        lost = build_save_manifest(unit, {"PARAM.SFO": b"metadata"}, complete=True)
        for native, carrier in ((lost, prior), (prior, lost), (lost, lost)):
            result = plan_save_reconciliation(native, carrier, confirmed(prior), evidence(native, carrier))
            self.assertEqual(result.kind, Kind.DEFERRED)
            self.assertEqual(result.reason, "members_removed_without_decision")
            self.assertTrue(result.preserve_both)

    def test_binding_and_version_mismatches_never_import(self):
        base = manifest()
        for altered in (
            manifest(b"changed", emulator="different-emulator"),
            manifest(b"changed", emulator_version="fixture-v2"),
            manifest(b"changed", format_version="other-format-version"),
            manifest(b"changed", unit_id="ULUS00002", game_ids=("ULUS00002",)),
        ):
            result = plan_save_reconciliation(base, altered, confirmed(base), evidence(base, altered))
            self.assertEqual(result.reason, "binding_mismatch")
        unknown = manifest(emulator_version=None)
        result = plan_save_reconciliation(unknown, unknown, confirmed(unknown), evidence(unknown, unknown))
        self.assertEqual(result.reason, "version_unknown")

    def test_save_states_are_not_ordinary_save_compatibility(self):
        value = manifest(data_kind=SaveDataKind.SAVE_STATE)
        result = plan_save_reconciliation(value, value, confirmed(value), evidence(value, value))
        self.assertEqual(result.kind, Kind.DEFERRED)
        self.assertEqual(result.reason, "save_state_out_of_scope")

    def test_closed_download_and_both_independent_backup_facts_are_required(self):
        native, carrier = manifest(), manifest(b"changed")
        good = evidence(native, carrier)
        for bad, reason in (
            (replace(good, emulator_closed=None), "emulator_not_confirmed_closed"),
            (replace(good, emulator_closed=False), "emulator_not_confirmed_closed"),
            (replace(good, download_complete=None), "download_not_confirmed"),
            (replace(good, download_complete=False), "download_not_confirmed"),
            (replace(good, native_backup_sha256=None), "independent_backups_unconfirmed"),
            (replace(good, carrier_backup_sha256=None), "independent_backups_unconfirmed"),
            (replace(good, native_backup_sha256=carrier.sha256), "independent_backups_unconfirmed"),
        ):
            with self.subTest(reason=reason):
                result = plan_save_reconciliation(native, carrier, confirmed(native), bad)
                self.assertEqual(result.kind, Kind.DEFERRED)
                self.assertEqual(result.reason, reason)
                self.assertTrue(result.preserve_both)
        # Export is also gated by download first, and carries no upload operation.
        result = plan_save_reconciliation(carrier, native, confirmed(native), replace(good, download_complete=False))
        self.assertEqual(result.kind, Kind.DEFERRED)

    def test_divergence_is_conflict_without_backup_or_time_winner(self):
        base, native, carrier = manifest(), manifest(b"local"), manifest(b"remote")
        result = plan_save_reconciliation(
            native, carrier, confirmed(base), ReconciliationEvidence(True, True))
        self.assertEqual(result.kind, Kind.CONFLICT)
        self.assertTrue(result.requires_user_choice)
        self.assertTrue(result.preserve_both)
        self.assertNotIn("mtime", ReconciliationEvidence.__dataclass_fields__)

    def test_equal_bytes_are_not_remote_acknowledgement(self):
        value = manifest()
        result = plan_save_reconciliation(
            value, value, confirmed(manifest(b"old")), ReconciliationEvidence(True, True))
        self.assertEqual(result.kind, Kind.UNCHANGED)
        self.assertEqual(result.reason, "equal_bytes_no_sync_ack")

    def test_whole_shared_ps2_card_conflicts_as_one_unit(self):
        unit = SaveBinding(
            SaveUnitKind.PS2_WHOLE_CARD, "shared-card", ("SLUS-00001", "SLUS-00002"),
            "pcsx2", "fixture-v1", "ps2-card", "fixture-format")
        base, native, carrier = (
            build_save_manifest(unit, {"card": data}, complete=True)
            for data in (b"base", b"game1 changed", b"game2 changed"))
        result = plan_save_reconciliation(native, carrier, confirmed(base), evidence(native, carrier))
        self.assertEqual(result.kind, Kind.CONFLICT)
        self.assertTrue(result.preserve_both)

    def test_strict_supplied_evidence_rejects_boolean_coercion(self):
        with self.assertRaises(ValueError):
            ReconciliationEvidence(emulator_closed=1)
        with self.assertRaises(ValueError):
            ReconciliationEvidence(native_backup_sha256="invalid")


if __name__ == "__main__":
    unittest.main()
