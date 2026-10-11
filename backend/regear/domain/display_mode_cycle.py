"""Single-flight, revocable pure plans and receipts; performs no provider calls."""
from dataclasses import dataclass, replace
from .display_modes import Binding, Mode, Observation, cycle, identity, number


@dataclass(frozen=True)
class Operation:
    request: str
    binding: Binding
    previous: Mode
    target: Mode
    sequence: int
    observed_at: float
    state: str = 'planned'
    restoring: bool = False
    readback_allowed: bool = True


@dataclass(frozen=True)
class Receipt:
    request: str
    binding: Binding
    committed: Mode
    observed_at: float
    sequence: int


class CycleController:
    """Caller supplies qualified evidence. Returned plans are NOT permission tokens.

    M1 must separately enforce real admission and ownership at its effect boundary.
    Recovery is explicit; this controller does not restart, retry, poll or restore.
    """
    def __init__(self):
        self._operation: Operation | None = None
        self._used: set[str] = set()

    @property
    def operation(self) -> Operation | None:
        return self._operation

    def _set(self, state: str) -> Operation:
        self._operation = replace(self._operation, state=state)
        return self._operation

    def begin(self, evidence: Observation, axis: str, request: str, now: float) -> Operation:
        if self.operation is not None and self.operation.state not in ('cancelled', 'revoked', 'rolled_back', 'committed'):
            raise ValueError('operation.in_flight_or_recovery')
        if not identity(request) or request in self._used:
            raise ValueError('request.invalid_or_replayed')
        target = cycle(evidence, axis, now)
        if evidence.rollback_qualified is not True:
            raise ValueError('rollback.unqualified')
        self._used.add(request)
        self._operation = Operation(request, evidence.binding, evidence.current, target, evidence.sequence, evidence.observed_at)
        return self.operation

    def _binding(self, evidence: Observation, now: float) -> None:
        evidence.validate(now)
        if evidence.binding != self.operation.binding or evidence.sequence < self.operation.sequence or evidence.observed_at < self.operation.observed_at:
            raise ValueError('operation.binding_lost')
        if self.operation.previous not in evidence.modes or self.operation.target not in evidence.modes:
            raise ValueError('operation.mode_withdrawn')

    def dispatch(self, evidence: Observation, now: float) -> Operation:
        if self.operation is None or self.operation.state != 'planned':
            raise ValueError('operation.not_planned')
        try:
            self._binding(evidence, now)
            if evidence.current != self.operation.previous or evidence.rollback_qualified is not True:
                raise ValueError('operation.changed_or_unqualified')
        except ValueError:
            self._set('revoked')
            raise
        self._operation = replace(self.operation, sequence=evidence.sequence, observed_at=now, state='pending')
        return self.operation

    def readback(self, evidence: Observation, receipt: Receipt, now: float) -> Operation:
        if self.operation is None or self.operation.state not in ('pending', 'rollback_pending', 'recovery_required'):
            raise ValueError('operation.no_readback')
        if not self.operation.readback_allowed:
            raise ValueError('operation.ownership_revoked')
        rollback = self.operation.restoring
        expected = self.operation.previous if rollback else self.operation.target
        try:
            self._binding(evidence, now)
            if evidence.current not in (self.operation.previous, self.operation.target):
                raise ValueError('readback.external_change')
        except ValueError:
            self._operation = replace(self.operation, state='recovery_required', readback_allowed=False)
            raise
        try:
            if not isinstance(receipt, Receipt) or receipt.request != self.operation.request or receipt.binding != self.operation.binding or receipt.committed != expected or evidence.current != expected or not number(receipt.observed_at) or receipt.observed_at != evidence.observed_at or receipt.observed_at < self.operation.observed_at or type(receipt.sequence) is not int or receipt.sequence != evidence.sequence or receipt.sequence <= self.operation.sequence:
                raise ValueError('readback.unverified')
        except ValueError:
            self._set('recovery_required')
            raise
        self._operation = replace(self.operation, sequence=receipt.sequence, observed_at=receipt.observed_at, state='rolled_back' if rollback else 'committed')
        return self.operation

    def rollback(self, evidence: Observation, now: float) -> Operation:
        if self.operation is None or self.operation.state != 'committed':
            raise ValueError('rollback.no_owned_committed_receipt')
        try:
            self._binding(evidence, now)
            if evidence.current != self.operation.target or evidence.owned_request != self.operation.request:
                raise ValueError('rollback.external_change_or_ownership_unknown')
        except ValueError:
            self._operation = replace(self.operation, state='recovery_required', readback_allowed=False)
            raise
        if evidence.rollback_qualified is not True:
            raise ValueError('rollback.unqualified')
        self._operation = replace(self.operation, sequence=evidence.sequence, observed_at=now, state='rollback_pending', restoring=True)
        return self.operation

    def uncertain(self) -> Operation:
        if self.operation is None or self.operation.state not in ('pending', 'rollback_pending'):
            raise ValueError('operation.not_submitted')
        return self._set('recovery_required')

    def cancel(self) -> Operation:
        if self.operation is None or self.operation.state not in ('planned', 'pending', 'rollback_pending'):
            raise ValueError('operation.not_cancellable')
        return self._set('cancelled' if self.operation.state == 'planned' else 'recovery_required')
