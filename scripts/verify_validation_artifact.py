"""Verify one downloaded HDM CI validation artifact without installing it.

The verifier reads only a directory produced by unzipping the bounded GitHub
Actions artifact. It accepts no URLs, checkout paths, device paths, or archive
member paths from callers and never writes to the handheld or local checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any


SOURCE_REVISION_FILENAME = "source-revision.txt"
CHECKSUM_FILENAME = "SHA256SUMS.txt"
ARCHIVE_RE = re.compile(r"^(?:Re-Gear|HandheldDockMode)-([0-9]+(?:\.[0-9]+){2}(?:[-+][A-Za-z0-9.-]+)?)\.zip$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
REVISION_PREFIX_RE = re.compile(r"^[0-9a-f]{12}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PLUGIN_DIRECTORY = "HandheldDockMode"
BUILD_INFO_NAME = f"{PLUGIN_DIRECTORY}/build_info.json"
PACKAGE_NAME = f"{PLUGIN_DIRECTORY}/package.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_text(path: Path, limit: int = 256) -> str | None:
    try:
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if len(value) > limit:
        return None
    return value


def _single_archive(root: Path) -> tuple[Path | None, str]:
    try:
        candidates = tuple(sorted((*root.glob("Re-Gear-*.zip"), *root.glob("HandheldDockMode-*.zip"))))
    except OSError:
        return None, "artifact.archive_unreadable"
    if len(candidates) != 1 or not candidates[0].is_file():
        return None, "artifact.archive_ambiguous"
    if not ARCHIVE_RE.fullmatch(candidates[0].name):
        return None, "artifact.archive_name_invalid"
    return candidates[0], ""


def _expected_checksum(root: Path, archive_name: str) -> tuple[str | None, str]:
    value = _read_text(root / CHECKSUM_FILENAME)
    if value is None:
        return None, "artifact.checksum_unreadable"
    rows = [line.split() for line in value.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2:
        return None, "artifact.checksum_invalid"
    digest, recorded_path = rows[0]
    if not SHA256_RE.fullmatch(digest) or Path(recorded_path).name != archive_name:
        return None, "artifact.checksum_invalid"
    return digest, ""


def _source_revision(root: Path) -> tuple[str | None, str]:
    value = _read_text(root / SOURCE_REVISION_FILENAME, limit=64)
    revision = value.strip() if value is not None else ""
    if not REVISION_RE.fullmatch(revision):
        return None, "artifact.source_revision_invalid"
    return revision, ""


def _embedded_build(archive: Path, expected_revision: str) -> tuple[str | None, str]:
    try:
        with zipfile.ZipFile(archive) as value:
            names = tuple(value.namelist())
            if not names or {name.split("/", 1)[0] for name in names} != {PLUGIN_DIRECTORY}:
                return None, "artifact.package_layout_invalid"
            build = json.loads(value.read(BUILD_INFO_NAME).decode("utf-8"))
            package = json.loads(value.read(PACKAGE_NAME).decode("utf-8"))
    except (OSError, KeyError, UnicodeDecodeError, ValueError, zipfile.BadZipFile):
        return None, "artifact.package_metadata_invalid"
    if (
        not isinstance(build, dict)
        or set(build) != {"schema_version", "version", "revision"}
        or build.get("schema_version") != 1
        or build.get("revision") != expected_revision
        or not isinstance(package, dict)
        or build.get("version") != package.get("version")
        or not isinstance(build.get("version"), str)
    ):
        return None, "artifact.package_build_inconsistent"
    return build["version"], ""


def verify_validation_artifact(
    root: Path, *, expected_revision_prefix: str | None = None
) -> dict[str, object]:
    """Return a categorical local-only verification result for one artifact folder."""
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        return {"state": "invalid", "reason": "artifact.directory_invalid"}
    if (
        expected_revision_prefix is not None
        and not REVISION_PREFIX_RE.fullmatch(expected_revision_prefix)
    ):
        return {"state": "invalid", "reason": "artifact.expected_revision_invalid"}
    archive, error = _single_archive(root)
    if archive is None:
        return {"state": "invalid", "reason": error}
    revision, error = _source_revision(root)
    if revision is None:
        return {"state": "invalid", "reason": error}
    expected, error = _expected_checksum(root, archive.name)
    if expected is None:
        return {"state": "invalid", "reason": error}
    try:
        if _sha256(archive) != expected:
            return {"state": "invalid", "reason": "artifact.checksum_mismatch"}
    except OSError:
        return {"state": "invalid", "reason": "artifact.archive_unreadable"}
    version, error = _embedded_build(archive, revision)
    if version is None:
        return {"state": "invalid", "reason": error}
    if (
        expected_revision_prefix is not None
        and not revision.startswith(expected_revision_prefix)
    ):
        return {"state": "invalid", "reason": "artifact.expected_revision_mismatch"}
    return {
        "state": "verified",
        "version": version,
        "revision": revision[:12],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_directory", type=Path)
    parser.add_argument(
        "--expected-revision-prefix",
        help="optional 12-character public build revision label to require",
    )
    args = parser.parse_args()
    result = verify_validation_artifact(
        args.artifact_directory,
        expected_revision_prefix=args.expected_revision_prefix,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("state") == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
