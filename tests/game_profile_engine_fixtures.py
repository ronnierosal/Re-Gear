"""Synthetic game, library, mapping and profiles for the Game Profile Engine.

Everything is invented. The AppID sits outside every range Steam has issued,
and the config is *shaped* like an Unreal GameUserSettings.ini -- the section
names, sg.* keys and Version key the foundation's research observed -- but it
is not any shipped game's file. The per-quality numbers are this fixture's
declared mapping, not facts about Unreal or any game: a real game needs its
own mapping and evidence.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.graphics_profiles import ManagedKey, ValueKind  # noqa: E402
from regear.domain.graphics_schema import GameSchema  # noqa: E402
from regear.domain.mode_profiles import ExperienceTarget  # noqa: E402
from regear.domain.models import OperatingMode  # noqa: E402
from regear.domain.semantic_profiles import (  # noqa: E402
    GameMapping,
    GameProfileDocument,
    GraphicsSetting,
    ProfileMetadata,
    Quality,
    QualityKey,
    Resolution,
    SemanticProfile,
    UpscalingMode,
    ValidationStatus,
)


APP_ID = "4000000002"
NATIVE_APP_ID = "4000000003"
INSTALL_DIR = "ReGear Fixture Engine Game"
NATIVE_INSTALL_DIR = "ReGear Fixture Native Game"
RELATIVE_DIR = "ReGearFixtureEngineGame/Saved/Config"
CONFIG = "GameUserSettings.ini"
GAME_BUILD = "fixture-build-7"

SECTION = "/Script/Engine.GameUserSettings"
SCALABILITY = "ScalabilityGroups"

#: CRLF on part of the file, a comment, spacing variations and an unrelated
#: section: a round trip must give all of it back.
SAMPLE = (
    "; ReGear synthetic engine-fixture configuration\r\n"
    "[ScalabilityGroups]\r\n"
    "sg.ResolutionQuality=100\r\n"
    "sg.ViewDistanceQuality = 2\r\n"
    "sg.TextureQuality=3\r\n"
    "sg.ShadowQuality=3\r\n"
    "sg.EffectsQuality=3\r\n"
    "\n"
    f"[{SECTION}]\n"
    "ResolutionSizeX=1280\n"
    "ResolutionSizeY=800\n"
    "FrameRateLimit=60\n"
    "bUseVSync=False\n"
    "Version=5\n"
    "\n"
    "[Audio]\n"
    "MasterVolume=0.8\n"
)


def _quality(key: str) -> ManagedKey:
    return ManagedKey(SCALABILITY, key, ValueKind.INTEGER, minimum=0, maximum=3)


LEVELS = {Quality.LOW: "0", Quality.MEDIUM: "1", Quality.HIGH: "2", Quality.EPIC: "3"}

TEXTURE = f"{SCALABILITY}/sg.TextureQuality"
SHADOW = f"{SCALABILITY}/sg.ShadowQuality"
EFFECTS = f"{SCALABILITY}/sg.EffectsQuality"
VIEW = f"{SCALABILITY}/sg.ViewDistanceQuality"
SCALE = f"{SCALABILITY}/sg.ResolutionQuality"
WIDTH = f"{SECTION}/ResolutionSizeX"
HEIGHT = f"{SECTION}/ResolutionSizeY"
FRAME_LIMIT = f"{SECTION}/FrameRateLimit"
VOLUME = "Audio/MasterVolume"


def mapping(adapter_version: int = 1) -> GameMapping:
    """The fixture game's mapping. Volumetrics is deliberately unmapped."""
    return GameMapping(
        mapping_id="regear-fixture-engine-game",
        adapter_version=adapter_version,
        schema_id="fixture-ue-gameusersettings-v5",
        config_filename=CONFIG,
        relative_dir=RELATIVE_DIR,
        quality_keys={
            GraphicsSetting.TEXTURES: QualityKey(_quality("sg.TextureQuality"), LEVELS),
            GraphicsSetting.SHADOWS: QualityKey(_quality("sg.ShadowQuality"), LEVELS),
            GraphicsSetting.EFFECTS: QualityKey(_quality("sg.EffectsQuality"), LEVELS),
            GraphicsSetting.VIEW_DISTANCE: QualityKey(_quality("sg.ViewDistanceQuality"), LEVELS),
        },
        resolution_keys=(
            ManagedKey(SECTION, "ResolutionSizeX", ValueKind.INTEGER, minimum=320, maximum=7680),
            ManagedKey(SECTION, "ResolutionSizeY", ValueKind.INTEGER, minimum=200, maximum=4320),
        ),
        frame_limit_key=ManagedKey(SECTION, "FrameRateLimit", ValueKind.INTEGER, minimum=20, maximum=240),
        upscaling_key=ManagedKey(SCALABILITY, "sg.ResolutionQuality", ValueKind.INTEGER, minimum=25, maximum=100),
        # Render-scale percentages declared for this fixture. A render scale is
        # not a named FSR/DLSS toggle; a real game maps its own upscaler keys.
        upscaling_values={
            UpscalingMode.OFF: "100",
            UpscalingMode.QUALITY: "67",
            UpscalingMode.BALANCED: "58",
            UpscalingMode.PERFORMANCE: "50",
        },
    )


def schema() -> GameSchema:
    keys = mapping().managed_keys()
    return GameSchema(
        schema_id="fixture-ue-gameusersettings-v5",
        version_address=f"{SECTION}/Version",
        supported_versions=("5",),
        required_addresses=tuple(sorted(keys)),
        current_value_validators=keys,
    )


PORTABLE_BALANCED = SemanticProfile(
    graphics={
        GraphicsSetting.TEXTURES: Quality.HIGH,
        GraphicsSetting.SHADOWS: Quality.MEDIUM,
        GraphicsSetting.EFFECTS: Quality.MEDIUM,
        GraphicsSetting.VIEW_DISTANCE: Quality.MEDIUM,
    },
    target_fps=45,
    resolution=Resolution(1280, 800),
    upscaling=UpscalingMode.QUALITY,
    frame_limit=45,
)
TV_BALANCED = SemanticProfile(
    graphics={
        GraphicsSetting.TEXTURES: Quality.HIGH,
        GraphicsSetting.SHADOWS: Quality.HIGH,
        GraphicsSetting.EFFECTS: Quality.HIGH,
        GraphicsSetting.VIEW_DISTANCE: Quality.EPIC,
    },
    target_fps=60,
    resolution=Resolution(1920, 1080),
    upscaling=UpscalingMode.OFF,
    frame_limit=60,
)
#: Asks for volumetrics, which the fixture mapping cannot express.
PORTABLE_QUALITY = SemanticProfile(
    graphics={
        GraphicsSetting.TEXTURES: Quality.EPIC,
        GraphicsSetting.VOLUMETRICS: Quality.HIGH,
    },
    target_fps=40,
    resolution=Resolution(1280, 800),
)


def document(**metadata) -> GameProfileDocument:
    values = dict(
        profile_version=1,
        adapter_version=1,
        tested_game_version=GAME_BUILD,
        validation=ValidationStatus.FIXTURE,
    )
    values.update(metadata)
    return GameProfileDocument(
        steam_app_id=APP_ID,
        mapping_id="regear-fixture-engine-game",
        metadata=ProfileMetadata(**values),
        profiles={
            OperatingMode.PORTABLE: {
                ExperienceTarget.BALANCED: PORTABLE_BALANCED,
                ExperienceTarget.QUALITY: PORTABLE_QUALITY,
            },
            OperatingMode.TV_DOCKED: {ExperienceTarget.BALANCED: TV_BALANCED},
        },
    )


def build_library(root: Path, *, native: bool = False, config: str = SAMPLE) -> tuple[Path, Path]:
    """A fake Steam root with one game. Returns (steam_root, config_path)."""
    app_id = NATIVE_APP_ID if native else APP_ID
    install = NATIVE_INSTALL_DIR if native else INSTALL_DIR
    steam = root / "steam"
    steamapps = steam / "steamapps"
    (steamapps / "common" / install).mkdir(parents=True)
    (steamapps / f"appmanifest_{app_id}.acf").write_text(
        '"AppState"\n{\n'
        f'\t"appid"\t\t"{app_id}"\n'
        f'\t"installdir"\t\t"{install}"\n'
        f'\t"buildid"\t\t"{GAME_BUILD}"\n'
        "}\n",
        encoding="utf-8",
    )
    (steamapps / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{steam}"\n\t}}\n}}\n',
        encoding="utf-8",
    )
    if native:
        directory = steamapps / "common" / install / RELATIVE_DIR
    else:
        directory = (
            steamapps / "compatdata" / app_id / "pfx" / "drive_c" / "users"
            / "steamuser" / "Documents" / RELATIVE_DIR
        )
    directory.mkdir(parents=True)
    path = directory / CONFIG
    # Bytes, not text: universal-newline translation would silently rewrite
    # the CRLF lines on some platforms and hide exactly what tests check.
    path.write_bytes(config.encode("utf-8"))
    return steam, path
