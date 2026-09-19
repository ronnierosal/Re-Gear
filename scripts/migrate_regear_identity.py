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
from regear.adapters.steamos.gamescope_user import GamescopeUserContext  # noqa: E402
from regear.delivery.gamescope_integration import GamescopeIntegrationStore  # noqa: E402
from regear.delivery.identity_dropin_migration import ManagedDropinMigration  # noqa: E402


JOURNAL = Path("/var/lib/regear/identity-migration-v1.json")
DROPIN_JOURNAL = Path("/var/lib/regear/identity-dropin-migration-v1.json")
SYSTEMCTL = "/usr/bin/systemctl"
DECK_USER = "deck"
PLUGIN_ROOT = Path("/home/deck/homebrew/plugins/Re-Gear")
CURRENT_GAMESCOPE_STATE = "/home/deck/.local/share/regear"
MAX_ENVIRON_BYTES = 1024 * 1024


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


def _classify_gamescope_environment(environment: dict[str, str]) -> str:
    current = environment.get("REGEAR_STATE_ROOT")
    former = environment.get("HDM_STATE_ROOT")
    if current is not None and former is not None:
        return "ambiguous"
    if former is not None:
        return "former"
    if current is None:
        return "missing"
    return "current" if current == CURRENT_GAMESCOPE_STATE else "unexpected"


def _gamescope_environment_status() -> str:
    observations: list[str] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            if (entry / "comm").read_text(encoding="utf-8").strip() != "gamescope":
                continue
            data = (entry / "environ").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        if len(data) > MAX_ENVIRON_BYTES:
            return "unreadable"
        environment: dict[str, str] = {}
        for item in data.split(b"\0"):
            if not item or b"=" not in item:
                continue
            key, value = item.split(b"=", 1)
            if key in (b"REGEAR_STATE_ROOT", b"HDM_STATE_ROOT"):
                environment[key.decode("ascii")] = value.decode("utf-8", "replace")
        observations.append(_classify_gamescope_environment(environment))
    if not observations:
        return "inactive"
    if len(observations) != 1:
        return "ambiguous"
    return observations[0]


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


def build_dropin_migration() -> ManagedDropinMigration:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise IdentityMigrationError("identity migration requires Linux root")
    import pwd

    account = pwd.getpwnam(DECK_USER)
    home = Path(account.pw_dir)
    if home != Path("/home/deck") or account.pw_uid <= 0 or account.pw_gid <= 0:
        raise IdentityMigrationError("fixed Decky user identity is unavailable")
    user = GamescopeUserContext(
        DECK_USER,
        account.pw_uid,
        account.pw_gid,
        home,
        Path("/run/user") / str(account.pw_uid),
        Path("/run/user") / str(account.pw_uid) / "bus",
    )
    store = GamescopeIntegrationStore(
        plugin_root=PLUGIN_ROOT,
        user=user,
        effective_uid=os.geteuid,
        set_owner=os.chown,
    )
    return ManagedDropinMigration(store, DROPIN_JOURNAL)


def _status_payload(
    migration: IdentityMigration,
    dropin: ManagedDropinMigration,
) -> dict[str, object]:
    status = migration.inspect()
    return {
        "state": "observed",
        "locations": {name: value.value for name, value in status.locations},
        "journal_phase": status.journal_phase,
        "gamescope_dropin": dropin.inspect(),
        "gamescope_environment": _gamescope_environment_status(),
        "hardware_write": False,
        "service_write": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "apply", "rollback"))
    args = parser.parse_args()
    try:
        migration = build_migration()
        dropin = build_dropin_migration()
        if args.command == "status":
            result = _status_payload(migration, dropin)
        else:
            require_offline()
            if args.command == "apply":
                status = migration.apply()
                dropin_status = dropin.apply()
            else:
                dropin_status = dropin.rollback()
                status = migration.rollback()
            result = {
                "state": status.journal_phase or "unchanged",
                "locations": {name: value.value for name, value in status.locations},
                "gamescope_dropin": dropin_status,
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
