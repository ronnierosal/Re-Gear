"""Inactive armed prepare-and-withhold entry, before native session startup.

Every outcome fails closed, including grant-shaped replies. No native execution
or arm clearing exists. Immutable bootstrap invokes this for an armed session;
no runtime installation or activation is supplied by this module.
"""
import hashlib
import math
import os
from pathlib import Path
import re
import secrets
import time
from .device_filter_arm import FilterArm,FilterArmStore
from .device_filter_protocol import FilterRequest
from .device_filter_transport import request_grant
from .device_filter_wrapper import config_hash
from .gamescope_wrapper import _load_config,_verified_egpu_binding_sha256

class SessionEntryWithheld(RuntimeError):pass


def withhold_session_entry(arm,*,state_root,raw_boot_id,environment,candidate_config,
                           arms=None,transport=request_grant,clock=time.monotonic,
                           uid=os.getuid if hasattr(os,'getuid') else lambda:-1,
                           load_config=_load_config,topology=_verified_egpu_binding_sha256):
    if (type(arm) is not FilterArm or arm.unit!='gamescope-session.service'
            or not isinstance(state_root,Path) or not state_root.is_absolute() or '..' in state_root.parts
            or type(raw_boot_id) is not str
            or re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',raw_boot_id) is None):
        raise SessionEntryWithheld('explicit armed session-entry context required')
    store=FilterArmStore() if arms is None else arms
    start=clock()
    if type(start) not in (int,float) or not math.isfinite(start) or start<0:
        raise SessionEntryWithheld('session-entry time unavailable')
    deadline=min(arm.deadline,start+5)
    try:
        invocation=environment.get('INVOCATION_ID','')
        if config_hash(candidate_config)!=arm.config_hash:raise ValueError('candidate configuration changed')
        if store.read(arm.unit)!=arm:raise ValueError('latched arm changed')
        observed_topology=topology(raw_boot_id)
        observed_config=config_hash(load_config(state_root))
        now=clock()
        arm.require_current(unit='gamescope-session.service',uid=uid(),boot_hash=hashlib.sha256(raw_boot_id.encode()).hexdigest(),
            topology_hash=observed_topology,config_hash=observed_config,invocation=invocation,now=now)
        if now<start or now>=deadline or store.read(arm.unit)!=arm:raise ValueError('session-entry deadline or arm changed')
        now=clock()
        if type(now) not in (int,float) or not math.isfinite(now) or not start<=now<deadline:
            raise ValueError('session-entry deadline changed during validation')
        request=FilterRequest(1,arm.operation,arm.unit,invocation,secrets.token_hex(32))
        transport(request,deadline=deadline)
    except Exception as error:
        raise SessionEntryWithheld('session-entry preparation withheld; recovery may be required') from error
    raise SessionEntryWithheld('no response authorizes native startup')
