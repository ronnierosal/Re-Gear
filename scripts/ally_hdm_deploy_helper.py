#!/usr/bin/env python3
"""Root-owned, signature-gated developer installer for one HDM package.

This program is intentionally installed outside the plugin tree. It replaces
the fixed plugin directory after archive and signature verification and
restarts only plugin_loader.service. It never touches Gamescope, sleep,
displays, or hardware.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import stat
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


PACKAGE_ROOT = Path("/home/deck")
PLUGIN_PARENT = Path("/home/deck/homebrew/plugins")
PLUGIN_NAME = "Re-Gear"
LEGACY_NAME = "HandheldDockMode"
TARGET = PLUGIN_PARENT / PLUGIN_NAME
BACKUPS = PLUGIN_PARENT / ".hdm-deploy-backups"
# SteamOS keeps /usr immutable.  /var/lib/handheld-dock-mode is the existing
# root-owned, mode-0700 HDM runtime authority and survives system updates.
PUBLIC_KEY = Path("/var/lib/handheld-dock-mode/deploy-public-key.pem")
SYSTEMCTL = "/usr/bin/systemctl"
PACKAGE_RE = re.compile(r"Re-Gear-update-([0-9]+(?:\.[0-9]+){2}(?:[-+][A-Za-z0-9.-]+)?)-([0-9a-f]{12})\.zip")
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


def verify_signature(package: Path, signature: Path, *, pass_fds: tuple[int, ...] = ()) -> None:
    key_parent_fd = open_directory_chain(PUBLIC_KEY.parent)
    try:
        key_fd = os.open(PUBLIC_KEY.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=key_parent_fd)
    finally:
        os.close(key_parent_fd)
    try:
        status = os.fstat(key_fd)
        if not stat.S_ISREG(status.st_mode) or status.st_uid != 0 or status.st_mode & 0o022:
            raise DeploymentError("deployment verification key is unavailable")
        result = subprocess.run(
            ["/usr/bin/openssl", "pkeyutl", "-verify", "-pubin", "-inkey", f"/proc/self/fd/{key_fd}", "-rawin", "-in", str(package), "-sigfile", str(signature)],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
            pass_fds=(*pass_fds, key_fd),
        )
    finally:
        os.close(key_fd)
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
            temporary_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            for entry in infos:
                parts = PurePosixPath(entry.filename).parts
                directory = temporary_root
                for component in parts[:-1]:
                    directory /= component
                    directory.mkdir(mode=0o755, exist_ok=True)
                destination = directory / parts[-1]
                output_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                with os.fdopen(output_fd, "wb") as output, archive.open(entry) as source:
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


def snapshot_download(name: str, destination: Path, limit: int) -> None:
    """Copy bounded input into private storage; an open source inode is mutable.

    O_NONBLOCK prevents a raced FIFO from blocking before fstat rejects it.
    Verification happens only after this copy is closed. Concurrent source edits
    can produce an invalid signature, but cannot change the verified snapshot.
    """
    source_fd = os.open(PACKAGE_ROOT / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(source_fd, "rb") as source:
        status = os.fstat(source.fileno())
        if not stat.S_ISREG(status.st_mode) or not 0 < status.st_size <= limit:
            raise DeploymentError("staged package size or type is invalid")
        with destination.open("xb") as output:
            remaining = limit
            while block := source.read(min(64 * 1024, remaining + 1)):
                remaining -= len(block)
                if remaining < 0:
                    raise DeploymentError("staged package size is invalid")
                output.write(block)


def entry_exists(name: str, directory_fd: int) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def reject_legacy(directory_fd: int) -> None:
    if entry_exists(LEGACY_NAME, directory_fd):
        raise DeploymentError("legacy installation requires supervised cutover; see docs/IDENTITY_CUTOVER.md")


def open_directory_chain(path: Path) -> int:
    """Reject symlinks in every component, retaining each parent while opening."""
    if not path.is_absolute() or ".." in path.parts:
        raise DeploymentError("installation authority path is invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        return directory_fd
    except BaseException:
        os.close(directory_fd)
        raise


def open_private_backups(parent_fd: int) -> int:
    """Pin the authority before using it; never repair attacker-owned storage."""
    try:
        os.mkdir(BACKUPS.name, mode=0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    directory_fd = os.open(BACKUPS.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        status = os.fstat(directory_fd)
        if status.st_uid != 0 or stat.S_IMODE(status.st_mode) != 0o700:
            raise DeploymentError("backup authority must be root-owned mode 0700")
        return directory_fd
    except BaseException:
        os.close(directory_fd)
        raise


def install(package_name: str, signature_name: str) -> dict[str, str]:
    match = PACKAGE_RE.fullmatch(package_name)
    if match is None or signature_name != f"{package_name}.sig":
        raise DeploymentError("package name is invalid")
    legacy = PLUGIN_PARENT / LEGACY_NAME
    if legacy.exists() or legacy.is_symlink():
        raise DeploymentError("legacy installation requires supervised cutover; see docs/IDENTITY_CUTOVER.md")
    # This privileged SteamOS program requires Linux descriptor-relative calls.
    # There is deliberately no path-based compatibility fallback.
    if sys.platform != "linux" or os.geteuid() != 0 or not Path("/proc/self/fd").is_dir():
        raise DeploymentError("installation requires Linux root with procfs")
    parent_fd = open_directory_chain(PLUGIN_PARENT)
    try:
        reject_legacy(parent_fd)
        backup_fd = open_private_backups(parent_fd)
        try:
            import fcntl
            fcntl.flock(backup_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return install_pinned(package_name, signature_name, match, parent_fd, backup_fd)
        finally:
            os.close(backup_fd)
    finally:
        os.close(parent_fd)


def install_pinned(package_name: str, signature_name: str, match: re.Match[str], parent_fd: int, backup_fd: int) -> dict[str, str]:
    # The private directory may be renamed by the plugin-parent owner. Retaining
    # its descriptor keeps snapshots, extraction, cleanup and rollback on the
    # same protected inode. Stage and target remain on the same filesystem.
    stage_name = f".stage-{uuid.uuid4().hex}"
    os.mkdir(stage_name, mode=0o700, dir_fd=backup_fd)
    private = Path(f"/proc/self/fd/{backup_fd}")
    stage = private / stage_name
    backup_name = f"{PLUGIN_NAME}-{match.group(1)}-{match.group(2)}"
    failed_name = backup_name + f".loader-failed-{uuid.uuid4().hex}"
    moved_old = published = False
    try:
        package, signature = stage / "package.zip", stage / "package.sig"
        snapshot_download(package_name, package, MAX_ARCHIVE_BYTES)
        snapshot_download(signature_name, signature, 16 * 1024)
        verify_signature(package, signature, pass_fds=(backup_fd,))
        validate_and_extract(package, stage, match.group(1), match.group(2))
        if entry_exists(backup_name, backup_fd):
            raise DeploymentError("backup destination already exists")
        reject_legacy(parent_fd)
        try:
            if entry_exists(PLUGIN_NAME, parent_fd):
                target_status = os.stat(PLUGIN_NAME, dir_fd=parent_fd, follow_symlinks=False)
                if not stat.S_ISDIR(target_status.st_mode):
                    raise DeploymentError("existing plugin must be a directory")
                os.replace(PLUGIN_NAME, backup_name, src_dir_fd=parent_fd, dst_dir_fd=backup_fd)
                moved_old = True
            os.replace(f"{stage_name}/{PLUGIN_NAME}", PLUGIN_NAME, src_dir_fd=backup_fd, dst_dir_fd=parent_fd)
            published = True
            restart_plugin_loader()
        except (OSError, DeploymentError, subprocess.SubprocessError) as error:
            # Keep failed content for inspection without following any swapped
            # target link. Restore the actual saved entry through pinned fds.
            if moved_old or published:
                if entry_exists(PLUGIN_NAME, parent_fd):
                    os.replace(PLUGIN_NAME, failed_name, src_dir_fd=parent_fd, dst_dir_fd=backup_fd)
                if moved_old:
                    os.replace(backup_name, PLUGIN_NAME, src_dir_fd=backup_fd, dst_dir_fd=parent_fd)
                if published:
                    try:
                        restart_plugin_loader()
                    except (OSError, DeploymentError, subprocess.SubprocessError):
                        pass
            message = "plugin loader restart failed; rollback attempted" if published else "plugin replacement failed; rollback attempted"
            raise DeploymentError(message) from error
    finally:
        shutil.rmtree(stage)
    return {"state": "installed", "version": match.group(1), "revision": match.group(2), "backup": str(BACKUPS / backup_name) if moved_old else "none", "loader": "active"}


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
