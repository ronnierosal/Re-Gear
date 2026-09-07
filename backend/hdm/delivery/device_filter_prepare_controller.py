"""One-shot listener composition, without activation or grant authority.

UID authentication is preliminary; the prepare handler must independently bind
the held peer/service and honor the supplied deadline for non-socket work.
"""
import time
import math
import os
from functools import partial
from dataclasses import dataclass

from ..adapters.steamos.prepare_hardware_identity import PrepareHardwareIdentity, RenderTarget
from .device_filter_arm import FilterArm, FilterArmStore
from ..ports.presentation_activation import GamescopeUserContext, UserServiceOperation
from .device_filter_runtime_bundle import RuntimeBundle
from .device_filter_session_entry import SessionEntryExpectation
from .device_filter_session_prepare import SessionEntryPreparedObservationSource, SessionEntryPrepareServer
from .device_filter_prepare_policy import build_prepare_policy
from .device_filter_program import compile_device_filter

from .device_filter_listener import FilterListener
from .device_filter_transport import _remaining, peer_identity


def serve_prepare_once(handler, *, session_gid, expected_uid, deadline,
                       clock=time.monotonic, listener_factory=FilterListener):
    if not callable(handler) or type(expected_uid) is not int or expected_uid <= 0:
        raise ValueError("prepare handler and independently expected UID required")
    with listener_factory(session_gid) as listener:
        return _accept_prepare(listener, handler, expected_uid, deadline, clock)


def _accept_prepare(listener, handler, expected_uid, deadline, clock):
    with listener.accept(deadline=deadline, clock=clock) as connection:
        _remaining(connection, deadline, clock)
        if peer_identity(connection).uid != expected_uid:
            raise ValueError("unexpected prepare peer UID")
        result = handler(connection, deadline=deadline)
        _remaining(listener.connection, deadline, clock)
        return result


def serve_session_prepare_once(*, user, expected_arm, runtime, expected_hardware,
                               effective_expectation, state_root, journal, deadline,
                               clock=time.monotonic, listener_factory=FilterListener,
                               source_factory=SessionEntryPreparedObservationSource,
                               server_factory=SessionEntryPrepareServer):
    """Compose the real prepare-and-withhold path from independent expectations.

    No service configuration, arm publication or recovery is performed. A caller
    must retain recovery ownership when this returns or raises.
    """
    handler = _session_handler(user=user, expected_arm=expected_arm, runtime=runtime,
        expected_hardware=expected_hardware, effective_expectation=effective_expectation,
        state_root=state_root, journal=journal, deadline=deadline, clock=clock,
        source_factory=source_factory, server_factory=server_factory)
    return serve_prepare_once(handler, session_gid=user.gid, expected_uid=user.uid,
                              deadline=deadline, clock=clock, listener_factory=listener_factory)


def _session_handler(*, user, expected_arm, runtime, expected_hardware,
                     effective_expectation, state_root, journal, deadline, clock,
                     source_factory, server_factory):
    arm = expected_arm
    now = clock()
    if (type(arm) is not FilterArm or arm.unit != 'gamescope-session.service'
            or type(user.uid) is not int or user.uid != arm.uid
            or type(user.gid) is not int or user.gid < 0
            or type(runtime) is not RuntimeBundle
            or type(effective_expectation) is not SessionEntryExpectation
            or effective_expectation.runtime != runtime
            or type(expected_hardware) is not PrepareHardwareIdentity
            or type(expected_hardware.external) is not RenderTarget
            or type(expected_hardware.internal) is not RenderTarget
            or (expected_hardware.boot_hash, expected_hardware.topology_hash) != (arm.boot_hash, arm.topology_hash)
            or type(now) not in (int, float) or not math.isfinite(now) or now < 0
            or type(deadline) not in (int, float) or not math.isfinite(deadline)
            or not now < deadline <= arm.deadline or deadline-now > 5):
        raise ValueError('independent current session preparation context required')
    external = expected_hardware.external
    denied = ((os.major(external.device), external.primary_minor),
              (os.major(external.device), os.minor(external.device)))
    compile_device_filter(denied)
    source = source_factory(user, arm, runtime, expected_hardware, effective_expectation,
                            state_root=state_root, deadline=deadline, clock=clock)
    server = server_factory(journal, user, source, clock=clock)
    builder = partial(build_prepare_policy, expected_denied_devices=denied)
    return partial(server.handle, expected_arm=arm, runtime=runtime, policy_builder=builder)


@dataclass(frozen=True)
class SessionPreparePreflight:
    user: GamescopeUserContext
    arm: FilterArm
    runtime_digest: str
    boot_hash: str
    config_hash: str
    topology_hash: str
    observed_at: float
    idle: bool


def run_session_prepare_once(*, user, expected_arm, runtime, expected_hardware,
                             effective_expectation, state_root, journal, deadline,
                             commands, preflight, arms=None, clock=time.monotonic,
                             listener_factory=FilterListener,
                             source_factory=SessionEntryPreparedObservationSource,
                             server_factory=SessionEntryPrepareServer):
    """Explicit supervised restart, followed by preparation with launch withheld.

    A durable external owner must already own rollback and process recovery.
    The independent preflight observer verifies current runtime/configuration,
    hardware and idle state; an approval boolean cannot replace its snapshot.
    """
    if type(user) is not GamescopeUserContext or not callable(preflight):
        raise ValueError('typed user and independent preflight observer required')
    start = clock()
    if (type(start) not in (int,float) or not math.isfinite(start) or start < 0
            or type(deadline) not in (int,float) or not math.isfinite(deadline)
            or type(expected_arm) is not FilterArm or not 0 < deadline-start <= 90
            or deadline >= expected_arm.deadline):
        raise ValueError('bounded startup deadline with remaining handshake time required')
    def handler_for(prepare_deadline):
        return _session_handler(user=user, expected_arm=expected_arm, runtime=runtime,
            expected_hardware=expected_hardware, effective_expectation=effective_expectation,
            state_root=state_root, journal=journal, deadline=prepare_deadline, clock=clock,
            source_factory=source_factory, server_factory=server_factory)
    # Validate all context before restart without spending the later handshake
    # budget on stopping the old Steam/Gamescope session. No source reads here.
    handler_for(min(start+4,expected_arm.deadline))
    store = FilterArmStore() if arms is None else arms
    last = None
    def verify():
        nonlocal last
        observed = preflight()
        if (type(observed) is not SessionPreparePreflight or type(observed.user) is not GamescopeUserContext
                or type(observed.arm) is not FilterArm or observed.user != user or observed.arm != expected_arm
                or observed.idle is not True
                or any(type(value) is not str for value in (observed.runtime_digest,
                    observed.boot_hash, observed.config_hash, observed.topology_hash))
                or (observed.runtime_digest, observed.boot_hash, observed.config_hash, observed.topology_hash)
                != (runtime.digest, expected_arm.boot_hash, expected_arm.config_hash, expected_arm.topology_hash)
                or type(observed.observed_at) not in (int,float) or not math.isfinite(observed.observed_at)
                or observed.observed_at < 0):
            raise ValueError('current approved session context unavailable')
        if store.read(expected_arm.unit) != expected_arm:
            raise ValueError('approved session arm changed')
        now = clock()
        if (type(now) not in (int,float) or not math.isfinite(now) or now < 0
                or not 0 <= now-observed.observed_at <= 1 or not now < deadline
                or (last is not None and now < last)):
            raise ValueError('fresh session preflight deadline required')
        last = now
        return deadline-now
    verify()
    with listener_factory(user.gid) as listener:
        remaining = verify()
        restarted = commands.run(UserServiceOperation.RESTART_GAMESCOPE_SESSION,
            uid=user.uid, username=user.username, timeout_seconds=remaining)
        if restarted.ok is not True:
            raise ValueError('prepared session restart request failed')
        with listener.accept_waiting(deadline=deadline,clock=clock) as connection:
            arrived = clock()
            if (type(arrived) not in (int,float) or not math.isfinite(arrived)
                    or arrived < last or arrived >= deadline):
                raise TimeoutError('session arrived outside startup deadline')
            prepare_deadline = min(expected_arm.deadline,arrived+4)
            _remaining(connection,prepare_deadline,clock)
            if peer_identity(connection).uid != user.uid:
                raise ValueError('unexpected prepare peer UID')
            handler = handler_for(prepare_deadline)
            result = handler(connection,deadline=prepare_deadline)
            _remaining(listener.connection,prepare_deadline,clock)
            return result
