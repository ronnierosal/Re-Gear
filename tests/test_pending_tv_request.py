from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.control_plane import RequestSource  # noqa: E402
from hdm.domain.models import (  # noqa: E402
    Confidence,
    DisplayKind,
    DisplayObservation,
)
from hdm.domain.pending_tv_request import (  # noqa: E402
    PendingTvHandoff,
    PendingTvRequest,
    PendingTvResolution,
    PendingTvState,
    cancel_pending_tv_request,
    create_pending_tv_request,
    evaluate_pending_tv_request,
)
from hdm.domain.saved_tv import SavedTvProfile  # noqa: E402


ATTACHMENT = "egpu:e3b0c44298fc1c14"
GENERATION = "observation-41"

PROFILE = SavedTvProfile(
    display_stable_id="display:9f2c41ab77e0d135",
    edid_identified=True,
    label="Living room TV",
)

TV = DisplayObservation(
    stable_id="display:9f2c41ab77e0d135",
    kind=DisplayKind.EXTERNAL,
    connector="HDMI-A-1",
    connected=True,
    active=False,
    edid_ready=True,
    confidence=Confidence.VERIFIED,
)

OTHER_TV = DisplayObservation(
    stable_id="display:5511aa22bb33cc44",
    kind=DisplayKind.EXTERNAL,
    connector="HDMI-A-2",
    connected=True,
    active=False,
    edid_ready=True,
    confidence=Confidence.VERIFIED,
)

PANEL = DisplayObservation(
    stable_id="internal-panel",
    kind=DisplayKind.INTERNAL,
    connector="eDP-1",
    connected=True,
    active=True,
    edid_ready=True,
    confidence=Confidence.VERIFIED,
)


def bound_request(**overrides) -> PendingTvRequest:
    values = {
        "request_id": "request-7f21",
        "source": RequestSource.MANUAL,
        "attachment_binding": ATTACHMENT,
        "display_stable_id": PROFILE.display_stable_id,
        "edid_identified": True,
        "label": PROFILE.label,
    }
    values.update(overrides)
    return PendingTvRequest(**values)


def evaluate(request, **overrides) -> PendingTvResolution:
    values = {
        "attachment_binding": ATTACHMENT,
        "displays": (PANEL,),
        "scan_complete": True,
        "observed_generation": GENERATION,
    }
    values.update(overrides)
    return evaluate_pending_tv_request(request, **values)


class CreateRequestTests(unittest.TestCase):
    def test_request_binds_to_the_remembered_panel(self):
        resolution = create_pending_tv_request(
            request_id="request-7f21",
            source=RequestSource.MANUAL,
            attachment_binding=ATTACHMENT,
            saved_profile=PROFILE,
            saved_record_readable=True,
        )

        self.assertIs(resolution.state, PendingTvState.WAITING)
        self.assertEqual(resolution.code, "pending_tv.requested")
        self.assertIsNotNone(resolution.request)
        self.assertTrue(resolution.request.bound)
        self.assertEqual(
            resolution.request.display_stable_id, PROFILE.display_stable_id
        )
        self.assertTrue(resolution.request.edid_identified)
        self.assertIsNone(resolution.handoff)

    def test_request_with_nothing_remembered_is_unbound(self):
        resolution = create_pending_tv_request(
            request_id="request-7f21",
            source=RequestSource.MANUAL,
            attachment_binding=ATTACHMENT,
            saved_profile=None,
            saved_record_readable=True,
        )

        self.assertIs(resolution.state, PendingTvState.WAITING)
        self.assertFalse(resolution.request.bound)

    def test_unreadable_record_refuses_rather_than_binding_to_anything(self):
        resolution = create_pending_tv_request(
            request_id="request-7f21",
            source=RequestSource.MANUAL,
            attachment_binding=ATTACHMENT,
            saved_profile=None,
            saved_record_readable=False,
        )

        self.assertIs(resolution.state, PendingTvState.REJECTED)
        self.assertEqual(resolution.code, "pending_tv.record_unreadable")
        self.assertIsNone(resolution.request)

    def test_request_without_an_exact_attachment_is_refused(self):
        resolution = create_pending_tv_request(
            request_id="request-7f21",
            source=RequestSource.MANUAL,
            attachment_binding="",
            saved_profile=PROFILE,
            saved_record_readable=True,
        )

        self.assertIs(resolution.state, PendingTvState.REJECTED)
        self.assertEqual(resolution.code, "pending_tv.attachment_unknown")

    def test_automatic_source_cannot_mint_a_player_intent(self):
        resolution = create_pending_tv_request(
            request_id="request-7f21",
            source=RequestSource.AUTOMATIC,
            attachment_binding=ATTACHMENT,
            saved_profile=PROFILE,
            saved_record_readable=True,
        )

        self.assertIs(resolution.state, PendingTvState.REJECTED)
        self.assertEqual(resolution.code, "pending_tv.automatic_source_rejected")

    def test_request_identities_are_required(self):
        with self.assertRaises(ValueError):
            bound_request(request_id="")
        with self.assertRaises(ValueError):
            bound_request(attachment_binding="")
        with self.assertRaises(ValueError):
            bound_request(display_stable_id="", edid_identified=True)

    def test_cancel_is_terminal_and_carries_no_request(self):
        resolution = cancel_pending_tv_request(bound_request())

        self.assertIs(resolution.state, PendingTvState.CANCELLED)
        self.assertEqual(resolution.code, "pending_tv.cancelled")
        self.assertIsNone(resolution.request)
        self.assertFalse(resolution.outstanding)


class WaitingTests(unittest.TestCase):
    def test_absent_tv_waits_on_a_finished_look(self):
        resolution = evaluate(bound_request())

        self.assertIs(resolution.state, PendingTvState.WAITING)
        self.assertEqual(resolution.code, "pending_tv.awaiting_display")
        self.assertTrue(resolution.outstanding)
        self.assertIsNone(resolution.handoff)

    def test_late_hdmi_becomes_ready_after_waiting(self):
        request = bound_request()
        for attempt in range(5):
            waiting = evaluate(request, attempts=attempt)
            self.assertIs(waiting.state, PendingTvState.WAITING)

        resolution = evaluate(request, displays=(PANEL, TV), attempts=5)

        self.assertIs(resolution.state, PendingTvState.READY)
        self.assertEqual(resolution.code, "pending_tv.ready")
        self.assertIsNotNone(resolution.handoff)
        self.assertEqual(resolution.handoff.display_stable_id, TV.stable_id)
        self.assertEqual(resolution.handoff.observed_generation, GENERATION)
        self.assertEqual(resolution.handoff.attachment_binding, ATTACHMENT)
        self.assertEqual(resolution.handoff.request_id, "request-7f21")

    def test_waiting_settles_into_not_found_after_the_budget(self):
        resolution = evaluate(bound_request(), attempts=4, max_attempts=4)

        self.assertIs(resolution.state, PendingTvState.NOT_FOUND)
        self.assertEqual(resolution.code, "pending_tv.not_found")
        self.assertTrue(resolution.outstanding)

    def test_settling_keeps_a_reason_that_is_not_mere_absence(self):
        disconnected = replace(TV, connected=False, confidence=Confidence.OBSERVED)
        resolution = evaluate(
            bound_request(), displays=(disconnected,), attempts=4, max_attempts=4
        )

        self.assertIs(resolution.state, PendingTvState.NOT_FOUND)
        self.assertEqual(resolution.code, "pending_tv.connection_unverified")

    def test_a_requested_identity_reporting_internal_is_contradicted(self):
        contradicted = replace(TV, kind=DisplayKind.INTERNAL)
        resolution = evaluate(bound_request(), displays=(contradicted,))

        self.assertIs(resolution.state, PendingTvState.WAITING)
        self.assertEqual(resolution.code, "pending_tv.identity_contradicted")

    def test_an_uncorroborated_reading_is_not_a_tv_to_switch_to(self):
        observed = replace(TV, confidence=Confidence.OBSERVED)
        resolution = evaluate(bound_request(), displays=(observed,))

        self.assertIs(resolution.state, PendingTvState.WAITING)
        self.assertEqual(resolution.code, "pending_tv.connection_unverified")

    def test_an_unreadable_connection_is_not_a_tv_to_switch_to(self):
        unreadable = replace(TV, connected=None)
        resolution = evaluate(bound_request(), displays=(unreadable,))

        self.assertIs(resolution.state, PendingTvState.WAITING)
        self.assertEqual(resolution.code, "pending_tv.connection_unverified")


class FailedScanTests(unittest.TestCase):
    def test_an_unfinished_look_cannot_tell(self):
        resolution = evaluate(bound_request(), scan_complete=False)

        self.assertIs(resolution.state, PendingTvState.UNOBSERVABLE)
        self.assertEqual(resolution.code, "pending_tv.display_scan_incomplete")
        self.assertTrue(resolution.outstanding)

    def test_repeated_failed_scans_never_reach_not_found(self):
        request = bound_request()
        for _ in range(40):
            resolution = evaluate(request, scan_complete=False, attempts=0)
            self.assertIs(resolution.state, PendingTvState.UNOBSERVABLE)

    def test_a_matched_tv_without_a_generation_cannot_be_handed_off(self):
        resolution = evaluate(
            bound_request(), displays=(PANEL, TV), observed_generation=""
        )

        self.assertIs(resolution.state, PendingTvState.UNOBSERVABLE)
        self.assertEqual(resolution.code, "pending_tv.observation_unavailable")
        self.assertIsNone(resolution.handoff)


class IdentityGradeTests(unittest.TestCase):
    def test_a_connector_derived_request_ends_on_the_first_look(self):
        request = bound_request(edid_identified=False)
        resolution = evaluate(request, displays=(PANEL, TV), attempts=0)

        self.assertIs(resolution.state, PendingTvState.NOT_FOUND)
        self.assertEqual(resolution.code, "pending_tv.identity_not_verifiable")
        self.assertIsNone(resolution.handoff)

    def test_a_connector_derived_request_is_settled_before_the_scan_question(self):
        request = bound_request(edid_identified=False)
        resolution = evaluate(request, scan_complete=False)

        self.assertIs(resolution.state, PendingTvState.NOT_FOUND)
        self.assertEqual(resolution.code, "pending_tv.identity_not_verifiable")


class UnboundRequestTests(unittest.TestCase):
    def test_one_verified_external_display_satisfies_an_unbound_request(self):
        request = bound_request(display_stable_id="", edid_identified=False, label="")
        resolution = evaluate(request, displays=(PANEL, TV))

        self.assertIs(resolution.state, PendingTvState.READY)
        self.assertEqual(resolution.handoff.display_stable_id, TV.stable_id)

    def test_two_candidates_are_reported_as_cannot_tell(self):
        request = bound_request(display_stable_id="", edid_identified=False, label="")
        resolution = evaluate(request, displays=(PANEL, TV, OTHER_TV))

        self.assertIs(resolution.state, PendingTvState.UNOBSERVABLE)
        self.assertEqual(resolution.code, "pending_tv.target_ambiguous")
        self.assertIsNone(resolution.handoff)

    def test_a_candidate_without_edid_identity_is_not_a_panel(self):
        socket = replace(TV, edid_ready=False)
        request = bound_request(display_stable_id="", edid_identified=False, label="")
        resolution = evaluate(request, displays=(PANEL, socket))

        self.assertIs(resolution.state, PendingTvState.WAITING)
        self.assertEqual(resolution.code, "pending_tv.awaiting_display")


class ChangedDockTests(unittest.TestCase):
    def test_a_different_attachment_invalidates_rather_than_retargets(self):
        resolution = evaluate(
            bound_request(),
            attachment_binding="egpu:1111222233334444",
            displays=(PANEL, TV),
        )

        self.assertIs(resolution.state, PendingTvState.INVALIDATED)
        self.assertEqual(resolution.code, "pending_tv.attachment_changed")
        self.assertIsNone(resolution.handoff)
        self.assertFalse(resolution.outstanding)

    def test_an_unidentified_attachment_ends_the_request(self):
        resolution = evaluate(
            bound_request(), attachment_binding="", displays=(PANEL, TV)
        )

        self.assertIs(resolution.state, PendingTvState.INVALIDATED)
        self.assertEqual(resolution.code, "pending_tv.attachment_absent")

    def test_a_changed_attachment_is_checked_before_any_display(self):
        # The dock question is answered first, so a new dock's TV can never be
        # matched against the previous dock's request.
        resolution = evaluate(
            bound_request(),
            attachment_binding="egpu:1111222233334444",
            displays=(PANEL, TV),
            scan_complete=True,
        )

        self.assertIs(resolution.state, PendingTvState.INVALIDATED)


class ResolutionShapeTests(unittest.TestCase):
    def test_only_a_ready_resolution_carries_a_handoff(self):
        handoff = PendingTvHandoff(
            request_id="request-7f21",
            attachment_binding=ATTACHMENT,
            observed_generation=GENERATION,
            display_stable_id=TV.stable_id,
        )
        with self.assertRaises(ValueError):
            PendingTvResolution(PendingTvState.WAITING, "x", bound_request(), handoff)
        with self.assertRaises(ValueError):
            PendingTvResolution(PendingTvState.READY, "x")

    def test_a_handoff_must_be_complete(self):
        for field in (
            "request_id",
            "attachment_binding",
            "observed_generation",
            "display_stable_id",
        ):
            values = {
                "request_id": "request-7f21",
                "attachment_binding": ATTACHMENT,
                "observed_generation": GENERATION,
                "display_stable_id": TV.stable_id,
            }
            values[field] = ""
            with self.assertRaises(ValueError):
                PendingTvHandoff(**values)

    def test_a_terminated_request_is_not_carried_forward(self):
        with self.assertRaises(ValueError):
            PendingTvResolution(
                PendingTvState.CANCELLED, "pending_tv.cancelled", bound_request()
            )

    def test_an_outstanding_state_must_carry_its_request(self):
        with self.assertRaises(ValueError):
            PendingTvResolution(PendingTvState.WAITING, "pending_tv.awaiting_display")


if __name__ == "__main__":
    unittest.main()
