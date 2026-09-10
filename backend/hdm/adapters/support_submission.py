"""Fixed HTTPS adapter for an explicitly approved support bundle.

This adapter is dormant.  Production delivery does not construct it and no
endpoint is shipped with Re-Gear.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from ..application.support_submission import parse_support_submission_response
from ..domain.support_submission import (
    ApprovedSupportUpload,
    SupportSubmissionResult,
)


MAX_SUBMISSION_RESPONSE_BYTES = 1024
DNS_HOST_RE = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
)
PATH_RE = re.compile(r"/[A-Za-z0-9][A-Za-z0-9/_-]{0,126}")


class SupportSubmissionAdapterError(RuntimeError):
    """Categorical failure that never includes a URL or remote response body."""

    def __init__(self, code: str) -> None:
        if not re.fullmatch(r"support_submission\.[a-z_]{1,48}", code):
            raise ValueError("support submission error code is invalid")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FixedHttpsEndpoint:
    host: str
    path: str

    @classmethod
    def parse(cls, value: str) -> "FixedHttpsEndpoint":
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError("support endpoint port is invalid") from error
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or parsed.query
            or parsed.fragment
            or not parsed.hostname
            or not DNS_HOST_RE.fullmatch(parsed.hostname)
            or not PATH_RE.fullmatch(parsed.path)
            or "//" in parsed.path
            or "/../" in f"{parsed.path}/"
        ):
            raise ValueError("support endpoint must be one fixed public HTTPS URL")
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            pass
        else:
            raise ValueError("support endpoint must use a DNS hostname")
        return cls(parsed.hostname.casefold(), parsed.path)


@dataclass(frozen=True, slots=True)
class BoundedHttpsResponse:
    status: int
    content_type: str
    body: bytes


class HttpsPostTransport(Protocol):
    def post(
        self,
        *,
        endpoint: FixedHttpsEndpoint,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> BoundedHttpsResponse: ...


class StandardLibraryHttpsTransport:
    """One verified TLS POST with no redirect behavior or credential support."""

    def post(
        self,
        *,
        endpoint: FixedHttpsEndpoint,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> BoundedHttpsResponse:
        connection = http.client.HTTPSConnection(
            endpoint.host,
            443,
            timeout=timeout_seconds,
            context=ssl.create_default_context(),
        )
        try:
            connection.request("POST", endpoint.path, body=body, headers=dict(headers))
            response = connection.getresponse()
            content_length = response.getheader("Content-Length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except ValueError:
                    raise SupportSubmissionAdapterError(
                        "support_submission.response_invalid"
                    ) from None
                if declared_length < 0 or declared_length > MAX_SUBMISSION_RESPONSE_BYTES:
                    raise SupportSubmissionAdapterError(
                        "support_submission.response_too_large"
                    )
            response_body = response.read(MAX_SUBMISSION_RESPONSE_BYTES + 1)
            if len(response_body) > MAX_SUBMISSION_RESPONSE_BYTES:
                raise SupportSubmissionAdapterError(
                    "support_submission.response_too_large"
                )
            return BoundedHttpsResponse(
                status=response.status,
                content_type=response.getheader("Content-Type", ""),
                body=response_body,
            )
        finally:
            connection.close()


class FixedHttpsSupportSubmissionAdapter:
    def __init__(
        self,
        endpoint: str,
        *,
        transport: HttpsPostTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 15:
            raise ValueError("support submission timeout must be between 0 and 15 seconds")
        self._endpoint = FixedHttpsEndpoint.parse(endpoint)
        self._transport = transport or StandardLibraryHttpsTransport()
        self._timeout_seconds = timeout_seconds

    def submit(self, upload: ApprovedSupportUpload) -> SupportSubmissionResult:
        headers = {
            "Accept": "application/json",
            "Content-Type": upload.content_type,
            "Content-Length": str(upload.size_bytes),
            "X-HDM-Content-SHA256": upload.sha256,
        }
        try:
            response = self._transport.post(
                endpoint=self._endpoint,
                headers=headers,
                body=upload.body,
                timeout_seconds=self._timeout_seconds,
            )
        except SupportSubmissionAdapterError:
            raise
        except Exception:
            raise SupportSubmissionAdapterError(
                "support_submission.transport_failed"
            ) from None
        if response.status != 200:
            raise SupportSubmissionAdapterError("support_submission.http_rejected")
        if response.content_type != "application/json":
            raise SupportSubmissionAdapterError("support_submission.response_invalid")
        if len(response.body) > MAX_SUBMISSION_RESPONSE_BYTES:
            raise SupportSubmissionAdapterError("support_submission.response_too_large")
        try:
            decoded = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SupportSubmissionAdapterError(
                "support_submission.response_invalid"
            ) from None
        if not isinstance(decoded, dict):
            raise SupportSubmissionAdapterError("support_submission.response_invalid")
        try:
            return parse_support_submission_response(decoded)
        except ValueError:
            raise SupportSubmissionAdapterError(
                "support_submission.response_invalid"
            ) from None
