"""Bounded in-memory fixture reader, deliberately without filesystem or providers.

Metadata fields are supplied declarations, not live observations. Physical PS2
filenames are mapped to one logical 'card' member without changing its bytes.
PSP files keep their complete game-directory-relative names.
"""

from __future__ import annotations

from regear.domain.emulator_save_inventory import (
    CloudRuleEvidence, EmulatorSaveInventory, LaunchIdentity, SaveBinding,
    SaveDataKind, SavePathEvidence, SaveUnitKind, build_save_manifest,
)


def _object(value: object, fields: set[str], label: str) -> dict:
    # Reject arbitrary mapping implementations: fixtures contain data only.
    if type(value) is not dict or len(value) != len(fields) or set(value) != fields:
        raise ValueError(f"invalid {label} fields")
    return value


def _tuple(value: object, limit: int, label: str) -> tuple:
    if type(value) not in (list, tuple) or len(value) > limit:
        raise ValueError(f"invalid {label}")
    return tuple(value)


def read_emulator_save_fixture(
    metadata: dict, files: dict[str, bytes]
) -> EmulatorSaveInventory:
    """Read injected metadata and synthetic bytes, never locations in metadata."""
    root = _object(metadata, {"binding", "launch", "paths", "cloud_rule", "complete"}, "fixture")
    b = _object(root["binding"], {
        "kind", "unit_id", "game_ids", "emulator", "emulator_version",
        "native_format", "format_version", "data_kind",
    }, "binding")
    binding = SaveBinding(
        SaveUnitKind(b["kind"]), b["unit_id"], _tuple(b["game_ids"], 64, "game IDs"),
        b["emulator"], b["emulator_version"], b["native_format"],
        b["format_version"], SaveDataKind(b["data_kind"]),
    )
    launch = LaunchIdentity(**_object(root["launch"], {
        "source", "provenance", "shortcut_app_id", "emulator_app_id", "carrier_app_id",
    }, "launch"))
    p = _object(root["paths"], {
        "configured", "canonical_target", "symlink_targets", "resolved", "confined",
    }, "paths")
    paths = SavePathEvidence(
        p["configured"], p["canonical_target"],
        _tuple(p["symlink_targets"], 16, "symlink targets"), p["resolved"], p["confined"],
    )
    cloud = CloudRuleEvidence(**_object(root["cloud_rule"], {
        "source", "capture_sha256", "platform", "root", "pattern", "recursive",
        "quota_bytes", "matches_save_unit",
    }, "cloud rule"))
    manifest = build_save_manifest(binding, files, complete=root["complete"])
    return EmulatorSaveInventory(binding, launch, paths, cloud, manifest)
