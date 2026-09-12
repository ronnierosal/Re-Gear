"""Read-only local-on-device Auto TDP configuration context; no admission or writes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.adapters.steamos.auto_tdp_host import AutoTdpHostDiscovery
from regear.adapters.steamos.gamescope import GamescopeDiscovery
from regear.adapters.steamos.gamescope_user import resolve_gamescope_user
from regear.adapters.steamos.tdp_provider import SteamOsManagerTdpProvider
from regear.ports.tdp import TdpReading


def _register(register) -> dict[str, int]:
    return {"minimum": register.minimum, "maximum": register.maximum, "current": register.current}


def expressible_range(reading: TdpReading) -> dict[str, object]:
    """The sustained watts this provider can actually express.

    A request maps onto the boost registers as max(watts, register.minimum), so a
    boost ceiling below the sustained ceiling silently narrows the usable range.
    Readiness reports the sustained range alone, so a policy above a boost ceiling
    looks startable and is only refused later, per-tick, as readback_invalid.
    """
    minimum = reading.sustained.minimum
    maximum = min(reading.sustained.maximum, reading.slow.maximum, reading.fast.maximum)
    return {
        "minimum_watts": minimum,
        "maximum_watts": maximum if maximum >= minimum else None,
        "narrowed_by_boost_ceiling": maximum < reading.sustained.maximum,
        "code": ("auto_tdp.provider_range_unavailable" if maximum < minimum
                 else "auto_tdp.provider_range_narrowed_by_boost_ceiling" if maximum < reading.sustained.maximum
                 else "auto_tdp.provider_range_fully_expressible"),
    }


def probe(provider=None, host=None) -> dict[str, object]:
    result = {"schema_version": 1, "code": "auto_tdp.configuration_context_unavailable",
              "host_context_key": None, "authorizes_control": False,
              "registers": None, "expressible": None}
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
        # Register evidence is bounded and non-identifying, so it is reported for
        # any stable reading, including one whose host context is unusable.
        registers = {name: _register(getattr(after, name)) for name in ("sustained", "slow", "fast")}
        result = {**result, "registers": registers, "expressible": expressible_range(after)}
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
