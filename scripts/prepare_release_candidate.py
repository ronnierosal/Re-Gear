"""Create a local-only, manually publishable HDM release-candidate record."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIRECTORY = "HandheldDockMode"
NUMERIC_IDENTIFIER = r"(?:0|[1-9]\d*)"
PRERELEASE_IDENTIFIER = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
SEMVER_RE = re.compile(
    rf"^{NUMERIC_IDENTIFIER}\.{NUMERIC_IDENTIFIER}\.{NUMERIC_IDENTIFIER}"
    rf"(?:-{PRERELEASE_IDENTIFIER}(?:\.{PRERELEASE_IDENTIFIER})*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _project_version(root: Path) -> str:
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    version = package.get("version")
    if not isinstance(version, str) or not SEMVER_RE.fullmatch(version):
        raise ValueError("release.version_invalid")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', pyproject, re.MULTILINE)
    if match is None or match.group(1) != version:
        raise ValueError("release.version_inconsistent")
    return version


def prepare_release_candidate(archive: Path, *, project_root: Path = ROOT) -> dict[str, Any]:
    """Return fixed metadata needed for a separately manual publication."""
    version = _project_version(project_root)
    if not archive.is_file() or archive.name != f"Re-Gear-{version}.zip":
        raise ValueError("release.archive_name_invalid")
    try:
        with zipfile.ZipFile(archive) as value:
            build = json.loads(value.read(f"{PLUGIN_DIRECTORY}/build_info.json").decode("utf-8"))
            package = json.loads(value.read(f"{PLUGIN_DIRECTORY}/package.json").decode("utf-8"))
    except (OSError, KeyError, UnicodeDecodeError, ValueError, zipfile.BadZipFile) as error:
        raise ValueError("release.archive_metadata_invalid") from error
    if (not isinstance(build, dict) or build.get("schema_version") != 1
            or build.get("version") != version or not isinstance(build.get("revision"), str)
            or not REVISION_RE.fullmatch(build["revision"]) or not isinstance(package, dict)
            or package.get("version") != version):
        raise ValueError("release.archive_build_inconsistent")
    return {
        "schema_version": 1, "version": version,
        "build": {"source_revision": build["revision"]},
        "archive": {"filename": archive.name, "sha256": _sha256(archive)},
        "release_notes": {
            "summary": "REQUIRED: describe player-visible changes.",
            "known_limitations": "REQUIRED: retain all unmet hardware gates.",
            "validation": "REQUIRED: record exact checks and evidence status.",
        },
        "publication": {"status": "manual_publication_required", "github_release": "not_published", "decky_channel": "not_registered"},
    }


def _notes_template(candidate: dict[str, Any]) -> str:
    archive, build = candidate["archive"], candidate["build"]
    return "\n".join((
        f"# Re-Gear {candidate['version']} release notes", "",
        f"- Build revision: `{build['source_revision']}`",
        f"- Archive: `{archive['filename']}`", f"- SHA-256: `{archive['sha256']}`",
        "- Status: `Hardware Validation Required` unless separately evidenced.", "",
        "## Player-visible changes", "", "TODO", "", "## Known limitations and safety gates", "", "TODO", "",
        "## Verification evidence", "", "TODO", "", "## Manual publication record", "",
        "TODO: record the GitHub Release URL and Decky channel decision.", "",
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--notes-template", type=Path, required=True)
    args = parser.parse_args()
    try:
        candidate = prepare_release_candidate(args.archive.resolve())
    except ValueError as error:
        print(str(error))
        return 1
    args.output.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.notes_template.write_text(_notes_template(candidate), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
