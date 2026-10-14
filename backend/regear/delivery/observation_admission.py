"""Deny unsupported-host effects before Plugin composition and method dispatch."""

import asyncio
import inspect
from functools import wraps

from ..adapters.steamos.host import HostDiscovery
from ..domain.runtime_admission import RuntimeAdmission, passive_rpc_allowed, runtime_admission
from ..profiles.ally_x import matches_ally_x


class ObservationDenied(ValueError):
    pass


def mode(plugin):
    try:
        reader = object.__getattribute__(plugin, "_runtime_host_record")
        exact = matches_ally_x(reader())
    except Exception:
        exact = False
    try:
        forced = object.__getattribute__(plugin, "_observation_only")
    except AttributeError:
        forced = None
    # A runtime composed without mutation services cannot upgrade in place.
    if getattr(plugin, "_observation_started", False) is True:
        forced = True
    return runtime_admission(exact_host=exact, observation_only=forced)


def unavailable():
    return {
        "schema_version": 1, "code": "runtime.observation_only", "state": "unsupported",
        "ok": False, "available": False, "accepted": False, "requested": False,
        "ready": False, "busy": False, "safe_to_unplug": False, "hardware_write": False,
        "token": "", "approval_token": "", "blockers": ["runtime.observation_only"],
    }


def interceptor_admission(plugin, payload):
    """Report immutable constructor provenance, never dynamic host/read evidence."""
    provenance = object.__getattribute__(plugin, "__dict__").get("_observation_started")
    if provenance is not True and provenance is not False:
        return payload
    admission = payload.setdefault("runtime_admission", {})
    admission.update(
        schema_version=1,
        sleep_interceptor_admission=("observation-only" if provenance is True else "supported-runtime"),
    )
    return payload


# Existing unload closes resources already owned by a known-host runtime. These
# helpers cannot construct services, dispatch work or alter a durable record.
_CLEANUP_HELPERS = frozenset({
    "_journey_now_ns", "_bounded_elapsed_ms", "_record_shutdown_checkpoint",
    "_retain_until_done", "_journey_clock_ns",
})


def observation_plugin(plugin_class, *, passive_api, build_info, render_snapshot, enrich_snapshot=None):
    """Wrap both build profiles, including methods added after class creation.

    Unknown hosts never compose the mutation-capable Plugin. Every later method
    invocation re-reads host evidence; a previously retrieved bound method is
    not a capability. Existing lifecycle guards remain necessary on known hosts.
    """
    class Guarded(plugin_class):
        _runtime_host_record = staticmethod(lambda: HostDiscovery().scan())

        def __init__(self, *, observation_only=False):
            self._observation_only = observation_only
            self._observation_started = mode(self) is RuntimeAdmission.OBSERVATION_ONLY
            if self._observation_started:
                self._unloading = False
                self._api = passive_api()
                self._build_info = build_info()
                return
            super().__init__()

        def __getattribute__(self, name):
            implementation = super().__getattribute__(name)
            if (name.startswith("__") or name == "_runtime_host_record"
                    or (name in _CLEANUP_HELPERS and object.__getattribute__(self, "__dict__").get("_observation_started") is False)
                    or (name.startswith("_") and name in object.__getattribute__(self, "__dict__"))
                    or not (inspect.isfunction(implementation) or inspect.ismethod(implementation))):
                return implementation
            if inspect.iscoroutinefunction(implementation):
                @wraps(implementation)
                async def guarded(*args, **kwargs):
                    if name == "_unload":
                        if getattr(self, "_observation_started", True):
                            self._unloading = True
                            return None
                        return await implementation(*args, **kwargs)
                    if mode(self) is RuntimeAdmission.PROFILE_GATED:
                        result = await implementation(*args, **kwargs)
                        if name == "get_snapshot":
                            if enrich_snapshot is not None:
                                result = await enrich_snapshot(self, result)
                            return interceptor_admission(self, result)
                        return result
                    if name == "_main":
                        return None
                    if name == "get_snapshot":
                        report = await asyncio.to_thread(self._api.get_snapshot_report)
                        payload = render_snapshot(report)
                        payload["diagnostics"]["build"] = self._build_info
                        guard = payload["snapshot"]["sleep_guard"]
                        guard.update(confidence="unknown", reason="Sleep protection is unverified in observation-only mode.")
                        payload["snapshot"]["disconnect_readiness"]["ready"] = False
                        payload["runtime_admission"] = {
                            "mode": "observation-only", "mutation_allowed": False,
                            "sleep_protection": "unknown", "safe_to_unplug": False,
                        }
                        if enrich_snapshot is not None:
                            payload = await enrich_snapshot(self, payload)
                        return interceptor_admission(self, payload)
                    if not name.startswith("_"):
                        if passive_rpc_allowed(name):
                            return await implementation(*args, **kwargs)
                        return unavailable()
                    raise ObservationDenied("runtime.observation_only")
                return guarded

            @wraps(implementation)
            def guarded(*args, **kwargs):
                if mode(self) is RuntimeAdmission.OBSERVATION_ONLY:
                    raise ObservationDenied("runtime.observation_only")
                return implementation(*args, **kwargs)
            return guarded

    Guarded.__name__ = plugin_class.__name__
    Guarded.__module__ = plugin_class.__module__
    return Guarded
