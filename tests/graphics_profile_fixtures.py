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

#: Deliberately awkward: a comment, a blank line, CRLF endings on part of the
#: file, spacing that differs per line, a duplicate key, and a section whose
#: keys Re-Gear does not manage. A round trip has to give all of this back.
SAMPLE_CONFIG = (
    "; ReGear test game graphics configuration\r\n"
    "\r\n"
    "[Display]\r\n"
    "ResolutionX=1280\r\n"
    "ResolutionY = 800\r\n"
    "Fullscreen=1\r\n"
    "\n"
    "[Graphics]\n"
    "ShadowQuality = 2\n"
    "TextureQuality=3\n"
    "FrameRateLimit= 60\n"
    "# the game writes this twice; the last one wins\n"
    "ShadowQuality = 2\n"
    "\n"
    "[Audio]\n"
    "MasterVolume=0.8\n"
)


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
