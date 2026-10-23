"""Pure feature-specific evidence consistency checks; no collector or consumer.

All projections must come from separately authenticated server-owned sources.
Passing fixtures proves consistency only, never native eligibility or authority.
The reviewed command contract remains the existing fixed service and target;
an observed template name alone is insufficient without the exact alias chain.
"""
from dataclasses import dataclass
import math

from .experimental_handoff_approval import HandoffContext


@dataclass(frozen=True, slots=True)
class SessionEvidence:
    boot_id: str
    user_uid: int
    user_context_sha256: str
    pid: int
    start_before: int
    start_after: int
    unit: str
    aliases: tuple[str, ...]
    target: str
    target_services: tuple[str, ...]
    main_pid: int
    invocation_id: str
    service_active: bool
    target_active: bool
    definition_sha256: str
    integration_sha256: str
    integration_safe: bool
    started: float
    completed: float


def qualify_session(context: HandoffContext, evidence: SessionEvidence, *, now: float) -> bool:
    """Refuse missing/stale/inconsistent projections without performing any I/O."""
    if type(context) is not HandoffContext or type(evidence) is not SessionEvidence:
        return False
    e = evidence
    times = (e.started, e.completed, now)
    try:
        if any(type(t) not in (int, float) or not math.isfinite(t) for t in times):
            return False
    except OverflowError:
        return False
    if not 0 <= e.started <= e.completed <= now or now - e.started > 5:
        return False
    if (type(e.pid) is not int or type(e.main_pid) is not int
            or type(e.user_uid) is not int or type(e.start_before) is not int
            or type(e.start_after) is not int or e.start_before <= 0
            or e.start_before != e.start_after):
        return False
    if (e.service_active is not True or e.target_active is not True
            or e.integration_safe is not True):
        return False
    for names in (e.aliases, e.target_services):
        if (type(names) is not tuple or not 1 <= len(names) <= 8
                or any(type(n) is not str or not 1 <= len(n) <= 256 for n in names)
                or len(set(names)) != len(names)):
            return False
    if (context.session_unit != "gamescope-session.service"
            or context.session_target != "gamescope-session.target"
            or e.unit not in e.aliases or context.session_unit not in e.aliases
            or e.target != context.session_target or e.unit not in e.target_services):
        return False
    return (
        e.boot_id == context.boot_id
        and e.user_uid == context.user_uid
        and e.user_context_sha256 == context.user_context_sha256
        and e.pid == e.main_pid == context.source_main_pid
        and e.invocation_id == context.source_invocation_id
        and e.definition_sha256 == context.session_definition_sha256
        and e.integration_sha256 == context.integration_sha256
    )
