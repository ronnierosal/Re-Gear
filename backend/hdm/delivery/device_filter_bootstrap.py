"""Immutable runtime entry; no install, arm mutation, or native fallback.

Deployment must independently verify the OS session script resolves Gamescope
through the preserved root shim. Hash equality alone does not prove resolution.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import zipfile

ROOT = "/var/lib/regear/filter-runtime"
MAX_RUNTIME_BYTES = 16 * 1024 * 1024
SESSION = "/usr/lib/steamos/gamescope-session"


def runtime_identity(path):
    if type(path) is not str:
        raise ValueError("fixed runtime path required")
    match = re.fullmatch(re.escape(ROOT) + r"/([0-9a-f]{64})/runtime\.pyz", path)
    if match is None:
        raise ValueError("invalid immutable runtime path")
    return match.group(1)


def manifest_from_bytes(raw, expected_hash):
    if (type(raw) is not bytes or not 0 < len(raw) <= MAX_RUNTIME_BYTES
            or type(expected_hash) is not str or hashlib.sha256(raw).hexdigest() != expected_hash):
        raise ValueError("runtime archive changed")
    def unique(items):
        value = {}
        for key, item in items:
            if key in value: raise ValueError("duplicate runtime manifest field")
            value[key] = item
        return value
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        matches = [info for info in infos if info.filename == "manifest.json"]
        if len(infos) > 2048 or len(matches) != 1 or matches[0].file_size > 4096:
            raise ValueError("runtime manifest unavailable")
        with archive.open(matches[0]) as source:
            value = json.loads(source.read(4097).decode("ascii"), object_pairs_hook=unique)
    if (type(value) is not dict or set(value) != {"schema", "session_sha256"}
            or type(value["schema"]) is not int or value["schema"] != 1
            or type(value["session_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", value["session_sha256"]) is None):
        raise ValueError("invalid runtime manifest")
    return value


def _read_root_file(path, limit, *, executable=False):
    parts = path.split("/")
    if parts[0] != "" or any(part in ("", ".", "..") for part in parts[1:]):
        raise ValueError("invalid fixed file path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open("/", flags)
    descriptor = None
    try:
        for index, part in enumerate(parts[1:], 1):
            info = os.fstat(directory)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError("untrusted runtime ancestor")
            if index == len(parts) - 1:
                descriptor = os.open(part, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                break
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
                or info.st_nlink != 1 or not 0 < info.st_size <= limit
                or (executable and info.st_mode & 0o005 != 0o005)):
            raise ValueError("untrusted runtime file")
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(descriptor, limit + 1 - len(data))
            if not chunk: break
            data.extend(chunk)
        if len(data) > limit: raise ValueError("runtime file exceeds bound")
        return bytes(data)
    finally:
        if descriptor is not None: os.close(descriptor)
        os.close(directory)


def shim_bytes(archive_path):
    runtime_identity(archive_path)
    return ("#!/bin/sh\nexec /usr/bin/python3 -I " + archive_path + ' gamescope "$@"\n').encode("ascii")


def main():
    try:
        if sys.platform != "linux" or not sys.flags.isolated or len(sys.argv) < 2:
            raise ValueError("isolated Linux runtime required")
        archive_path, role, *arguments = sys.argv
        digest = runtime_identity(archive_path)
        manifest = manifest_from_bytes(_read_root_file(archive_path, MAX_RUNTIME_BYTES), digest)
        if role not in ("session", "steam", "gamescope") or (role != "gamescope" and arguments):
            raise ValueError("invalid fixed runtime role")
        if role == "session":
            from .device_filter_wrapper import latch_filter_arm
            arm = latch_filter_arm("gamescope-session.service")
            if arm is not None:
                # Preparation must precede native FIFO/helpers and their startup
                # timeout. This entry has no authority to execute an armed session.
                try:
                    from .device_filter_session_withhold import withhold_session_entry
                    from .gamescope_wrapper import _boot_identity, _load_config
                    environment = dict(os.environ)
                    root = Path(environment.get("HDM_STATE_ROOT", ""))
                    if not root.is_absolute() or ".." in root.parts:
                        raise ValueError("absolute session state root required")
                    boot, _ = _boot_identity()
                    config = _load_config(root)
                    withhold_session_entry(arm, state_root=root, raw_boot_id=boot,
                                           environment=environment, candidate_config=config)
                except Exception:
                    return 78
                # Even an unexpected helper return cannot authorize native exec.
                return 78
            # Preserve native session setup and native Gamescope's capability
            # exec path; root shim source must remain exact and independently
            # preserved while any arm/journal/recovery references this runtime.
            binary_directory = archive_path.rsplit("/", 1)[0] + "/bin"
            if _read_root_file(binary_directory + "/gamescope", 4096, executable=True) != shim_bytes(archive_path):
                raise ValueError("stable Gamescope shim changed")
            if hashlib.sha256(_read_root_file(SESSION, 1024 * 1024, executable=True)).hexdigest() != manifest["session_sha256"]:
                raise ValueError("OS session script changed")
            environment = dict(os.environ)
            environment["PATH"] = binary_directory + ":/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin"
            os.execve(SESSION, (SESSION,), environment)
            return 127
        sys.argv = [role, *arguments]
        if role == "gamescope":
            from .gamescope_wrapper import main as launch
        else:
            from .steam_trial_wrapper import main as launch
        return launch()
    except (OSError, ValueError, TypeError, KeyError, ImportError, SyntaxError, zipfile.BadZipFile):
        return 78
