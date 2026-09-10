import unittest
from dataclasses import replace

from backend.regear.delivery.device_filter_lifecycle import (
    FilterLifecycle, LaunchBinding, OwnedFilter, Phase,
)


class FilterLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.binding = LaunchBinding("a" * 64, "trial", "gamescope-session.service",
            "b" * 32, 1000, 50, 100, 29, 1234, "c" * 64, 30.0)
        self.owner = OwnedFilter(42, "d" * 64, True, True, 43, 1234)
        self.request = FilterLifecycle(self.binding)

    def pending(self):
        return self.request.prepare_pin(replace(self.owner, survives_owner_exit=False),
                                        observed=self.binding, now=9)

    def attached(self):
        return self.pending().confirm_pin(self.owner, observed=self.binding, now=10)

    def grant(self, state=None, **changes):
        args = dict(observed=self.binding, now=11, no_game=True,
                    inherited_scan_complete=True, inherited_descriptors_free=True)
        args.update(changes)
        return (state or self.attached()).grant(**args)

    def test_request_attachment_grant_sequence(self):
        with self.assertRaises(ValueError):
            self.grant(self.request)
        self.assertEqual(self.grant().phase, Phase.GRANTED)

    def test_unknown_or_incomplete_evidence_cancels(self):
        for field in ("no_game", "inherited_scan_complete", "inherited_descriptors_free"):
            for value in (False, None, 1):
                state = self.grant(**{field: value})
                self.assertEqual(state.phase, Phase.CANCELLED)
                self.assertTrue(state.owned_detach_allowed)

    def test_crash_surviving_ownership_required(self):
        for field in ("ownership_verified", "survives_owner_exit"):
            owner = replace(self.owner, **{field: False})
            state = self.pending().confirm_pin(owner, observed=self.binding, now=10)
            self.assertEqual(state.phase, Phase.CANCELLED)
        self.assertTrue(state.owned_detach_allowed)  # verified but ephemeral owner

    def test_deadline_and_changed_invocation_invalidate(self):
        for observation, now in ((self.binding, 30), (self.binding, float("nan")),
                                 (None, 11), (replace(self.binding, invocation="e" * 32), 11)):
            self.assertEqual(self.grant(observed=observation, now=now).phase, Phase.CANCELLED)
        self.assertEqual(self.grant().revalidate(None, now=12).phase, Phase.RECOVERY_REQUIRED)

    def test_before_grant_cancellation_can_only_detach_verified_owner(self):
        self.assertFalse(self.request.cancel().owned_detach_allowed)
        self.assertTrue(self.attached().cancel().owned_detach_allowed)
        state = self.request.prepare_pin(replace(self.owner, ownership_verified=False, survives_owner_exit=False),
                                    observed=self.binding, now=10)
        self.assertFalse(state.owned_detach_allowed)

    def test_after_grant_cancellation_or_crash_preserves_recovery_requirement(self):
        for state in (self.grant().cancel(), self.grant().after_crash()):
            self.assertEqual(state.phase, Phase.RECOVERY_REQUIRED)
            self.assertFalse(state.owned_detach_allowed)
            self.assertEqual(state.cancel(), state)
        self.assertEqual(self.attached().after_crash().phase, Phase.CANCELLED)

    def test_consumed_or_cancelled_state_cannot_replay(self):
        for state in (self.grant(), self.attached().cancel(), self.grant().after_crash()):
            with self.assertRaises(ValueError):
                self.grant(state)
            with self.assertRaises(ValueError):
                state.attach(self.owner, observed=self.binding, now=12)

    def test_invalid_binding_rejected(self):
        for field, value in (("deadline", float("inf")), ("deadline", True),
                             ("uid", 0), ("pid", True), ("unit", "user@1000.service"),
                             ("invocation", "bad"), ("topology_hash", "bad")):
            with self.assertRaises(ValueError):
                replace(self.binding, **{field: value})

    def test_reconstructed_active_state_requires_recoverable_owner(self):
        for phase in (Phase.ATTACHED, Phase.GRANTED, Phase.RECOVERY_REQUIRED):
            for owner in (None, replace(self.owner, ownership_verified=False),
                          replace(self.owner, survives_owner_exit=False)):
                with self.assertRaises(ValueError):
                    FilterLifecycle(self.binding, phase, owner)

    def test_malformed_reconstruction_rejected(self):
        for binding, phase, owner in ((None, Phase.REQUESTED, None),
                                     (self.binding, "granted", self.owner),
                                     (self.binding, Phase.CANCELLED, {}),
                                     (self.binding, Phase.REQUESTED, self.owner)):
            with self.assertRaises(ValueError):
                FilterLifecycle(binding, phase, owner)

    def test_reconstructed_grant_still_requires_crash_recovery(self):
        recovered = FilterLifecycle(self.binding, Phase.GRANTED, self.owner).after_crash()
        self.assertEqual(recovered.phase, Phase.RECOVERY_REQUIRED)
        self.assertFalse(recovered.owned_detach_allowed)

    def test_kernel_ownership_ids_are_exact_and_bounded(self):
        for field, value in (("program_id", 2**32), ("link_id", True),
                             ("link_id", 0), ("link_id", 2**32),
                             ("kernel_cgroup_id", 0), ("kernel_cgroup_id", 2**64)):
            with self.assertRaises(ValueError):
                replace(self.owner, **{field:value})

    def test_request_cannot_bypass_pending_phase(self):
        for method in (self.request.attach, self.request.confirm_pin):
            with self.assertRaises(ValueError):
                method(self.owner, observed=self.binding, now=10)
        self.assertEqual(self.pending().phase, Phase.PIN_PENDING)
        with self.assertRaises(ValueError):
            self.grant(self.pending())

    def test_pending_reconstruction_requires_verified_ephemeral_owner(self):
        for owner in (None, self.owner, replace(self.owner, ownership_verified=False,
                                              survives_owner_exit=False)):
            with self.assertRaises(ValueError):
                FilterLifecycle(self.binding, Phase.PIN_PENDING, owner)

    def test_pending_cancel_and_crash_retain_owner_without_grant(self):
        pending = self.pending()
        for state in (pending.cancel(), pending.after_crash()):
            self.assertEqual(state.phase, Phase.CANCELLED)
            self.assertEqual(state.owned, pending.owned)
            self.assertTrue(state.owned_detach_allowed)
            with self.assertRaises(ValueError):
                state.confirm_pin(self.owner, observed=self.binding, now=10)

    def test_confirmation_requires_exact_owner_identity(self):
        pending = self.pending()
        for field, value in (("program_id", 99), ("program_hash", "f" * 64),
                             ("link_id", 99), ("kernel_cgroup_id", 99),
                             ("ownership_verified", False), ("survives_owner_exit", False)):
            state = pending.confirm_pin(replace(self.owner, **{field: value}),
                                        observed=self.binding, now=10)
            self.assertEqual(state.phase, Phase.CANCELLED)
            self.assertEqual(state.owned, pending.owned)

    def test_both_pin_stages_require_fresh_binding_and_deadline(self):
        for observed, now in ((None, 10), (self.binding, 30), (self.binding, float("nan")),
                              (replace(self.binding, topology_hash="e" * 64), 10)):
            state = self.request.prepare_pin(self.pending().owned, observed=observed, now=now)
            self.assertEqual(state.phase, Phase.CANCELLED)
            state = self.pending().confirm_pin(self.owner, observed=observed, now=now)
            self.assertEqual(state.phase, Phase.CANCELLED)
            self.assertEqual(state.owned, self.pending().owned)

    def test_preparation_rejects_persistent_or_unverified_evidence(self):
        for owner in (self.owner, replace(self.owner, ownership_verified=False,
                                         survives_owner_exit=False)):
            state = self.request.prepare_pin(owner, observed=self.binding, now=10)
            self.assertEqual(state.phase, Phase.CANCELLED)
        with self.assertRaises(ValueError):
            self.pending().prepare_pin(self.pending().owned, observed=self.binding, now=10)
