"""Validate and execute golden behavior contracts without freezing implementation."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"[a-z][a-z0-9_-]*\Z")
TEST_ID = re.compile(
    r"(?:tests\.)?test_[A-Za-z0-9_]+\.[A-Za-z_]\w*\.test_[A-Za-z0-9_]+\Z"
)


class ContractError(ValueError):
    """The contract cannot provide a meaningful regression gate."""


def fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ContractError(f"{label}: expected fields {sorted(expected)}")


def strings(value, label):
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(set(value)) != len(value)
    ):
        raise ContractError(f"{label}: expected unique nonempty strings")
    return value


def safe_path(value, root, *, glob=False):
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
        or ":" in value
        or any(part in ("", ".", "..") for part in value.split("/"))
        or any(ord(char) < 32 for char in value)
    ):
        raise ContractError(f"Unsafe relative path: {value!r}")
    if not glob and any(char in value for char in "*?[]"):
        raise ContractError(f"Evidence must be a file: {value!r}")
    if not (root / value).resolve().is_relative_to(root.resolve()):
        raise ContractError(f"Path escapes repository: {value!r}")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def load_manifest(path, root=ROOT):
    try:
        data = json.loads(
            Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_object
        )
    except (OSError, ValueError) as exc:
        raise ContractError(f"Cannot read manifest: {exc}") from exc
    fields(data, ("schema_version", "baseline", "behaviors"), "manifest")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ContractError("Unsupported schema_version")
    baseline = data["baseline"]
    fields(
        baseline, ("id", "source_revision", "artifact_sha256", "evidence"), "baseline"
    )
    for key, pattern in (
        ("id", re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._/-]*\Z")),
        ("source_revision", re.compile(r"[0-9a-f]{40}\Z")),
        ("artifact_sha256", re.compile(r"[0-9a-f]{64}\Z")),
    ):
        if not isinstance(baseline[key], str) or not pattern.fullmatch(baseline[key]):
            raise ContractError(f"Invalid baseline {key}")
    for evidence in [baseline["evidence"]]:
        safe_path(evidence, root)
        if not (root / evidence).is_file():
            raise ContractError(f"Missing evidence: {evidence}")
    if not isinstance(data["behaviors"], list) or not data["behaviors"]:
        raise ContractError("At least one behavior is required")
    seen = set()
    for behavior in data["behaviors"]:
        fields(
            behavior,
            ("id", "contract", "test_ids", "source_paths", "hardware_cases"),
            "behavior",
        )
        name = behavior["id"]
        if not isinstance(name, str) or not ID.fullmatch(name) or name in seen:
            raise ContractError(f"Invalid or duplicate behavior ID: {name!r}")
        seen.add(name)
        if (
            not isinstance(behavior["contract"], str)
            or not behavior["contract"].strip()
        ):
            raise ContractError(f"{name}: empty contract")
        for test in strings(behavior["test_ids"], f"{name} test_ids"):
            if not TEST_ID.fullmatch(test) or test.removeprefix("tests.").startswith(
                "test_golden_behaviors."
            ):
                raise ContractError(f"Expected concrete unittest method: {test!r}")
        for source in strings(behavior["source_paths"], f"{name} source_paths"):
            safe_path(source, root, glob=True)
            if not any(
                item.is_file()
                for item in root.glob(
                    source + "/*" if source.endswith("/**") else source
                )
            ):
                raise ContractError(f"Source pattern matches no files: {source}")
        cases = behavior["hardware_cases"]
        if cases != []:
            strings(cases, f"{name} hardware_cases")
    return data


def load_tests(manifest, loader=None):
    loader = loader or unittest.TestLoader()
    suite = unittest.TestSuite()
    ids = dict.fromkeys(
        test for item in manifest["behaviors"] for test in item["test_ids"]
    )
    for test_id in ids:
        loaded = loader.loadTestsFromName(test_id)
        leaves = list(flatten(loaded))
        if loader.errors or len(leaves) != 1 or leaves[0].id() != test_id:
            raise ContractError(
                f"Missing or non-concrete test: {test_id}; {loader.errors}"
            )
        suite.addTests(leaves)
    if not suite.countTestCases():
        raise ContractError("Golden test suite is empty")
    return suite


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


def run_tests(suite, stream=None):
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return (
        result.testsRun > 0
        and result.wasSuccessful()
        and not result.skipped
        and not result.expectedFailures
    )


def affected(manifest, base, root=ROOT):
    revision = subprocess.run(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    output = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", "-z", revision, "HEAD", "--"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    paths = output.decode("utf-8").rstrip("\0").split("\0")
    return [
        item["id"]
        for item in manifest["behaviors"]
        if any(
            fnmatch.fnmatchcase(path, pattern)
            for path in paths
            for pattern in item["source_paths"]
        )
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "contracts/golden-behaviors.json"
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--base", help="Report affected contracts; still execute every golden test"
    )
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT / "tests"))
    sys.path.insert(0, str(ROOT))
    try:
        manifest = load_manifest(args.manifest)
        suite = load_tests(manifest)
        print(
            f"Golden contracts: {len(manifest['behaviors'])}; tests: {suite.countTestCases()}"
        )
        if args.base:
            print(
                "Affected behaviors: "
                + (", ".join(affected(manifest, args.base)) or "none")
            )
        if args.validate_only:
            return 0
        if not run_tests(suite):
            print(
                "Golden gate FAILED (failures, errors, skips, expected failures, or empty suite).",
                file=sys.stderr,
            )
            return 1
        print("Golden automated gate passed; hardware cases require separate evidence.")
        return 0
    except (ContractError, subprocess.SubprocessError, OSError) as exc:
        print(f"Golden gate FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
