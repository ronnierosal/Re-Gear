"""Pure deterministic runtime archive builder; no installation or authority."""
from dataclasses import dataclass
import hashlib
import io
import json
import re
from collections.abc import Mapping
import zipfile

MAX_SOURCE_BYTES = 16 * 1024 * 1024
_REQUIRED = frozenset("hdm/delivery/" + name for name in (
    "device_filter_bootstrap.py", "gamescope_wrapper.py", "steam_trial_wrapper.py",
    "device_filter_wrapper.py")) | {"hdm/__init__.py", "hdm/delivery/__init__.py"}
_MAIN = b"from hdm.delivery.device_filter_bootstrap import main\nraise SystemExit(main())\n"


@dataclass(frozen=True)
class RuntimeBundle:
    archive: bytes
    digest: str
    path: str
    gamescope_shim: bytes
    steam_argv: tuple[str, ...]
    session_argv: tuple[str, ...]


def build_runtime_bundle(sources: Mapping[str, bytes], *, session_sha256: str) -> RuntimeBundle:
    """Caller supplies audited source closure and exact verified OS session hash.

    Inclusion is not dependency, syntax, hash-lineage or runtime validation.
    Archive digest is content identity, never authentication by itself.
    """
    if type(session_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", session_sha256) is None:
        raise ValueError("verified session SHA-256 required")
    if not isinstance(sources, Mapping) or not 1 <= len(sources) <= 2046:
        raise ValueError("bounded source mapping required")
    entries = {}
    total = 0
    for name, raw in sources.items():
        if (type(name) is not str or len(name) > 240
                or re.fullmatch(r"hdm/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*\.py", name) is None
                or name in entries or type(raw) is not bytes):
            raise ValueError("invalid runtime source entry")
        total += len(raw)
        if total > MAX_SOURCE_BYTES or len(entries) >= 2046:
            raise ValueError("runtime sources exceed bound")
        entries[name] = raw
    if not _REQUIRED <= entries.keys():
        raise ValueError("runtime source closure missing required wrappers")
    entries["__main__.py"] = _MAIN
    entries["manifest.json"] = json.dumps(
        {"schema": 1, "session_sha256": session_sha256},
        sort_keys=True, separators=(",", ":")).encode("ascii")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, raw in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    result = buffer.getvalue()
    if len(result) > MAX_SOURCE_BYTES:
        raise ValueError("serialized runtime archive exceeds bound")
    digest = hashlib.sha256(result).hexdigest()
    path = f"/var/lib/regear/filter-runtime/{digest}/runtime.pyz"
    shim = f'#!/bin/sh\nexec /usr/bin/python3 -I {path} gamescope "$@"\n'.encode("ascii")
    return RuntimeBundle(result, digest, path, shim,
                         ("/usr/bin/python3", "-I", path, "steam"),
                         ("/usr/bin/python3", "-I", path, "session"))
