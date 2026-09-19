#!/usr/bin/env python3
"""Inspect or move Re-Gear state identities while every runtime is offline.

This operator tool never stops or starts a service and performs no session or
hardware action. ``apply`` and ``rollback`` refuse while Decky or Gamescope is
active. The operator must establish that supervised offline state separately.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.delivery.identity_migration import (  # noqa: E402
    IdentityMigration,
    IdentityMigrationError,
    default_moves,
)


JOURNAL = Path("/var/lib/regear/identity-migration-v1.json")
SYSTEMCTL = "/usr/bin/systemctl"
DECK_USER = "deck"


def _plugin_loader_active() -> bool:
    result = subprocess.run(
        [SYSTEMCTL, "is-active", "--quiet", "plugin_loader.service"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    return result.returncode == 0


def _active_processes() -> tuple[str, ...]:
    active: set[str] = set()
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8").strip()
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", "replace"
            )
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        if comm == "gamescope":
            active.add("gamescope")
        if "/home/deck/homebrew/plugins/Re-Gear/" in command:
            active.add("regear_backend")
    return tuple(sorted(active))


def require_offline() -> None:
    if _plugin_loader_active():
        raise IdentityMigrationError("plugin_loader.service must be inactive")
    active = _active_processes()
    if active:
        raise IdentityMigrationError("runtime processes must be stopped: " + ",".join(active))


def build_migration() -> IdentityMigration:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise IdentityMigrationError("identity migration requires Linux root")
    import pwd

    account = pwd.getpwnam(DECK_USER)
    home = Path(account.pw_dir)
    if home != Path("/home/deck") or account.pw_uid <= 0:
        raise IdentityMigrationError("fixed Decky user identity is unavailable")
    return IdentityMigration(default_moves(home, user_uid=account.pw_uid), JOURNAL)


def _status_payload(migration: IdentityMigration) -> dict[str, object]:
    status = migration.inspect()
    return {
        "state": "observed",
        "locations": {name: value.value for name, value in status.locations},
        "journal_phase": status.journal_phase,
        "hardware_write": False,
        "service_write": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "apply", "rollback"))
    args = parser.parse_args()
    try:
        migration = build_migration()
        if args.command == "status":
            result = _status_payload(migration)
        else:
            require_offline()
            status = migration.apply() if args.command == "apply" else migration.rollback()
            result = {
                "state": status.journal_phase or "unchanged",
                "locations": {name: value.value for name, value in status.locations},
                "hardware_write": False,
                "service_write": False,
            }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (IdentityMigrationError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(
            json.dumps(
                {
                    "state": "refused",
                    "reason": str(error),
                    "hardware_write": False,
                    "service_write": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
