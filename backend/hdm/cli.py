"""Read-only Re-Gear diagnostics command-line interface."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .api import DiagnosticsApi


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        prog="hdm-diagnose",
        description="Collect a privacy-safe, read-only Re-Gear state snapshot.",
    )
    value.add_argument(
        "--compact",
        action="store_true",
        help="emit compact JSON instead of indented JSON",
    )
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    payload = DiagnosticsApi().get_snapshot()
    print(
        json.dumps(
            payload,
            indent=None if args.compact else 2,
            separators=(",", ":") if args.compact else None,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
