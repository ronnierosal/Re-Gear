"""Compare two previously validated, read-only Re-Gear wake-diagnostic captures.

This utility never opens SSH, changes the Ally, or names a PCI function. It
reports only whether the documented aggregate wake evidence changed between two
captured observations. A difference is not a causal wake-source conclusion and
does not change Re-Gear's disconnect-before-sleep policy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import remote_capture


# Kept as a public alias for callers of the established wake-comparison helper.
load_capture = remote_capture.load_saved_capture


def compare_wake_diagnostics(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, object]:
    """Return a bounded, identity-free aggregate comparison.

    The caller must provide already validated capture objects. Missing or
    inapplicable evidence remains inconclusive rather than resembling a stable
    wake configuration.
    """
    baseline = before.get("wake_diagnostics")
    current = after.get("wake_diagnostics")
    if not isinstance(baseline, dict):
        return {"state": "inconclusive", "reason": "wake.before_unavailable"}
    if not isinstance(current, dict):
        return {"state": "inconclusive", "reason": "wake.after_unavailable"}
    if baseline.get("applicable") is not True or current.get("applicable") is not True:
        return {"state": "inconclusive", "reason": "wake.topology_unverified"}

    changed: list[str] = []
    if baseline["bridge_wakeup"] != current["bridge_wakeup"]:
        changed.append("wake.bridge_capability_changed")
    for group, fields in (
        ("function_wakeup", ("enabled", "disabled", "unknown")),
        ("function_runtime", ("active", "suspended", "unknown")),
    ):
        for field in fields:
            if baseline[group][field] != current[group][field]:
                changed.append(f"wake.{group}_{field}_count_changed")
    return {
        "state": "changed" if changed else "unchanged",
        "reason": "wake.aggregate_changed" if changed else "wake.aggregate_unchanged",
        "changes": changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path, help="earlier saved remote capture")
    parser.add_argument("after", type=Path, help="later saved remote capture")
    args = parser.parse_args()
    try:
        result = compare_wake_diagnostics(
            load_capture(args.before),
            load_capture(args.after),
        )
    except (OSError, ValueError) as error:
        print(f"Wake comparison failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
