"""Read the bounded build identity generated inside a Decky archive."""

from __future__ import annotations

import json
import re
from pathlib import Path


BUILD_INFO_FILENAME = "build_info.json"
BUILD_SCHEMA_VERSION = 1
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^[0-9A-Za-z.+-]{1,32}$")


def load_public_build_info(
    plugin_root: Path,
    *,
    fallback_version: str = "0.3.65",
) -> dict[str, object]:
    """Return a small public provenance label without reading Git at runtime.

    The build script writes this one static file into the archive. Missing or
    invalid metadata remains explicitly unavailable rather than inheriting a
    checkout revision that may not match installed files.
    """
    fallback = {
        "schema_version": BUILD_SCHEMA_VERSION,
        "version": fallback_version if VERSION_RE.fullmatch(fallback_version) else "unknown",
        "revision": "unavailable",
    }
    try:
        value = json.loads((plugin_root / BUILD_INFO_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback
    if not isinstance(value, dict) or value.get("schema_version") != BUILD_SCHEMA_VERSION:
        return fallback
    version = value.get("version")
    revision = value.get("revision")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        return fallback
    if revision in {"uncommitted", "unavailable"}:
        public_revision = revision
    elif isinstance(revision, str) and REVISION_RE.fullmatch(revision):
        public_revision = revision[:12]
    else:
        return fallback
    return {
        "schema_version": BUILD_SCHEMA_VERSION,
        "version": version,
        "revision": public_revision,
    }
