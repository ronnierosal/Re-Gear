"""Dormant explicit approval contract for a future fixed support endpoint."""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ..domain.support_submission import (
    MAX_SUPPORT_UPLOAD_BYTES,
    ApprovedSupportUpload,
    SupportSubmissionResult,
)
from .support_bundle import SupportBundle


APPROVAL_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,96}$")
#: Report ids are issued by the support endpoint, not by us, so this parses
#: what a server returns. The endpoint is still dormant, but if one is ever
#: stood up it may keep issuing ``HDM-`` ids that were handed out earlier,
#: so the legacy prefix stays accepted. Removal criterion: a shipped
#: endpoint that has never issued an ``HDM-`` id.
REPORT_ID_RE = re.compile(r"^(?:RG|HDM)-[A-Z0-9]{6,16}$")


@dataclass(frozen=True, slots=True)
class SupportSubmissionApproval:
    token: str
    size_bytes: int
    sha256: str


class SupportSubmissionApprovalStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = 300,
        max_approvals: int = 3,
        monotonic: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or ttl_seconds > 300:
            raise ValueError("support submission TTL must be between 0 and 300 seconds")
        if max_approvals <= 0 or max_approvals > 3:
            raise ValueError("support submission approval count must be between 1 and 3")
        self._ttl_seconds = ttl_seconds
        self._max_approvals = max_approvals
        self._monotonic = monotonic
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(18))
        self._approvals: dict[str, tuple[float, bytes, str]] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        bundle: SupportBundle,
        *,
        user_confirmed: bool,
    ) -> SupportSubmissionApproval:
        if not user_confirmed:
            raise ValueError("support submission requires separate explicit consent")
        body = bundle.json_text.encode("utf-8")
        if len(body) != bundle.size_bytes or not (
            0 < len(body) <= MAX_SUPPORT_UPLOAD_BYTES
        ):
            raise ValueError("support bundle bytes do not match their reviewed size")
        digest = hashlib.sha256(body).hexdigest()
        with self._lock:
            self._expire_locked()
            while len(self._approvals) >= self._max_approvals:
                oldest = min(self._approvals, key=lambda key: self._approvals[key][0])
                self._approvals.pop(oldest)
            token = self._token_factory()
            if not APPROVAL_TOKEN_RE.fullmatch(token):
                raise ValueError("support submission token generator returned an invalid token")
            if token in self._approvals:
                raise ValueError("support submission token generator returned a duplicate token")
            self._approvals[token] = (self._monotonic(), body, digest)
        return SupportSubmissionApproval(token, len(body), digest)

    def consume(self, token: str) -> ApprovedSupportUpload:
        if not APPROVAL_TOKEN_RE.fullmatch(token):
            raise ValueError("support submission approval token is invalid")
        with self._lock:
            self._expire_locked()
            value = self._approvals.pop(token, None)
        if value is None:
            raise ValueError("support submission approval expired or was already used")
        _, body, digest = value
        return ApprovedSupportUpload(
            body=body,
            content_type="application/json",
            size_bytes=len(body),
            sha256=digest,
        )

    def _expire_locked(self) -> None:
        cutoff = self._monotonic() - self._ttl_seconds
        expired = [
            token
            for token, (created, _, _) in self._approvals.items()
            if created <= cutoff
        ]
        for token in expired:
            self._approvals.pop(token, None)


def parse_support_submission_response(
    payload: Mapping[str, object],
) -> SupportSubmissionResult:
    if set(payload) != {"ok", "report_id"} or payload.get("ok") is not True:
        raise ValueError("support submission response shape is invalid")
    report_id = payload.get("report_id")
    if not isinstance(report_id, str) or not REPORT_ID_RE.fullmatch(report_id):
        raise ValueError("support submission report ID is invalid")
    return SupportSubmissionResult(report_id)
