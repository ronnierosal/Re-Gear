"""Read-only local-on-device Auto TDP configuration context; no admission or writes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from hdm.adapters.steamos.auto_tdp_host import AutoTdpHostDiscovery
from hdm.adapters.steamos.gamescope import GamescopeDiscovery
from hdm.adapters.steamos.gamescope_user import resolve_gamescope_user
from hdm.adapters.steamos.tdp_provider import SteamOsManagerTdpProvider
from hdm.ports.tdp import TdpReading


def probe(provider=None, host=None) -> dict[str, object]:
    result = {"schema_version": 1, "code": "auto_tdp.configuration_context_unavailable",
              "host_context_key": None, "authorizes_control": False}
    try:
        provider = provider or SteamOsManagerTdpProvider(
            user_resolver=lambda: resolve_gamescope_user(GamescopeDiscovery().scan()).context)
        host = host or AutoTdpHostDiscovery()
        # The default provider deliberately retains ownership_ready=False. Reading
        # observations is allowed; no lease, session, journal or actuator is created.
        before = provider.observe().reading
        if not isinstance(before, TdpReading):
            return result
        first = host.observe(before)
        after = provider.observe().reading
        if not isinstance(after, TdpReading) or after != before:
            return result
        last = host.observe(after)
        if first != last or first.context_key is None:
            return result
        return {**result, "code": "auto_tdp.configuration_context_observed",
                "host_context_key": first.context_key}
    except Exception:
        return result


def main() -> int:
    result = probe()
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["host_context_key"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
