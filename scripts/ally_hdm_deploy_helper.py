#!/usr/bin/env python3
"""Root-owned, signature-gated developer installer for one HDM package.

This program is intentionally installed outside the plugin tree.  It never
reloads Decky or touches Gamescope, sleep, displays, or hardware.  Its only
mutation is an atomic replacement of the fixed HDM plugin directory after a
strict archive and signature verification.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


PACKAGE_ROOT = Path("/home/deck")
PLUGIN_PARENT = Path("/home/deck/homebrew/plugins")
PLUGIN_NAME = "HandheldDockMode"
TARGET = PLUGIN_PARENT / PLUGIN_NAME
BACKUPS = PLUGIN_PARENT / ".hdm-deploy-backups"
# SteamOS keeps /usr immutable.  /var/lib/handheld-dock-mode is the existing
# root-owned, mode-0700 HDM runtime authority and survives system updates.
PUBLIC_KEY = Path("/var/lib/handheld-dock-mode/deploy-public-key.pem")
SYSTEMCTL = "/usr/bin/systemctl"
PACKAGE_RE = re.compile(r"HDM-update-([0-9]+(?:\.[0-9]+){2}(?:[-+][A-Za-z0-9.-]+)?)-([0-9a-f]{12})\.zip")
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_UNPACKED_BYTES = 96 * 1024 * 1024


class DeploymentError(RuntimeError):
    pass


def fixed_download(name: str, suffix: str) -> Path:
    """Return a no-follow fixed package path, rejecting all caller paths."""
    if Path(name).name != name or not name.endswith(suffix):
        raise DeploymentError("package name is invalid")
    path = PACKAGE_ROOT / name
    try:
        status = path.lstat()
    except FileNotFoundError as error:
        raise DeploymentError("staged package is unavailable") from error
    if not path.is_file() or path.is_symlink() or status.st_size <= 0:
        raise DeploymentError("staged package is invalid")
    return path


def verify_signature(package: Path, signature: Path) -> None:
    if not PUBLIC_KEY.is_file() or PUBLIC_KEY.is_symlink():
        raise DeploymentError("deployment verification key is unavailable")
    result = subprocess.run(
        ["/usr/bin/openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(PUBLIC_KEY), "-rawin", "-in", str(package), "-sigfile", str(signature)],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise DeploymentError("package signature verification failed")


def validate_and_extract(package: Path, temporary_root: Path, expected_version: str, expected_revision_prefix: str) -> Path:
    if package.stat().st_size > MAX_ARCHIVE_BYTES:
        raise DeploymentError("package size is invalid")
    try:
        with zipfile.ZipFile(package) as archive:
            infos = archive.infolist()
            names = [entry.filename for entry in infos]
            if not infos or len(set(names)) != len(names):
                raise DeploymentError("package layout is invalid")
            total = sum(entry.file_size for entry in infos)
            if total > MAX_UNPACKED_BYTES:
                raise DeploymentError("package size is invalid")
            for entry in infos:
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or ".." in path.parts or path.parts[:1] != (PLUGIN_NAME,):
                    raise DeploymentError("package layout is invalid")
                if entry.is_dir() or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise DeploymentError("package layout is invalid")
            build: Any = json.loads(archive.read(f"{PLUGIN_NAME}/build_info.json"))
            manifest: Any = json.loads(archive.read(f"{PLUGIN_NAME}/package.json"))
            if (
                not isinstance(build, dict)
                or set(build) != {"schema_version", "version", "revision"}
                or build.get("schema_version") != 1
                or build.get("version") != expected_version
                or not isinstance(build.get("revision"), str)
                or not re.fullmatch(r"[0-9a-f]{40}", build["revision"])
                or not build["revision"].startswith(expected_revision_prefix)
                or not isinstance(manifest, dict)
                or manifest.get("version") != expected_version
            ):
                raise DeploymentError("package provenance is invalid")
            extracted = temporary_root / PLUGIN_NAME
            for entry in infos:
                destination = temporary_root.joinpath(*PurePosixPath(entry.filename).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, destination.open("xb") as output:
                    shutil.copyfileobj(source, output, length=64 * 1024)
    except (OSError, KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        raise DeploymentError("package metadata is invalid") from error
    if not (extracted / "plugin.json").is_file() or not (extracted / "main.py").is_file():
        raise DeploymentError("package content is incomplete")
    return extracted


def restart_plugin_loader() -> None:
    """Reload only Decky's plugin service after a completed replacement."""
    for arguments in (("restart", "plugin_loader.service"), ("is-active", "--quiet", "plugin_loader.service")):
        result = subprocess.run(
            [SYSTEMCTL, *arguments],
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
        if result.returncode:
            raise DeploymentError("plugin loader restart could not be verified")


def install(package_name: str, signature_name: str) -> dict[str, str]:
    match = PACKAGE_RE.fullmatch(package_name)
    if match is None or signature_name != f"{package_name}.sig":
        raise DeploymentError("package name is invalid")
    package = fixed_download(package_name, ".zip")
    signature = fixed_download(signature_name, ".sig")
    if signature.stat().st_size > 16 * 1024:
        raise DeploymentError("package signature is invalid")
    verify_signature(package, signature)
    PLUGIN_PARENT.mkdir(mode=0o755, parents=True, exist_ok=True)
    BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".hdm-deploy-", dir=PLUGIN_PARENT) as temporary:
        staged = validate_and_extract(package, Path(temporary), match.group(1), match.group(2))
        # A unique root-owned backup preserves rollback.  Renames stay within
        # one filesystem, so there is no partial target tree.
        backup = BACKUPS / f"{PLUGIN_NAME}-{match.group(1)}-{match.group(2)}"
        if backup.exists():
            raise DeploymentError("backup destination already exists")
        moved_old = False
        try:
            if TARGET.exists():
                os.replace(TARGET, backup)
                moved_old = True
            os.replace(staged, TARGET)
            restart_plugin_loader()
        except OSError as error:
            if moved_old and not TARGET.exists() and backup.exists():
                os.replace(backup, TARGET)
            raise DeploymentError("plugin replacement failed; rollback attempted") from error
        except (DeploymentError, subprocess.SubprocessError) as error:
            # If the replacement reached the loader but the loader did not
            # return healthy, restore the exact old tree and retry only that
            # same fixed service.  Never touch Gamescope or session state.
            failed = BACKUPS / f"{PLUGIN_NAME}-{match.group(1)}-{match.group(2)}.loader-failed"
            if moved_old and TARGET.exists() and backup.exists() and not failed.exists():
                os.replace(TARGET, failed)
                os.replace(backup, TARGET)
                try:
                    restart_plugin_loader()
                except (DeploymentError, subprocess.SubprocessError):
                    pass
            raise DeploymentError("plugin loader restart failed; rollback attempted") from error
    return {"state": "installed", "version": match.group(1), "revision": match.group(2), "backup": str(backup) if moved_old else "none", "loader": "active"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_name")
    parser.add_argument("signature_name")
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.package_name, args.signature_name), sort_keys=True))
        return 0
    except (DeploymentError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"state": "rejected", "reason": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
