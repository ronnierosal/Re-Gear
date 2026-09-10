from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.support_submission import (  # noqa: E402
    BoundedHttpsResponse,
    FixedHttpsEndpoint,
    FixedHttpsSupportSubmissionAdapter,
    StandardLibraryHttpsTransport,
    SupportSubmissionAdapterError,
)
from regear.domain.support_submission import ApprovedSupportUpload  # noqa: E402


def upload() -> ApprovedSupportUpload:
    body = b'{"schema_version":2}'
    return ApprovedSupportUpload(
        body,
        "application/json",
        len(body),
        hashlib.sha256(body).hexdigest(),
    )


class FakeTransport:
    def __init__(self, response: BoundedHttpsResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class SupportSubmissionAdapterTests(unittest.TestCase):
    def test_endpoint_is_tls_dns_only_and_contains_no_credentials_or_query(self):
        endpoint = FixedHttpsEndpoint.parse(
            "https://support.example.com/v1/hdm-reports"
        )
        self.assertEqual(endpoint.host, "support.example.com")
        invalid = (
            "http://support.example.com/v1/reports",
            "https://user:secret@support.example.com/v1/reports",
            "https://support.example.com:8443/v1/reports",
            "https://127.0.0.1/v1/reports",
            "https://localhost/v1/reports",
            "https://support.example.com/v1/reports?path=chosen",
            "https://support.example.com/v1/../admin",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                FixedHttpsEndpoint.parse(value)

    def test_exact_approved_bytes_and_checksum_are_posted_once(self):
        transport = FakeTransport(
            BoundedHttpsResponse(
                200,
                "application/json",
                b'{"ok":true,"report_id":"HDM-8F3A21"}',
            )
        )
        adapter = FixedHttpsSupportSubmissionAdapter(
            "https://support.example.com/v1/hdm-reports",
            transport=transport,
        )
        result = adapter.submit(upload())
        self.assertEqual(result.report_id, "HDM-8F3A21")
        self.assertEqual(len(transport.calls), 1)
        call = transport.calls[0]
        self.assertEqual(call["body"], upload().body)
        self.assertEqual(call["headers"]["Content-Length"], str(upload().size_bytes))
        self.assertEqual(call["headers"]["X-Re-Gear-Content-SHA256"], upload().sha256)
        self.assertNotIn("Authorization", call["headers"])

    def test_redirect_error_and_non_exact_json_are_not_followed_or_accepted(self):
        responses = (
            BoundedHttpsResponse(302, "application/json", b"{}"),
            BoundedHttpsResponse(200, "text/html", b"{}"),
            BoundedHttpsResponse(
                200,
                "application/json",
                b'{"ok":true,"report_id":"HDM-8F3A21","url":"https://private"}',
            ),
            BoundedHttpsResponse(200, "application/json", b"[1]"),
        )
        for response in responses:
            transport = FakeTransport(response)
            adapter = FixedHttpsSupportSubmissionAdapter(
                "https://support.example.com/v1/hdm-reports",
                transport=transport,
            )
            with self.subTest(response=response), self.assertRaises(
                SupportSubmissionAdapterError
            ):
                adapter.submit(upload())
            self.assertEqual(len(transport.calls), 1)

    def test_transport_failure_is_categorical_and_does_not_leak_details(self):
        class FailingTransport:
            def post(self, **kwargs):
                raise OSError("secret endpoint diagnostic")

        adapter = FixedHttpsSupportSubmissionAdapter(
            "https://support.example.com/v1/hdm-reports",
            transport=FailingTransport(),
        )
        with self.assertRaises(SupportSubmissionAdapterError) as raised:
            adapter.submit(upload())
        self.assertEqual(raised.exception.code, "support_submission.transport_failed")
        self.assertNotIn("secret", str(raised.exception))

    def test_standard_transport_is_one_post_and_bounds_response_before_return(self):
        class Response:
            status = 200

            @staticmethod
            def getheader(name, default=None):
                return {"Content-Length": "2", "Content-Type": "application/json"}.get(
                    name, default
                )

            @staticmethod
            def read(limit):
                self_limit.append(limit)
                return b"{}"

        class Connection:
            def __init__(self, *args, **kwargs):
                self.requests = []

            def request(self, *args, **kwargs):
                requests.append((args, kwargs))

            @staticmethod
            def getresponse():
                return Response()

            @staticmethod
            def close():
                closed.append(True)

        requests: list[object] = []
        self_limit: list[int] = []
        closed: list[bool] = []
        with patch(
            "regear.adapters.support_submission.http.client.HTTPSConnection",
            Connection,
        ):
            response = StandardLibraryHttpsTransport().post(
                endpoint=FixedHttpsEndpoint.parse(
                    "https://support.example.com/v1/hdm-reports"
                ),
                headers={"Content-Type": "application/json"},
                body=b"{}",
                timeout_seconds=5,
            )
        self.assertEqual(requests[0][0][:2], ("POST", "/v1/hdm-reports"))
        self.assertEqual(self_limit, [1025])
        self.assertEqual(response.body, b"{}")
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
