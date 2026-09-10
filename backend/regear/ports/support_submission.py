"""Future fixed-endpoint submission boundary; no implementation exists."""

from __future__ import annotations

from typing import Protocol

from ..domain.support_submission import (
    ApprovedSupportUpload,
    SupportSubmissionResult,
)


class SupportSubmissionPort(Protocol):
    def submit(self, upload: ApprovedSupportUpload) -> SupportSubmissionResult:
        """Submit exact approved bytes to backend-owned fixed configuration."""
