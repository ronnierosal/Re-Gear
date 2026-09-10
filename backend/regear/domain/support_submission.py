"""Pure immutable values for an exact approved support upload."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


MAX_SUPPORT_UPLOAD_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class ApprovedSupportUpload:
    body: bytes
    content_type: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if self.content_type != "application/json":
            raise ValueError("support upload content type is invalid")
        if self.size_bytes != len(self.body) or not (
            0 < self.size_bytes <= MAX_SUPPORT_UPLOAD_BYTES
        ):
            raise ValueError("support upload size is invalid")
        if hashlib.sha256(self.body).hexdigest() != self.sha256:
            raise ValueError("support upload checksum does not match")


@dataclass(frozen=True, slots=True)
class SupportSubmissionResult:
    report_id: str
