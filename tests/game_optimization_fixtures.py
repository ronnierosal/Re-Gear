"""Synthetic catalog entries and service wiring for automatic game optimization.

Built on the Game Profile Engine fixtures: the same invented game, mapping and
schema. The catalog entry below is that fixture document expressed in the
catalog's data-only format, so the engine sees exactly what its own tests do.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

import game_profile_engine_fixtures as fx  # noqa: E402

APP_ID = fx.APP_ID
OTHER_APP_ID = "4000000009"

ENTRY = {
    "catalog_version": 1,
    "steam_app_id": APP_ID,
    "mapping_id": "regear-fixture-engine-game",
    "profile_version": 1,
    "adapter_version": 1,
    "tested_game_version": fx.GAME_BUILD,
    "validation": "fixture",
    "provenance": {"source": "local", "evidence_id": "", "validated_modes": []},
    "profiles": {
        "portable": {
            "balanced": {
                "graphics": {
                    "textures": "high",
                    "shadows": "medium",
                    "effects": "medium",
                    "view_distance": "medium",
                },
                "target_fps": 45,
                "resolution": [1280, 800],
                "upscaling": "quality",
                "frame_limit": 45,
            },
            "quality": {
                "graphics": {"textures": "epic", "volumetrics": "high"},
                "target_fps": 40,
                "resolution": [1280, 800],
            },
        },
        "tv_docked": {
            "balanced": {
                "graphics": {
                    "textures": "high",
                    "shadows": "high",
                    "effects": "high",
                    "view_distance": "epic",
                },
                "target_fps": 60,
                "resolution": [1920, 1080],
                "upscaling": "off",
                "frame_limit": 60,
            }
        },
    },
}


def entry(**changes) -> dict:
    value = copy.deepcopy(ENTRY)
    value.update(changes)
    return value


def write_catalog(directory: Path, *entries: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for item in entries or (ENTRY,):
        (directory / f"{item['steam_app_id']}.json").write_text(
            json.dumps(item), encoding="utf-8"
        )
    return directory
