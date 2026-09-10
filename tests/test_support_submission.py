from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.support_bundle import SupportBundle  # noqa: E402
from regear.application.support_submission import (  # noqa: E402
    SupportSubmissionApprovalStore,
    parse_support_submission_response,
)
from regear.domain.support_submission import ApprovedSupportUpload  # noqa: E402


def bundle(text: str = '{"schema_version":2}') -> SupportBundle:
    return SupportBundle(
        payload={"schema_version": 2},
        json_text=text,
        size_bytes=len(text.encode("utf-8")),
        event_count=0,
    )


class SupportSubmissionTests(unittest.TestCase):
    def test_separate_consent_binds_single_use_token_to_exact_reviewed_bytes(self):
        now = [10.0]
        store = SupportSubmissionApprovalStore(
            monotonic=lambda: now[0],
            token_factory=lambda: "submission_token_0001",
        )
        with self.assertRaisesRegex(ValueError, "separate explicit consent"):
            store.issue(bundle(), user_confirmed=False)
        approval = store.issue(bundle(), user_confirmed=True)
        upload = store.consume(approval.token)
        self.assertEqual(upload.body, bundle().json_text.encode("utf-8"))
        self.assertEqual(upload.content_type, "application/json")
        self.assertEqual(upload.sha256, hashlib.sha256(upload.body).hexdigest())
        with self.assertRaisesRegex(ValueError, "already used"):
            store.consume(approval.token)

    def test_approval_expires_and_arbitrary_tokens_are_rejected(self):
        now = [10.0]
        store = SupportSubmissionApprovalStore(
            ttl_seconds=5,
            monotonic=lambda: now[0],
            token_factory=lambda: "submission_token_0001",
        )
        approval = store.issue(bundle(), user_confirmed=True)
        now[0] = 15.0
        with self.assertRaisesRegex(ValueError, "expired"):
            store.consume(approval.token)
        with self.assertRaisesRegex(ValueError, "invalid"):
            store.consume("https://attacker.invalid/upload")

    def test_bundle_size_or_byte_mismatch_fails_before_approval(self):
        store = SupportSubmissionApprovalStore(
            token_factory=lambda: "submission_token_0001"
        )
        altered = SupportBundle(
            payload={},
            json_text="{}",
            size_bytes=999,
            event_count=0,
        )
        with self.assertRaisesRegex(ValueError, "reviewed size"):
            store.issue(altered, user_confirmed=True)

    def test_upload_value_revalidates_checksum_and_content_type(self):
        body = b"{}"
        digest = hashlib.sha256(body).hexdigest()
        with self.assertRaisesRegex(ValueError, "content type"):
            ApprovedSupportUpload(body, "text/html", len(body), digest)
        with self.assertRaisesRegex(ValueError, "checksum"):
            ApprovedSupportUpload(body, "application/json", len(body), "0" * 64)

    def test_worker_response_is_strict_and_contains_only_server_report_id(self):
        result = parse_support_submission_response(
            {"ok": True, "report_id": "HDM-8F3A21"}
        )
        self.assertEqual(result.report_id, "HDM-8F3A21")
        invalid = (
            {"ok": True, "report_id": "../../secret"},
            {"ok": True, "report_id": "HDM-8F3A21", "url": "https://example"},
            {"ok": False, "report_id": "HDM-8F3A21"},
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_support_submission_response(payload)

    def test_a_renamed_report_id_is_accepted_without_widening_the_format(self):
        """The endpoint issues these ids, so both prefixes must parse.

        The test above already pins the legacy ``HDM-`` prefix, which is the
        half that matters for a server that may still be handing out ids
        issued before the rename. This one pins the other half: the new
        prefix works, and accepting it did not turn the pattern into a
        wildcard that lets an arbitrary prefix through.
        """
        result = parse_support_submission_response(
            {"ok": True, "report_id": "RG-8F3A21"}
        )
        self.assertEqual(result.report_id, "RG-8F3A21")
        rejected = (
            "XX-8F3A21",
            "-8F3A21",
            "8F3A21",
            "RGHDM-8F3A21",
            "RG-8f3a21",
        )
        for report_id in rejected:
            with self.subTest(report_id=report_id):
                with self.assertRaises(ValueError):
                    parse_support_submission_response(
                        {"ok": True, "report_id": report_id}
                    )

    def test_approval_contract_contains_no_endpoint_or_credentials(self):
        approval = SupportSubmissionApprovalStore(
            token_factory=lambda: "submission_token_0001"
        ).issue(bundle(), user_confirmed=True)
        text = repr(approval)
        self.assertNotIn("http", text)
        self.assertNotIn("r2", text.casefold())
        self.assertNotIn("credential", text.casefold())


if __name__ == "__main__":
    unittest.main()
