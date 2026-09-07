from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.application.experimental_transition import (  # noqa: E402
    ExperimentalTransitionApprovalStore,
)
from hdm.domain.control_plane import PlacementState  # noqa: E402


class ExperimentalTransitionApprovalTests(unittest.TestCase):
    def make_store(self, now):
        return ExperimentalTransitionApprovalStore(
            ttl_seconds=5,
            monotonic=lambda: now[0],
            token_factory=lambda: "experimental_token_0001",
        )

    def issue(self, store, confirmed=True):
        return store.issue(
            plan_id="operation-1",
            observed_generation="generation-1",
            target_placement=PlacementState.DOCKED_EGPU,
            host_profile_id="asus-rog-ally-x",
            egpu_profile_id="gpd-g1-rx7600mxt-titan-ridge",
            egpu_stable_id="gpd-g1:0123456789abcdef",
            user_confirmed=confirmed,
        )

    def test_consent_is_required_and_permit_is_exact_single_use(self):
        now = [10.0]
        store = self.make_store(now)
        with self.assertRaisesRegex(ValueError, "explicit consent"):
            self.issue(store, confirmed=False)
        token = self.issue(store)
        permit = store.consume(token)
        self.assertEqual(permit.plan_id, "operation-1")
        self.assertEqual(permit.portable_trial_schema_version, 1)
        self.assertEqual(permit.observed_generation, "generation-1")
        self.assertEqual(permit.egpu_stable_id, "gpd-g1:0123456789abcdef")
        with self.assertRaisesRegex(ValueError, "already used"):
            store.consume(token)

    def test_wrong_token_does_not_destroy_valid_approval(self):
        now = [10.0]
        store = self.make_store(now)
        token = self.issue(store)
        with self.assertRaises(ValueError):
            store.consume("experimental_token_9999")
        self.assertEqual(store.consume(token).permit_id, token)

    def test_expired_approval_fails_closed(self):
        now = [10.0]
        store = self.make_store(now)
        token = self.issue(store)
        now[0] = 15.0
        with self.assertRaisesRegex(ValueError, "expired"):
            store.consume(token)

    def test_schema_two_cannot_be_added_to_nontrial_permit(self):
        store=self.make_store([10.0])
        permit=store.consume(self.issue(store))
        for schema in (2, True, '2', 3):
            with self.assertRaises(ValueError):
                replace(permit,portable_trial_schema_version=schema)


if __name__ == "__main__":
    unittest.main()
