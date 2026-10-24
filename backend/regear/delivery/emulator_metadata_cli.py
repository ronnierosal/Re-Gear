"""Unregistered source CLI. Metadata-only evidence, never coverage/readiness PASS."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from ..adapters.emulator_metadata_capture import (
    MetadataInput, capture_metadata, inventory_from_fixture, read_metadata_file,
)
from ..domain.emulator_metadata_inventory import MAX_FILES, MAX_ROOTS, CaptureResult, MetadataError, Reason, Role


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        # argparse's default message echoes unrecognized arguments and private paths.
        raise MetadataError(Reason.INVALID_INPUT)


def parser() -> argparse.ArgumentParser:
    value = _Parser(prog="emulator-metadata", description="Explicit, read-only emulator metadata inventory; no save reads or sync.")
    mode = value.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture", metavar="FILE", help="bounded synthetic JSON fixture")
    mode.add_argument("--capture", action="store_true", help="explicit local metadata reads; unsupported safe-open platforms defer")
    value.add_argument("--root", action="append", default=[], metavar="ROOT", help="explicit approved metadata root; no defaults")
    value.add_argument("--metadata", action="append", default=[], metavar="ROLE=FILE", help="selected allowlisted metadata input")
    value.add_argument("--save-root", action="append", default=[], metavar="PATH", help="lstat/readlink facts only; no target opens")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        if len(args.root) > MAX_ROOTS or len(args.metadata) > MAX_FILES or len(args.save_root) > MAX_ROOTS:
            raise MetadataError(Reason.LIMIT_EXCEEDED)
        if args.fixture:
            if args.metadata or args.save_root:
                raise MetadataError()
            data = read_metadata_file(MetadataInput(Role.FIXTURE, args.fixture), tuple(args.root))
            result = inventory_from_fixture(data)
        else:
            inputs = []
            for item in args.metadata:
                role_name, separator, path = item.partition("=")
                if not separator:
                    raise MetadataError()
                try:
                    role = Role(role_name)
                except ValueError:
                    role = None
                if role is None:
                    raise MetadataError()
                inputs.append(MetadataInput(role, path))
            result = capture_metadata(tuple(args.root), tuple(inputs), tuple(args.save_root))
    except MetadataError as error:
        result = CaptureResult(failure=error.reason)
    print(json.dumps(result.public_summary(), sort_keys=True))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
