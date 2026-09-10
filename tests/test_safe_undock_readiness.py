from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.models import GameState  # noqa: E402
from regear.domain.safe_undock_readiness import (  # noqa: E402
    SafeUndockEvidence,
    SafeUndockFact,
    SafeUndockReadinessState,
    assess_safe_undock_readiness,
)


def fact(value=True, verified=True, generation="generation-1", sample_id="sample-1"):
    return SafeUndockFact(value, verified, generation, sample_id)


def evidence(**changes):
    value = SafeUndockEvidence(
        attachment_binding="opaque-attach-1",
        generation="generation-1",
        sample_id="sample-1",
        game_state=GameState.IDLE,
        exact_attachment=fact(),
        topology_exact=fact(),
        client_scan_complete=fact(),
        clients_clear=fact(),
        portable_display_active=fact(),
        portable_render_gpu=fact(),
        portable_audio_active=fact(),
        builtin_controller_active=fact(),
        external_display_active=fact(False),
    )
    return replace(value, **changes)


class SafeUndockReadinessTests(unittest.TestCase):
    def assess(self, value):
        return assess_safe_undock_readiness(
            value,
            expected_attachment_binding="opaque-attach-1",
            expected_generation="generation-1",
            expected_sample_id="sample-1",
        )

    def test_complete_portable_evidence_is_ready_only_for_revalidation(self):
        result = self.assess(evidence())

        self.assertEqual(result.state, SafeUndockReadinessState.READY_FOR_REVALIDATION)
        self.assertEqual(result.code, "safe_undock.ready_for_revalidation")
        self.assertEqual(result.revalidation.observed_sample_id, "sample-1")

    def test_protected_or_incomplete_client_scan_never_appears_ready(self):
        for value, state, code in (
            (
                evidence(client_scan_complete=fact(None, False)),
                SafeUndockReadinessState.EVIDENCE_INSUFFICIENT,
                "safe_undock.client_scan_incomplete",
            ),
            (
                evidence(clients_clear=fact(False, True)),
                SafeUndockReadinessState.NOT_READY,
                "safe_undock.clients_active_or_protected",
            ),
        ):
            with self.subTest(code=code):
                result = self.assess(value)
                self.assertEqual(result.state, state)
                self.assertEqual(result.code, code)
                self.assertIsNone(result.revalidation)

    def test_game_and_portable_fallback_gates_fail_closed(self):
        for value, state, code in (
            (evidence(game_state=GameState.RUNNING), SafeUndockReadinessState.NOT_READY, "safe_undock.game_running"),
            (evidence(game_state=GameState.UNKNOWN), SafeUndockReadinessState.EVIDENCE_INSUFFICIENT, "safe_undock.game_state_unknown"),
            (evidence(portable_audio_active=fact(False, True)), SafeUndockReadinessState.NOT_READY, "safe_undock.portable_audio_unverified"),
        ):
            with self.subTest(code=code):
                result = self.assess(value)
                self.assertEqual(result.state, state)
                self.assertEqual(result.code, code)

    def test_topology_display_staleness_and_binding_change_invalidate_or_block(self):
        cases = (
            (evidence(topology_exact=fact(None, False)), SafeUndockReadinessState.EVIDENCE_INSUFFICIENT, "safe_undock.topology_unverified"),
            (
                evidence(external_display_active=fact(True, True)),
                SafeUndockReadinessState.EVIDENCE_INSUFFICIENT,
                "safe_undock.display_contradictory",
            ),
            (
                evidence(portable_render_gpu=fact(sample_id="other")),
                SafeUndockReadinessState.INVALIDATED,
                "safe_undock.evidence_stale_or_inconsistent",
            ),
            (
                evidence(attachment_binding="opaque-attach-2"),
                SafeUndockReadinessState.INVALIDATED,
                "safe_undock.attachment_changed",
            ),
        )
        for value, state, code in cases:
            with self.subTest(code=code):
                result = self.assess(value)
                self.assertEqual(result.state, state)
                self.assertEqual(result.code, code)


if __name__ == "__main__":
    unittest.main()
