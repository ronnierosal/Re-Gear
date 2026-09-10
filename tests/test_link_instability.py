from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.link_instability import (  # noqa: E402
    LinkHealthSample,
    LinkInstabilityStatus,
    assess_link_instability,
    link_instability_to_public_dict,
)
from regear.domain.models import Confidence, EgpuLinkState  # noqa: E402


def sample(state, generation="generation-1", sample_id="sample-1", **changes):
    values = {
        "attachment_binding": "g1-binding",
        "generation": generation,
        "sample_id": sample_id,
        "applicable": True,
        "state": state,
        "confidence": Confidence.OBSERVED,
    }
    values.update(changes)
    return LinkHealthSample(**values)


class LinkInstabilityTests(unittest.TestCase):
    def setUp(self):
        self.previous = sample(EgpuLinkState.UP)
        self.current = sample(EgpuLinkState.UP, "generation-2", "sample-2")

    def assess(self, previous=None, current=None):
        return assess_link_instability(
            previous or self.previous,
            current or self.current,
            expected_attachment_binding="g1-binding",
        )

    def test_fresh_equal_observed_states_are_stable_without_quality_claim(self):
        result = self.assess()
        self.assertEqual(LinkInstabilityStatus.STABLE_OBSERVED, result.status)
        self.assertEqual(EgpuLinkState.UP, result.current_state)
        self.assertFalse(result.authorizes_action)

    def test_fresh_observed_state_change_is_an_instability_episode(self):
        result = self.assess(current=replace(self.current, state=EgpuLinkState.DOWN))
        self.assertEqual(LinkInstabilityStatus.INSTABILITY_OBSERVED, result.status)
        self.assertEqual("link_instability.state_changed", result.code)
        self.assertEqual(EgpuLinkState.DOWN, result.current_state)

    def test_unknown_or_unobserved_samples_fail_closed(self):
        for changed in (
            replace(self.current, state=EgpuLinkState.UNKNOWN),
            replace(self.current, confidence=Confidence.UNKNOWN),
            replace(self.current, applicable=False),
        ):
            with self.subTest(changed=changed):
                result = self.assess(current=changed)
                self.assertEqual(LinkInstabilityStatus.EVIDENCE_INSUFFICIENT, result.status)
                self.assertIsNone(result.current_state)

    def test_stale_or_changed_binding_fails_closed(self):
        stale = self.assess(current=replace(self.current, sample_id="sample-1"))
        self.assertEqual("link_instability.observation_not_fresh", stale.code)
        changed = self.assess(current=replace(self.current, attachment_binding="other"))
        self.assertEqual("link_instability.attachment_changed", changed.code)

    def test_public_result_redacts_binding_and_observation_identity(self):
        public = link_instability_to_public_dict(self.assess())
        self.assertEqual(public["status"], "stable_observed")
        self.assertEqual(public["current_state"], "up")
        rendered = repr(public)
        for private in ("binding", "generation", "sample"):
            self.assertNotIn(private, rendered)


if __name__ == "__main__":
    unittest.main()
