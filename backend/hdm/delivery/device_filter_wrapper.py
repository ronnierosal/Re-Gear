"""Armed wrapper gate. Any failure must terminate the armed launch.

Only authenticated absence at wrapper entry permits ordinary fallback. This
module never arms, clears an arm, restarts a service, or infers exec success.
"""
import hashlib
import json
import os
import secrets
import time

from .device_filter_arm import FilterArm, FilterArmStore
from .device_filter_protocol import FilterRequest, grant_matches
from .device_filter_transport import request_grant


def latch_filter_arm(unit):
    return FilterArmStore().read(unit)


def config_hash(config):
    from .gamescope_wrapper import config_to_dict
    if config is None:
        raise ValueError("filter launch configuration unavailable")
    raw = json.dumps(config_to_dict(config), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def authorize_filter_launch(arm, *, state_root, raw_boot_id, environment, candidate_config):
    from .gamescope_wrapper import _load_config, _verified_egpu_binding_sha256
    if type(arm) is not FilterArm or not raw_boot_id or not state_root.is_absolute():
        raise ValueError("armed launch context required")
    selected_hash = config_hash(candidate_config)
    if selected_hash != arm.config_hash:
        raise ValueError("candidate configuration does not match arm")
    store = FilterArmStore()
    invocation = environment.get("INVOCATION_ID", "")
    boot_hash = hashlib.sha256(raw_boot_id.encode()).hexdigest()
    def revalidate():
        if store.read(arm.unit) != arm:
            raise ValueError("latched arm changed")
        arm.require_current(unit=arm.unit, uid=os.getuid(), boot_hash=boot_hash,
            topology_hash=_verified_egpu_binding_sha256(raw_boot_id),
            config_hash=config_hash(_load_config(state_root)), invocation=invocation,
            now=time.monotonic())
    revalidate()
    request = FilterRequest(1, arm.operation, arm.unit, invocation, secrets.token_hex(32))
    grant = request_grant(request, deadline=min(arm.deadline, time.monotonic() + 5))
    if not grant_matches(request, grant):
        raise ValueError("filter reply does not match waiting launch")
    revalidate()
    return grant
