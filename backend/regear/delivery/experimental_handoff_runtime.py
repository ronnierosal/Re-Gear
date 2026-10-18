"""Local request boundary only: no executor, native qualification or startup.

Read/gate ports are server-owned constructor dependencies, never RPC inputs.
The shipped composition supplies no qualified session context and no gate.
"""
import threading
from typing import Callable

from ..application.experimental_handoff_approval import HandoffApprovalStore, HandoffContext
from ..domain.control_plane import PlacementState


HANDOFF_METHODS = frozenset({
    "preview_supervised_tv_switch", "approve_supervised_tv_switch", "execute_supervised_tv_switch",
    "approve_supervised_portable_switch", "execute_supervised_portable_switch",
    "get_transition_journal_status",
})


def unavailable(code="experimental_handoff.unavailable"):
    return {"schema_version":1, "code":code, "accepted":False, "ready":False,
            "requested":False, "operation_started":False, "safe_to_unplug":False,
            "approval_token":"", "action_required":False}


class ExperimentalHandoffRuntime:
    def __init__(self, *, read_context: Callable[[PlacementState], HandoffContext | None],
                 approvals: HandoffApprovalStore | None = None, gate_factory: Callable | None = None):
        self._read_context = read_context
        self._approvals = approvals or HandoffApprovalStore()
        self._gate_factory = gate_factory
        self._lock = threading.Lock()

    def _context(self, target):
        try:
            current = self._read_context(target)
            return current if type(current) is HandoffContext and current.target_placement is target else None
        except Exception:
            return None

    def handle(self, method, args, kwargs):
        if method not in HANDOFF_METHODS:
            return unavailable()
        target = PlacementState.PORTABLE if "portable" in method else PlacementState.DOCKED_EGPU
        if not method.startswith("execute_"):
            # No engine, journal repair, acknowledgement, approval consumption or
            # token issuance is reachable through this read-only boundary slice.
            current = self._context(target)
            return unavailable("experimental_handoff.executor_unavailable" if current is not None
                               else "experimental_handoff.session_unqualified")
        if len(args) == 1 and not kwargs:
            token = args[0]
        elif not args and set(kwargs) == {"approval_token"}:
            token = kwargs["approval_token"]
        else:
            return unavailable("experimental_handoff.request_invalid")
        if not self._lock.acquire(blocking=False):
            return unavailable("experimental_handoff.busy")
        try:
            current = self._context(target)
            try:
                approved = self._approvals.consume(token, current=current)
            except ValueError:
                return unavailable("experimental_handoff.approval_unavailable")
            # No production gate/executor is wired in this slice. Inert injected
            # gates exercise consume/admission/recheck ordering in software only.
            if self._gate_factory is None:
                return unavailable("experimental_handoff.executor_unavailable")
            try:
                with self._gate_factory().admit():
                    if self._context(target) != approved.context:
                        return unavailable("experimental_handoff.evidence_changed")
                    return unavailable("experimental_handoff.executor_unavailable")
            except Exception:
                return unavailable("experimental_handoff.admission_unavailable")
        finally:
            self._lock.release()
