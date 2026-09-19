"""Offline settings backup. Stop the plugin before backup OR restore.

No device operations. Backups must be new directories; restores require an absent
path. Checksums detect corruption, not malicious replacement of an entire backup.
On POSIX private backup permissions are enforced; Windows inherits parent ACLs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile

MAX_FILES = 4096
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024


def _safe_path(value):
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or any(ord(c) < 32 for c in value) or value.startswith("/")):
        raise ValueError("Unsafe relative path")
    parts = value.split("/")
    if any(p in ("", ".", "..") or p.endswith((".", " ")) for p in parts):
        raise ValueError("Unsafe relative path")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
    if any(p.split(".")[0].upper() in reserved for p in parts):
        raise ValueError("Unsafe relative path")
    return PurePosixPath(value)


def _checked(path):
    path = Path(os.path.abspath(path))
    for item in reversed((path, *path.parents)):
        if item.is_symlink():
            raise ValueError("Symlinks are not allowed")
        if item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("Reparse points are not allowed")
    return path


def _read(path, limit):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError("Not a bounded regular file")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(fd, "rb") as stream:
        current = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
            raise ValueError("File changed while reading")
        data = stream.read(limit + 1)
    if len(data) > limit or len(data) != before.st_size:
        raise ValueError("File changed or exceeds size limit")
    return data


def _inventory(root):
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise ValueError("Expected a directory")
    result = []
    pending = [root]
    while pending:
        directory = pending.pop()
        for item in sorted(directory.iterdir()):
            info = item.lstat()
            if item.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Symlinks and reparse points are not allowed")
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise ValueError("Special files are not allowed")
            relative = item.relative_to(root).as_posix()
            _safe_path(relative)
            result.append((relative, item, info))
            if len(result) > MAX_FILES:
                raise ValueError("Too many entries")
            if stat.S_ISDIR(info.st_mode):
                pending.append(item)
    if len({name.casefold() for name, _, _ in result}) != len(result):
        raise ValueError("Case-colliding paths")
    return result


def _metadata(info):
    mode = stat.S_IMODE(info.st_mode)
    if mode & ~0o777:
        raise ValueError("Special permission bits are not allowed")
    return {"mode": mode, "uid": info.st_uid, "gid": info.st_gid}


def _write(path, data):
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def backup(source, destination):
    source, destination = _checked(source), _checked(destination)
    if source == destination or source in destination.parents:
        raise ValueError("Backup must be outside source")
    entries = _inventory(source)
    root_meta = _metadata(source.stat())
    destination.mkdir(mode=0o700)  # Exclusive, never overwrite a backup.
    os.chmod(destination, 0o700)
    payload = destination / "files"
    payload.mkdir(mode=0o700)
    records, total = [], 0
    for relative, original, info in sorted(entries, key=lambda e: (e[0].count("/"), e[0])):
        record = {"path": relative, **_metadata(info)}
        target = payload / relative
        if stat.S_ISDIR(info.st_mode):
            target.mkdir(mode=0o700)
            record["kind"] = "directory"
        else:
            data = _read(original, MAX_FILE_BYTES)
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise ValueError("Backup exceeds total size limit")
            _write(target, data)
            record.update(kind="file", size=len(data), sha256=hashlib.sha256(data).hexdigest())
        records.append(record)
    manifest = json.dumps({"schema": 1, "root": root_meta, "entries": records},
                          sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(manifest) > MAX_MANIFEST_BYTES:
        raise ValueError("Manifest too large")
    _write(destination / "manifest.json", manifest)
    _write(destination / "manifest.sha256", hashlib.sha256(manifest).hexdigest().encode("ascii"))
    return verify(destination)


def _valid_metadata(record):
    for field in ("mode", "uid", "gid"):
        if type(record.get(field)) is not int or record[field] < 0:
            raise ValueError("Invalid metadata")
    if record["mode"] > 0o777 or max(record["uid"], record["gid"]) > 2**32 - 2:
        raise ValueError("Invalid metadata")


def verify(directory):
    directory = _checked(directory)
    if {p.name for p in directory.iterdir()} != {"files", "manifest.json", "manifest.sha256"}:
        raise ValueError("Incomplete or unexpected backup content")
    raw = _read(directory / "manifest.json", MAX_MANIFEST_BYTES)
    digest = _read(directory / "manifest.sha256", 64)
    if hashlib.sha256(raw).hexdigest().encode("ascii") != digest:
        raise ValueError("Manifest checksum mismatch")
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise ValueError("Unsupported manifest")
    _valid_metadata(manifest["root"])
    entries = manifest.get("entries")
    if not isinstance(entries, list) or len(entries) > MAX_FILES:
        raise ValueError("Invalid entry list")
    actual = {relative: info for relative, _, info in _inventory(directory / "files")}
    expected, folded, total = set(), set(), 0
    for record in entries:
        if not isinstance(record, dict):
            raise ValueError("Invalid entry")
        relative = str(_safe_path(record.get("path")))
        if relative.casefold() in folded:
            raise ValueError("Duplicate path")
        expected.add(relative)
        folded.add(relative.casefold())
        _valid_metadata(record)
        info = actual.get(relative)
        if info is None:
            raise ValueError("Missing entry")
        if record.get("kind") == "directory":
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("Directory type mismatch")
        elif record.get("kind") == "file":
            data = _read(directory / "files" / relative, MAX_FILE_BYTES)
            total += len(data)
            if (type(record.get("size")) is not int or record["size"] != len(data)
                    or record.get("sha256") != hashlib.sha256(data).hexdigest()):
                raise ValueError("File checksum or size mismatch")
        else:
            raise ValueError("Unknown entry kind")
    if expected != set(actual) or total > MAX_TOTAL_BYTES:
        raise ValueError("Unexpected entries or size limit exceeded")
    return manifest


def _restore_metadata(path, record):
    if os.name == "posix":
        info = path.stat()
        if (info.st_uid, info.st_gid) != (record["uid"], record["gid"]):
            os.chown(path, record["uid"], record["gid"])
        os.chmod(path, record["mode"])


def restore(directory, destination):
    directory, destination = _checked(directory), _checked(destination)
    manifest = verify(directory)  # Validate everything before destination creation.
    if destination.exists():
        raise FileExistsError(destination)
    if directory == destination or directory in destination.parents:
        raise ValueError("Restore must be outside backup")
    stage = Path(tempfile.mkdtemp(prefix=".regear-restore-", dir=destination.parent))
    published = False
    try:
        records = sorted(manifest["entries"], key=lambda r: (r["path"].count("/"), r["path"]))
        for record in records:
            target = stage / record["path"]
            if record["kind"] == "directory":
                target.mkdir(mode=0o700)
            else:
                data = _read(directory / "files" / record["path"], MAX_FILE_BYTES)
                if hashlib.sha256(data).hexdigest() != record["sha256"]:
                    raise ValueError("Backup changed during restore")
                _write(target, data)
                _restore_metadata(target, record)
        for record in reversed(records):
            if record["kind"] == "directory":
                _restore_metadata(stage / record["path"], record)
        if os.name == "nt":
            # Windows rename refuses existing targets and publishes atomically.
            stage.rename(destination)
            return
        # Portable exclusive reservation: never let POSIX rename replace an empty
        # existing destination. Publication is not atomic; keep the plugin stopped.
        destination.mkdir(mode=0o700)
        published = True
        for child in stage.iterdir():
            child.rename(destination / child.name)
        _restore_metadata(destination, manifest["root"])
    except BaseException:
        if published:
            shutil.rmtree(destination)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command, first, second in [("backup", "source", "backup"), ("restore", "backup", "destination")]:
        item = sub.add_parser(command, help="Stop the plugin before running")
        item.add_argument(first)
        item.add_argument(second)
    sub.add_parser("verify").add_argument("backup")
    args = parser.parse_args()
    if args.command == "backup":
        backup(args.source, args.backup)
    elif args.command == "restore":
        restore(args.backup, args.destination)
    else:
        verify(args.backup)
    print(f"{args.command}: verified successfully")


if __name__ == "__main__":
    main()
