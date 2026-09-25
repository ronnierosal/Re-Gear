"""Production admission for the connection and plain Safe Disconnect surface.

This policy narrows product access; it never replaces lifecycle safety checks.
Read/recovery dependencies are retained even when their feature UI is hidden.
The delivered Plugin composes this adapter without changing private lifecycle
methods. Internal recovery stays available even when operator RPCs are hidden.
"""

from __future__ import annotations

from functools import wraps
import inspect
from typing import Any


CONNECTION_AND_DISCONNECT_RPCS = frozenset({
    "get_snapshot",
    "get_automatic_dock_status",
    "get_link_recovery_status",
    "get_egpu_disconnect_status", "execute_egpu_disconnect",
    "preview_presentation_preparation",
    "preview_supervised_tv_switch",
    "get_supervised_tv_switch_status",
    "get_sleep_readiness", "get_transition_journal_status", "acknowledge_sleep_journal",
    "get_process_release_status", "acknowledge_process_release",
})

# These expose observation only. Retained-state lookup and acknowledgement above
# must remain available; a hidden tab must not suppress safety status/recovery.
READ_RPCS = frozenset({
    "get_tdp_status", "get_auto_tdp_status", "get_auto_tdp_preferences",
    "get_auto_tdp_benchmark_status", "get_peripheral_status", "get_action_history",
    "get_diagnostic_logging_status", "get_docked_igpu_status", "acknowledge_docked_igpu_status",
    "preview_support_bundle", "preview_process_release", "classify_offline_details",
})
PLAIN_DISCONNECT_ACTIONS = frozenset({
    "whole_dock_disconnect", "whole_dock_disconnect_complete",
})


def rpc_allowed(profile: str, method: str, arguments: dict[str, Any]) -> bool:
    if profile == "development":
        return True
    if profile != "production":
        return False
    if method not in CONNECTION_AND_DISCONNECT_RPCS | READ_RPCS:
        return False
    if method == "execute_egpu_disconnect":
        action = arguments.get("trial_action", "")
        return (
            isinstance(action, str) and action in PLAIN_DISCONNECT_ACTIONS
            and arguments.get("relaunch_intent", "disconnect") == "disconnect"
        )
    return True


def unavailable() -> dict[str, object]:
    return {
        "schema_version": 1, "ok": False, "available": False,
        "code": "build_profile.feature_unavailable", "busy": False,
        "safe_to_unplug": False, "hardware_write": False,
    }


def profiled_plugin(plugin_class: type, profile: str) -> type:
    """Wrap public async RPC entry points; private lifecycle methods stay intact.

    Development retains its exact class. Production denies new public methods by
    default and binds positional/keyword arguments identically before admission.
    Wrappers call the original method only after product-policy admission; its
    current consent, identity, freshness and safety validation still runs.
    """
    if profile == "development":
        return plugin_class

    def wrap(method: str, implementation):
        signature = inspect.signature(implementation)

        @wraps(implementation)
        async def guarded(self, *args, **kwargs):
            try:
                bound = signature.bind(self, *args, **kwargs)
                bound.apply_defaults()
            except TypeError:
                return unavailable()
            if not rpc_allowed(profile, method, bound.arguments):
                return unavailable()
            return await implementation(self, *args, **kwargs)

        return guarded

    methods = {
        name: wrap(name, implementation)
        for name, implementation in inspect.getmembers(plugin_class, inspect.iscoroutinefunction)
        if not name.startswith("_")
    }
    return type(plugin_class.__name__, (plugin_class,), {
        "__module__": plugin_class.__module__, **methods,
    })
