"""Internal approval policy for future guarded eGPU process release.

This module issues and validates backend-owned approval tokens.  It contains no
signal mechanism and is not exposed by the Decky delivery adapter.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

from ..domain.models import (
    EgpuClientKind,
    EgpuClientObservation,
    EgpuResourceKind,
    ObservedSnapshot,
)
from ..domain.process_release import (
    ProcessClientFact,
    ProcessReleaseApproval,
    ProcessReleasePreview,
    ProcessReleasePreviewRow,
    ProcessReleaseTarget,
    ReleasePhase,
)


TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,96}$")
DEFAULT_APPROVAL_TTL_SECONDS = 120.0
MAX_APPROVAL_TOKENS = 3
MAX_RELEASE_TARGETS = 32
# Reserve full journal capacity for the verified-save child, both release
# phases, every remaining sleep boundary, and restart recovery.
MAX_SLEEP_CHILD_RELEASE_TARGETS = 26


@dataclass(frozen=True, slots=True)
class GracefulReleaseEvidence:
    operation_id: str
    attempted_instance_ids: tuple[str, ...]
    observed_generation: str
    parent_operation_id: str = ""

    def __post_init__(self) -> None:
        if not TOKEN_RE.fullmatch(self.operation_id):
            raise ValueError("graceful release operation ID is invalid")
        if not self.attempted_instance_ids or not self.observed_generation:
            raise ValueError("graceful release evidence is incomplete")
        if self.parent_operation_id and not TOKEN_RE.fullmatch(
            self.parent_operation_id
        ):
            raise ValueError("graceful release parent operation ID is invalid")


class GracefulReleaseReceiptStore:
    """Keep graceful-attempt identities behind short-lived opaque receipts."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_APPROVAL_TTL_SECONDS,
        max_tokens: int = MAX_APPROVAL_TOKENS,
        monotonic: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or ttl_seconds > 300:
            raise ValueError("process receipt TTL must be between 0 and 300 seconds")
        if max_tokens <= 0 or max_tokens > 10:
            raise ValueError("process receipt bound must be between 1 and 10")
        self._ttl_seconds = ttl_seconds
        self._max_tokens = max_tokens
        self._monotonic = monotonic
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(18))
        self._values: dict[str, tuple[float, GracefulReleaseEvidence]] = {}
        self._lock = threading.Lock()

    def issue(self, evidence: GracefulReleaseEvidence) -> str:
        with self._lock:
            self._expire_locked()
            while len(self._values) >= self._max_tokens:
                oldest = min(self._values, key=lambda token: self._values[token][0])
                self._values.pop(oldest)
            token = self._token_factory()
            if not TOKEN_RE.fullmatch(token) or token in self._values:
                raise ValueError("process receipt generator returned an invalid token")
            self._values[token] = (self._monotonic(), evidence)
            return token

    def inspect(self, token: str) -> GracefulReleaseEvidence:
        return self._get(token, consume=False)

    def consume(self, token: str) -> GracefulReleaseEvidence:
        return self._get(token, consume=True)

    def _get(self, token: str, *, consume: bool) -> GracefulReleaseEvidence:
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("process receipt token is invalid")
        with self._lock:
            self._expire_locked()
            value = self._values.get(token)
            if value is None:
                raise ValueError("process receipt expired or was already used")
            if consume:
                self._values.pop(token)
            return value[1]

    def _expire_locked(self) -> None:
        cutoff = self._monotonic() - self._ttl_seconds
        for token in [
            token for token, (created, _) in self._values.items() if created < cutoff
        ]:
            self._values.pop(token, None)


def _client_fingerprint(clients: tuple[EgpuClientObservation, ...]) -> str:
    rows = sorted(
        (
            client.instance_id,
            str(client.pid),
            client.name,
            client.process_start_time,
            client.kind.value,
            "1" if client.close_eligible else "0",
            ",".join(sorted(resource.value for resource in client.resources)),
        )
        for client in clients
    )
    encoded = "\n".join("|".join(row) for row in rows).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _client_facts(
    clients: tuple[EgpuClientObservation, ...],
) -> tuple[ProcessClientFact, ...]:
    return tuple(
        ProcessClientFact(
            instance_id=client.instance_id,
            pid=client.pid,
            name=client.name,
            kind=client.kind,
            resources=client.resources,
            close_eligible=client.close_eligible,
            process_start_time=client.process_start_time,
        )
        for client in clients
    )


def _eligible_targets(
    clients: tuple[EgpuClientObservation, ...],
) -> tuple[ProcessReleaseTarget, ...]:
    eligible_clients = tuple(
        client
        for client in clients
        if client.kind is EgpuClientKind.USER and client.close_eligible
    )
    if any(not client.process_start_time for client in eligible_clients):
        raise ValueError("exact process start-time identity is required")
    eligible = tuple(
        ProcessReleaseTarget(
            instance_id=client.instance_id,
            pid=client.pid,
            name=client.name,
            resources=client.resources,
            process_start_time=client.process_start_time,
        )
        for client in eligible_clients
    )
    if len(eligible) > MAX_RELEASE_TARGETS:
        raise ValueError("eligible process target count exceeds the approval bound")
    return eligible


class ProcessReleaseApprovalStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_APPROVAL_TTL_SECONDS,
        max_tokens: int = MAX_APPROVAL_TOKENS,
        monotonic: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] | None = None,
        operation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or ttl_seconds > 300:
            raise ValueError("process approval TTL must be between 0 and 300 seconds")
        if max_tokens <= 0 or max_tokens > 10:
            raise ValueError("process approval token bound must be between 1 and 10")
        self._ttl_seconds = ttl_seconds
        self._max_tokens = max_tokens
        self._monotonic = monotonic
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(18))
        self._operation_id_factory = operation_id_factory or (
            lambda: f"process-release-{secrets.token_hex(8)}"
        )
        self._values: dict[str, tuple[float, ProcessReleaseApproval]] = {}
        self._lock = threading.Lock()

    def inspect(
        self,
        snapshot: ObservedSnapshot,
        *,
        observed_generation: str,
        phase: ReleasePhase,
        graceful_evidence: GracefulReleaseEvidence | None = None,
        parent_operation_id: str = "",
    ) -> ProcessReleasePreview:
        """Build a redacted preview without creating executable authority."""
        targets, _ = self._validate_candidate(
            snapshot,
            observed_generation=observed_generation,
            phase=phase,
            graceful_evidence=graceful_evidence,
            parent_operation_id=parent_operation_id,
        )
        return self._preview(
            snapshot,
            token="",
            phase=phase,
            targets=targets,
        )

    def issue(
        self,
        snapshot: ObservedSnapshot,
        *,
        observed_generation: str,
        phase: ReleasePhase,
        graceful_evidence: GracefulReleaseEvidence | None = None,
        parent_operation_id: str = "",
    ) -> ProcessReleasePreview:
        targets, prior_graceful_operation_id = self._validate_candidate(
            snapshot,
            observed_generation=observed_generation,
            phase=phase,
            graceful_evidence=graceful_evidence,
            parent_operation_id=parent_operation_id,
        )
        readiness = snapshot.disconnect_readiness
        with self._lock:
            self._expire_locked()
            while len(self._values) >= self._max_tokens:
                oldest = min(self._values, key=lambda token: self._values[token][0])
                self._values.pop(oldest)
            token = self._token_factory()
            if not TOKEN_RE.fullmatch(token) or token in self._values:
                raise ValueError("process approval token generator returned an invalid token")
            operation_id = self._operation_id_factory()
            if not TOKEN_RE.fullmatch(operation_id) or any(
                item.operation_id == operation_id for _, item in self._values.values()
            ):
                raise ValueError("process release operation ID is invalid or duplicated")
            approval = ProcessReleaseApproval(
                operation_id=operation_id,
                phase=phase,
                egpu_stable_id=readiness.egpu_stable_id,
                observed_generation=observed_generation,
                client_fingerprint=_client_fingerprint(readiness.clients),
                targets=targets,
                observed_clients=_client_facts(readiness.clients),
                prior_graceful_operation_id=prior_graceful_operation_id,
                parent_operation_id=parent_operation_id,
            )
            self._values[token] = (self._monotonic(), approval)
        return self._preview(
            snapshot,
            token=token,
            phase=phase,
            targets=targets,
        )

    def consume(self, token: str) -> ProcessReleaseApproval:
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("process approval token is invalid")
        with self._lock:
            self._expire_locked()
            value = self._values.pop(token, None)
            if value is None:
                raise ValueError("process approval expired or was already used")
            return value[1]

    def _expire_locked(self) -> None:
        cutoff = self._monotonic() - self._ttl_seconds
        for token in [
            token for token, (created, _) in self._values.items() if created < cutoff
        ]:
            self._values.pop(token, None)

    @staticmethod
    def _validate_candidate(
        snapshot: ObservedSnapshot,
        *,
        observed_generation: str,
        phase: ReleasePhase,
        graceful_evidence: GracefulReleaseEvidence | None,
        parent_operation_id: str,
    ) -> tuple[tuple[ProcessReleaseTarget, ...], str]:
        readiness = snapshot.disconnect_readiness
        if parent_operation_id and not TOKEN_RE.fullmatch(parent_operation_id):
            raise ValueError("process release parent operation ID is invalid")
        if not observed_generation:
            raise ValueError("process approval observation generation is required")
        if not readiness.applicable or not readiness.egpu_stable_id:
            raise ValueError("an exact eGPU identity is required")
        if not readiness.scan_complete:
            raise ValueError("eGPU client scan must be complete")
        if readiness.storage_in_use:
            raise ValueError("eGPU storage use is non-overridable")
        targets = _eligible_targets(readiness.clients)
        if not targets:
            raise ValueError("no close-eligible eGPU user process was observed")
        if (
            parent_operation_id
            and len(targets) > MAX_SLEEP_CHILD_RELEASE_TARGETS
        ):
            raise ValueError("sleep child process target count exceeds journal capacity")
        prior_graceful_operation_id = ""
        if phase is ReleasePhase.FORCE:
            if graceful_evidence is None:
                raise ValueError("force approval requires a prior graceful attempt")
            if observed_generation == graceful_evidence.observed_generation:
                raise ValueError("force approval requires a post-graceful observation")
            if graceful_evidence.parent_operation_id != parent_operation_id:
                raise ValueError("force approval parent operation changed")
            previously_attempted = frozenset(graceful_evidence.attempted_instance_ids)
            if any(target.instance_id not in previously_attempted for target in targets):
                raise ValueError("force approval cannot add a new process target")
            prior_graceful_operation_id = graceful_evidence.operation_id
        elif graceful_evidence is not None:
            raise ValueError("graceful evidence is valid only for force approval")
        return targets, prior_graceful_operation_id

    def _preview(
        self,
        snapshot: ObservedSnapshot,
        *,
        token: str,
        phase: ReleasePhase,
        targets: tuple[ProcessReleaseTarget, ...],
    ) -> ProcessReleasePreview:
        readiness = snapshot.disconnect_readiness
        return ProcessReleasePreview(
            token=token,
            phase=phase,
            expires_in_seconds=max(1, int(self._ttl_seconds)) if token else 0,
            targets=tuple(
                ProcessReleasePreviewRow(target.name, target.resources)
                for target in targets
            ),
            protected_client_count=len(readiness.clients) - len(targets),
        )


def revalidate_process_release(
    approval: ProcessReleaseApproval,
    snapshot: ObservedSnapshot,
    *,
    observed_generation: str,
) -> tuple[ProcessReleaseTarget, ...]:
    readiness = snapshot.disconnect_readiness
    if not observed_generation or observed_generation == approval.observed_generation:
        raise ValueError("a fresh observation is required before process release")
    if not readiness.applicable or not readiness.scan_complete:
        raise ValueError("fresh eGPU client evidence is incomplete")
    if readiness.egpu_stable_id != approval.egpu_stable_id:
        raise ValueError("eGPU identity changed after approval")
    if readiness.storage_in_use:
        raise ValueError("eGPU storage use is non-overridable")
    if _client_fingerprint(readiness.clients) != approval.client_fingerprint:
        raise ValueError("eGPU client evidence changed after approval")
    current_targets = _eligible_targets(readiness.clients)
    if frozenset(current_targets) != frozenset(approval.targets):
        raise ValueError("eligible process instances changed after approval")
    return approval.targets


def revalidate_process_release_target(
    approval: ProcessReleaseApproval,
    snapshot: ObservedSnapshot,
    *,
    observed_generation: str,
    previous_generation: str,
    target: ProcessReleaseTarget,
) -> ProcessReleaseTarget | None:
    """Revalidate one remaining target after every preceding action.

    A target that exited as a side effect of an earlier graceful action is a
    safe no-op. Any new or changed client fact invalidates the approval.
    """
    readiness = snapshot.disconnect_readiness
    if not observed_generation or observed_generation == previous_generation:
        raise ValueError("a fresh observation is required before every signal")
    if not readiness.applicable or not readiness.scan_complete:
        raise ValueError("fresh eGPU client evidence is incomplete")
    if readiness.egpu_stable_id != approval.egpu_stable_id:
        raise ValueError("eGPU identity changed after approval")
    if readiness.storage_in_use:
        raise ValueError("eGPU storage use is non-overridable")
    approved_facts = frozenset(approval.observed_clients)
    current_facts = frozenset(_client_facts(readiness.clients))
    if not current_facts.issubset(approved_facts):
        raise ValueError("new or changed eGPU client evidence invalidated approval")
    matches = tuple(
        item
        for item in _eligible_targets(readiness.clients)
        if item.instance_id == target.instance_id
    )
    if not matches:
        return None
    if len(matches) != 1 or matches[0] != target:
        raise ValueError("approved process instance changed before signal")
    return matches[0]


def revalidate_process_release_rescan(
    approval: ProcessReleaseApproval,
    snapshot: ObservedSnapshot,
    *,
    observed_generation: str,
    previous_generation: str,
) -> None:
    """Validate the mandatory observation immediately after one signal."""
    readiness = snapshot.disconnect_readiness
    if not observed_generation or observed_generation == previous_generation:
        raise ValueError("a fresh observation is required after every signal")
    if not readiness.applicable or not readiness.scan_complete:
        raise ValueError("post-signal eGPU client evidence is incomplete")
    if readiness.egpu_stable_id != approval.egpu_stable_id:
        raise ValueError("eGPU identity changed after signal")
    if readiness.storage_in_use:
        raise ValueError("eGPU storage use is non-overridable")
    approved_facts = frozenset(approval.observed_clients)
    current_facts = frozenset(_client_facts(readiness.clients))
    if not current_facts.issubset(approved_facts):
        raise ValueError("new or changed eGPU client evidence appeared after signal")
