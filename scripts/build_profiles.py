"""Build-profile identity, separate from runtime authority or GA acceptance.

Production selection is reserved but cannot yet package: UI, RPC and automatic
entry points do not consume a stable feature allowlist. A manifest edit alone
must never turn the current development runtime into a production package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROFILE_FILENAME = "build_profile.json"
PROFILE_NAMES = ("development", "production")
POLICIES = {
    "development": "existing_development_surface",
    "production": "stable_allowlist",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_contract(root: Path = ROOT) -> dict[str, Any]:
    """Read the shared profile names/policies without granting runtime access."""
    try:
        contract = json.loads((root / "contracts/build-profiles.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError("release.profile_contract_invalid") from error
    if (
        not isinstance(contract, dict)
        or set(contract) != {"schema_version", "profiles"}
        or type(contract["schema_version"]) is not int
        or contract["schema_version"] != 1
        or contract["profiles"] != {
            name: {"feature_policy": policy} for name, policy in POLICIES.items()
        }
    ):
        raise ValueError("release.profile_contract_invalid")
    return contract


def package_profile(profile: str = "development", *, root: Path = ROOT) -> dict[str, Any]:
    """Resolve package identity; keep the existing development behavior intact."""
    contract = load_contract(root)
    if profile not in PROFILE_NAMES:
        raise ValueError("release.profile_unknown")
    if profile == "production":
        raise ValueError("release.production_runtime_enforcement_pending")
    return {
        "schema_version": 1,
        "profile": profile,
        "feature_policy": contract["profiles"][profile]["feature_policy"],
        "contract_sha256": hashlib.sha256(canonical_bytes(contract)).hexdigest(),
    }


def validate_packaged_profile(value: Any, *, root: Path = ROOT) -> dict[str, Any]:
    """Require explicit, current package identity; never infer production."""
    if not isinstance(value, dict) or not isinstance(value.get("profile"), str):
        raise ValueError("release.archive_profile_invalid")
    expected = package_profile(value["profile"], root=root)
    if type(value.get("schema_version")) is not int or value != expected:
        raise ValueError("release.archive_profile_inconsistent")
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILE_NAMES, default="development")
    args = parser.parse_args()
    try:
        result = package_profile(args.profile)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
