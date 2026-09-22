"""A fake Steam library and Proton prefix, built in a temporary directory.

Everything the graphics-profile tests touch lives under a directory the test
created and will delete. No test reads or writes a real Steam installation, and
the locator is always handed this root explicitly -- it has no default root to
fall back to.
"""

from __future__ import annotations

from pathlib import Path


PROTON_APP_ID = "620"
NATIVE_APP_ID = "570"
PROTON_INSTALL_DIR = "Portal 2"
NATIVE_INSTALL_DIR = "dota 2 beta"
CONFIG_FILENAME = "graphics.ini"
GAME_CONFIG_DIR = "ReGearTestGame/Config"

#: Shaped on a real Unreal Engine `GameUserSettings.ini` -- the section names,
#: the `sg.*` scalability keys and the `Version` key are the engine's, observed
#: in a published UE4 configuration file (see docs/GRAPHICS_PROFILES_RESEARCH.md).
#: The contents are written here rather than copied, and no shipped game's file
#: has been verified, so this remains a synthetic mechanism demonstration.
#:
#: Deliberately awkward as a document: a comment, blank lines, CRLF on part of
#: the file, spacing that differs per line, a duplicate key, and sections whose
#: keys Re-Gear does not manage. A round trip has to give all of this back.
SAMPLE_CONFIG = (
    "; ReGear synthetic UE-shaped graphics configuration\r\n"
    "\r\n"
    "[ScalabilityGroups]\r\n"
    "sg.ResolutionQuality=100\r\n"
    "sg.ViewDistanceQuality = 3\r\n"
    "sg.AntiAliasingQuality=3\r\n"
    "\n"
    "[/Script/Engine.GameUserSettings]\n"
    "sg.ShadowQuality = 2\n"
    "sg.TextureQuality=3\n"
    "FrameRateLimit= 60\n"
    "# the game writes this twice; the last one wins\n"
    "sg.ShadowQuality = 2\n"
    "bUseVSync=False\n"
    "Version=5\n"
    "\n"
    "[Audio]\n"
    "MasterVolume=0.8\n"
)

#: Addresses in the sample, for tests and for the game adapter.
TEXTURE = "/Script/Engine.GameUserSettings/sg.TextureQuality"
SHADOW = "/Script/Engine.GameUserSettings/sg.ShadowQuality"
FRAME_LIMIT = "/Script/Engine.GameUserSettings/FrameRateLimit"
VERSION_ADDRESS = "/Script/Engine.GameUserSettings/Version"
VIEW_DISTANCE = "ScalabilityGroups/sg.ViewDistanceQuality"
MASTER_VOLUME = "Audio/MasterVolume"

def build_library(root: Path, *, extra_library: Path | None = None) -> Path:
    """Create a Steam root with one Proton game and one native game."""
    steam_root = root / "steam"
    steamapps = steam_root / "steamapps"
    (steamapps / "common" / PROTON_INSTALL_DIR).mkdir(parents=True)
    (steamapps / "common" / NATIVE_INSTALL_DIR).mkdir(parents=True)

    _write_manifest(steamapps, PROTON_APP_ID, PROTON_INSTALL_DIR)
    _write_manifest(steamapps, NATIVE_APP_ID, NATIVE_INSTALL_DIR)

    prefix_documents = (
        steamapps
        / "compatdata"
        / PROTON_APP_ID
        / "pfx"
        / "drive_c"
        / "users"
        / "steamuser"
        / "Documents"
        / GAME_CONFIG_DIR
    )
    prefix_documents.mkdir(parents=True)
    (prefix_documents / CONFIG_FILENAME).write_text(SAMPLE_CONFIG, encoding="utf-8")

    native_config = steamapps / "common" / NATIVE_INSTALL_DIR / GAME_CONFIG_DIR
    native_config.mkdir(parents=True)
    (native_config / CONFIG_FILENAME).write_text(SAMPLE_CONFIG, encoding="utf-8")

    paths = [steam_root]
    if extra_library is not None:
        (extra_library / "steamapps").mkdir(parents=True, exist_ok=True)
        paths.append(extra_library)
    _write_library_folders(steamapps / "libraryfolders.vdf", paths)
    return steam_root


def proton_config_path(steam_root: Path) -> Path:
    return (
        steam_root
        / "steamapps"
        / "compatdata"
        / PROTON_APP_ID
        / "pfx"
        / "drive_c"
        / "users"
        / "steamuser"
        / "Documents"
        / GAME_CONFIG_DIR
        / CONFIG_FILENAME
    )


def native_config_path(steam_root: Path) -> Path:
    return (
        steam_root
        / "steamapps"
        / "common"
        / NATIVE_INSTALL_DIR
        / GAME_CONFIG_DIR
        / CONFIG_FILENAME
    )


def _write_manifest(steamapps: Path, app_id: str, install_dir: str) -> None:
    (steamapps / f"appmanifest_{app_id}.acf").write_text(
        '"AppState"\n'
        "{\n"
        f'\t"appid"\t\t"{app_id}"\n'
        f'\t"name"\t\t"ReGear Test Game {app_id}"\n'
        f'\t"installdir"\t\t"{install_dir}"\n'
        '\t"StateFlags"\t\t"4"\n'
        "}\n",
        encoding="utf-8",
    )


def _write_library_folders(path: Path, paths: list[Path]) -> None:
    entries = "".join(
        "\t\"%d\"\n\t{\n\t\t\"path\"\t\t\"%s\"\n\t\t\"label\"\t\t\"\"\n\t}\n"
        % (index, str(library))
        for index, library in enumerate(paths)
    )
    path.write_text('"libraryfolders"\n{\n' + entries + "}\n", encoding="utf-8")


def sample_schema():
    """The one schema this milestone's adapter is written against."""
    from regear.domain.graphics_profiles import ManagedKey, ValueKind
    from regear.domain.graphics_schema import GameSchema

    validators = {
        TEXTURE: ManagedKey(
            "/Script/Engine.GameUserSettings", "sg.TextureQuality",
            ValueKind.INTEGER, minimum=0, maximum=3,
        ),
        SHADOW: ManagedKey(
            "/Script/Engine.GameUserSettings", "sg.ShadowQuality",
            ValueKind.INTEGER, minimum=0, maximum=3,
        ),
        FRAME_LIMIT: ManagedKey(
            "/Script/Engine.GameUserSettings", "FrameRateLimit",
            ValueKind.INTEGER, minimum=30, maximum=240,
        ),
    }
    return GameSchema(
        schema_id="ue-gameusersettings",
        version_address=VERSION_ADDRESS,
        supported_versions=("5",),
        required_addresses=(TEXTURE, SHADOW, FRAME_LIMIT, VIEW_DISTANCE),
        current_value_validators=validators,
    ), validators


def sample_adapter():
    """A game adapter with declared, not derived, per-mode settings.

    The values below are this fixture's declared choices for a synthetic game.
    They are not measured, benchmarked or claimed to be optimal for any
    hardware, and Boosted Handheld is declared only so the translation path is
    exercised -- not as a performance recommendation.
    """
    from regear.domain.graphics_game_adapter import GameSettingsAdapter
    from regear.domain.mode_profiles import ExperienceTarget

    schema, validators = sample_schema()
    return GameSettingsAdapter(
        adapter_id="regear-test-ue-game",
        steam_app_ids=(PROTON_APP_ID, NATIVE_APP_ID),
        config_filename=CONFIG_FILENAME,
        relative_dir=GAME_CONFIG_DIR,
        schema=schema,
        owned_keys=validators,
        declared_settings={
            ExperienceTarget.BATTERY: {TEXTURE: "1", SHADOW: "0", FRAME_LIMIT: "40"},
            ExperienceTarget.BALANCED: {TEXTURE: "2", SHADOW: "2", FRAME_LIMIT: "60"},
            ExperienceTarget.QUALITY: {TEXTURE: "3", SHADOW: "3", FRAME_LIMIT: "120"},
        },
    )
