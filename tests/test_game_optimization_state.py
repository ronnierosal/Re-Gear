"""The bounded learning lifecycle, transition by transition. Pure."""

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.game_optimization_preferences import (  # noqa: E402
    EffectiveIntent,
    IntentReason,
)
from regear.domain.game_optimization_state import (  # noqa: E402
    AttemptOutcome,
    DispatchKind,
    DispatchResult,
    InFlight,
    LaneKey,
    LearningPolicy,
    ObservationBinding,
    ObservationWindow,
    OptimizationContext,
    PerformanceContextRef,
    Phase,
    QueuedPlan,
    WindowVerdict,
    apply_intent,
    assess,
    begin_dispatch,
    clear_override,
    current_binding,
    finish_dispatch,
    initial,
    launched,
    next_dispatch,
    recover,
    window_refusal,
)
from regear.domain.game_optimization_state import observe as observe_window  # noqa: E402
from regear.domain.game_optimization_state import propose as propose_for  # noqa: E402
from regear.domain.graphics_profiles import SupportTier  # noqa: E402
from regear.domain.mode_profiles import ExperienceTarget  # noqa: E402
from regear.domain.models import OperatingMode  # noqa: E402

APP = "4000000002"
KEY = LaneKey(APP, OperatingMode.PORTABLE)
POLICY = LearningPolicy()
BALANCED = ExperienceTarget.BALANCED
PERF = PerformanceContextRef("fixture-gpu-a.display-800p")
CONTEXT = OptimizationContext(BALANCED, "build-7", 1, 1, "schema-v5", PERF)
CANDIDATE = QueuedPlan("candidate-a", BALANCED)
MEETS, BELOW, UNSURE = (
    WindowVerdict.MEETS_TARGET,
    WindowVerdict.BELOW_TARGET,
    WindowVerdict.INCONCLUSIVE,
)
ON = EffectiveIntent(APP, True, BALANCED, IntentReason.AUTOMATIC_INHERITED)
OFF = EffectiveIntent(APP, False, BALANCED, IntentReason.GLOBAL_DISABLED)


def observe(state, qualified, verdict, policy=POLICY):
    """A window bound to the lane's current launch, as a correct observer sends it."""
    binding = current_binding(state) or ObservationBinding(-1, CONTEXT, "")
    return observe_window(state, ObservationWindow(binding, qualified, verdict), policy)


def propose(state, candidate, policy=POLICY):
    """A candidate planned against the lane's current context."""
    return propose_for(state, candidate, state.context, policy)


def managed(state=None, context=CONTEXT):
    return assess(state or initial(KEY), SupportTier.MANAGED, context, POLICY)


def learned(windows=POLICY.learning_windows):
    state = managed()
    for _ in range(windows):
        state = observe(state, True, MEETS, POLICY)
    return state


def staged():
    proposal = propose(learned(), CANDIDATE, POLICY)
    assert proposal.staged, proposal.reason
    return proposal.state


def dispatched(state, result=DispatchResult.LANDED):
    return finish_dispatch(begin_dispatch(state, next_dispatch(state)), result, POLICY)


def validating():
    return dispatched(staged())


def feed(state, *windows):
    for qualified, verdict in windows:
        state = observe(state, qualified, verdict, POLICY)
    return state


class LearningTests(unittest.TestCase):
    def test_supported_game_starts_at_baseline_and_writes_nothing(self):
        state = managed()
        self.assertIs(state.phase, Phase.BASELINE)
        self.assertIsNone(next_dispatch(state))

    def test_advisor_and_unknown_support_never_dispatch(self):
        self.assertIs(assess(initial(KEY), SupportTier.ADVISOR, CONTEXT, POLICY).phase, Phase.ADVISOR_ONLY)
        self.assertIs(assess(initial(KEY), SupportTier.UNKNOWN, None, POLICY).phase, Phase.UNSUPPORTED)
        # MANAGED with no context (e.g. unknown game version) is not managed.
        self.assertIs(assess(initial(KEY), SupportTier.MANAGED, None, POLICY).phase, Phase.UNSUPPORTED)

    def test_unqualified_windows_do_not_count_as_learning(self):
        state = feed(managed(), *[(False, MEETS)] * 10)
        self.assertEqual(state.learning_windows, 0)
        self.assertEqual(state.excluded_windows, 10)
        self.assertFalse(propose(state, CANDIDATE, POLICY).staged)

    def test_candidate_waits_for_enough_ordinary_play(self):
        early = learned(POLICY.learning_windows - 1)
        self.assertIs(early.phase, Phase.LEARNING)
        self.assertFalse(propose(early, CANDIDATE, POLICY).staged)
        self.assertTrue(propose(learned(), CANDIDATE, POLICY).staged)

    def test_candidate_for_another_preference_is_refused(self):
        other = QueuedPlan("candidate-q", ExperienceTarget.QUALITY)
        self.assertFalse(propose(learned(), other, POLICY).staged)

    def test_only_one_candidate_at_a_time(self):
        self.assertFalse(propose(staged(), QueuedPlan("candidate-b", BALANCED), POLICY).staged)


class ValidationTests(unittest.TestCase):
    def test_staged_candidate_is_the_next_dispatch(self):
        state = staged()
        self.assertIs(state.phase, Phase.TESTING_PROFILE)
        self.assertEqual(next_dispatch(state), InFlight(DispatchKind.APPLY_CANDIDATE, "candidate-a"))

    def test_deferred_launch_keeps_the_candidate_staged(self):
        state = dispatched(staged(), DispatchResult.DEFERRED)
        self.assertIs(state.phase, Phase.TESTING_PROFILE)
        self.assertEqual(state.candidate, CANDIDATE)

    def test_each_launch_while_validating_checks_the_candidate_is_intact(self):
        state = feed(validating(), (True, MEETS))
        self.assertEqual(next_dispatch(state), InFlight(DispatchKind.APPLY_CANDIDATE, "candidate-a"))
        checked = dispatched(state)
        self.assertIs(checked.phase, Phase.VALIDATING)
        self.assertEqual(checked.meets, 1)  # evidence so far stands
        self.assertIs(dispatched(state, DispatchResult.NOT_APPLIED).phase, Phase.VALIDATING)
        edited = dispatched(state, DispatchResult.CONFLICT)
        self.assertIs(edited.phase, Phase.USER_OVERRIDE)
        self.assertIs(edited.history[-1].outcome, AttemptOutcome.CONFLICT)

    def test_qualified_meets_windows_accept_and_lock(self):
        state = feed(validating(), *[(True, MEETS)] * POLICY.accept_windows)
        self.assertIs(state.phase, Phase.OPTIMIZED_LOCKED)
        self.assertEqual(state.accepted, CANDIDATE)
        self.assertEqual(state.accepted_context, CONTEXT)
        self.assertIs(state.history[-1].outcome, AttemptOutcome.ACCEPTED)
        self.assertEqual(next_dispatch(state).kind, DispatchKind.REAPPLY_ACCEPTED)

    def test_uncertain_windows_never_accept(self):
        windows = [(True, UNSURE), (False, MEETS)] * POLICY.validation_window_budget
        state = feed(validating(), *windows)
        self.assertIsNone(state.accepted)
        self.assertIs(state.history[-1].outcome, AttemptOutcome.INCONCLUSIVE)

    def test_inconclusive_validation_restores_the_original(self):
        state = feed(validating(), *[(True, UNSURE)] * POLICY.validation_window_budget)
        self.assertIs(state.phase, Phase.LEARNING)
        self.assertTrue(state.restore_pending)
        self.assertEqual(next_dispatch(state).kind, DispatchKind.RESTORE_ORIGINAL)

    def test_qualified_below_windows_reject_before_acceptance_is_reached(self):
        state = feed(validating(), (True, MEETS), (True, MEETS), (True, BELOW), (True, BELOW))
        self.assertIs(state.history[-1].outcome, AttemptOutcome.REJECTED)
        self.assertTrue(state.restore_pending)

    def test_no_new_candidate_until_the_original_is_back(self):
        state = feed(validating(), *[(True, BELOW)] * POLICY.reject_windows)
        self.assertFalse(propose(state, QueuedPlan("candidate-b", BALANCED), POLICY).staged)
        restored = dispatched(state)
        self.assertFalse(restored.restore_pending)
        self.assertTrue(propose(restored, QueuedPlan("candidate-b", BALANCED), POLICY).staged)

    def test_attempt_budget_is_bounded(self):
        state = learned()
        for index in range(POLICY.attempt_budget):
            proposal = propose(state, QueuedPlan(f"candidate-{index}", BALANCED), POLICY)
            self.assertTrue(proposal.staged)
            state = dispatched(proposal.state, DispatchResult.NOT_APPLIED)
        refused = propose(state, QueuedPlan("candidate-x", BALANCED), POLICY)
        self.assertFalse(refused.staged)
        self.assertIn("budget", refused.reason)
        self.assertTrue(state.exhausted(POLICY))

    def test_candidate_that_did_not_land_is_not_validated_or_restored(self):
        state = dispatched(staged(), DispatchResult.NOT_APPLIED)
        self.assertIs(state.phase, Phase.LEARNING)
        self.assertFalse(state.restore_pending)
        self.assertIs(state.history[-1].outcome, AttemptOutcome.NOT_APPLIED)

    def test_history_is_bounded(self):
        policy = LearningPolicy(attempt_budget=50, history_limit=4)
        state = learned()
        for index in range(10):
            state = propose(state, QueuedPlan(f"c{index}", BALANCED), policy).state
            state = finish_dispatch(begin_dispatch(state, next_dispatch(state)),
                                    DispatchResult.NOT_APPLIED, policy)
        self.assertEqual(len(state.history), 4)
        self.assertEqual(state.history[-1].candidate_id, "c9")


class DominanceTests(unittest.TestCase):
    def test_disable_cancels_pending_work_and_writes_nothing(self):
        state = apply_intent(staged(), OFF, POLICY)
        self.assertIs(state.phase, Phase.OPTIMIZATION_DISABLED)
        self.assertIsNone(state.candidate)
        self.assertIs(state.history[-1].outcome, AttemptOutcome.CANCELLED)
        self.assertIsNone(next_dispatch(state))

    def test_disable_drops_a_pending_restore_too(self):
        state = feed(validating(), *[(True, BELOW)] * POLICY.reject_windows)
        self.assertFalse(apply_intent(state, OFF, POLICY).restore_pending)

    def test_disabled_ignores_support_and_proposals(self):
        state = apply_intent(learned(), OFF, POLICY)
        self.assertIs(assess(state, SupportTier.MANAGED, CONTEXT, POLICY), state)
        self.assertFalse(propose(state, CANDIDATE, POLICY).staged)

    def test_reenable_reassesses_and_reuses_an_accepted_plan_only_in_its_context(self):
        locked = feed(validating(), *[(True, MEETS)] * POLICY.accept_windows)
        again = apply_intent(apply_intent(locked, OFF, POLICY), ON, POLICY)
        self.assertIs(again.phase, Phase.UNKNOWN)
        self.assertIs(managed(again).phase, Phase.OPTIMIZED_LOCKED)
        newer = dataclasses.replace(CONTEXT, game_version="build-8")
        self.assertIs(managed(again, newer).phase, Phase.NEEDS_REVALIDATION)

    def test_conflict_is_a_user_override_only_the_player_ends(self):
        state = dispatched(staged(), DispatchResult.CONFLICT)
        self.assertIs(state.phase, Phase.USER_OVERRIDE)
        self.assertIsNone(state.candidate)
        self.assertIs(state.history[-1].outcome, AttemptOutcome.CONFLICT)
        self.assertIs(managed(state), state)
        self.assertIsNone(next_dispatch(state))
        self.assertIs(apply_intent(state, ON, POLICY), state)
        self.assertIs(clear_override(state).phase, Phase.UNKNOWN)


class RevalidationTests(unittest.TestCase):
    def locked(self):
        return feed(validating(), *[(True, MEETS)] * POLICY.accept_windows)

    def test_version_drift_invalidates_evidence_and_keeps_the_plan_as_history(self):
        state = managed(self.locked(), dataclasses.replace(CONTEXT, game_version="build-8"))
        self.assertIs(state.phase, Phase.NEEDS_REVALIDATION)
        self.assertIn("game_version", state.reason)
        self.assertEqual(state.accepted, CANDIDATE)
        self.assertIsNone(next_dispatch(state))  # never reapplied in a new context
        self.assertEqual(state.attempts_used, 0)

    def test_drift_during_testing_cancels_the_candidate(self):
        state = managed(staged(), dataclasses.replace(CONTEXT, adapter_version=2))
        self.assertIs(state.phase, Phase.BASELINE)
        self.assertIsNone(state.candidate)
        self.assertEqual(state.learning_windows, 0)

    def test_repeated_qualified_degradation_asks_for_revalidation(self):
        state = feed(self.locked(), (True, BELOW), (True, MEETS), (True, BELOW))
        self.assertIs(state.phase, Phase.OPTIMIZED_LOCKED)
        state = feed(state, (True, BELOW))
        self.assertIs(state.phase, Phase.NEEDS_REVALIDATION)

    def test_unqualified_degradation_is_ignored(self):
        state = feed(self.locked(), *[(False, BELOW)] * 10, *[(True, UNSURE)] * 10)
        self.assertIs(state.phase, Phase.OPTIMIZED_LOCKED)

    def test_revalidation_may_retry_the_accepted_plan(self):
        state = feed(self.locked(), *[(True, BELOW)] * POLICY.reject_windows)
        self.assertTrue(propose(state, CANDIDATE, POLICY).staged)


class RecoveryTests(unittest.TestCase):
    def test_interrupted_candidate_write_is_uncertain_and_not_replayed(self):
        state = staged()
        marked = begin_dispatch(state, next_dispatch(state))
        recovered = recover(marked, POLICY)
        self.assertIsNone(recovered.in_flight)
        self.assertIsNone(recovered.candidate)
        self.assertIs(recovered.phase, Phase.NEEDS_REVALIDATION)
        self.assertIs(recovered.history[-1].outcome, AttemptOutcome.UNCERTAIN)
        self.assertIsNone(next_dispatch(recovered))
        # The attempt still counts.
        self.assertEqual(recovered.attempts_used, 1)

    def test_interrupted_restore_stays_due(self):
        state = feed(validating(), *[(True, BELOW)] * POLICY.reject_windows)
        recovered = recover(begin_dispatch(state, next_dispatch(state)), POLICY)
        self.assertTrue(recovered.restore_pending)
        self.assertEqual(next_dispatch(recovered).kind, DispatchKind.RESTORE_ORIGINAL)

    def test_nothing_is_due_while_a_dispatch_is_in_flight(self):
        state = staged()
        marked = begin_dispatch(state, next_dispatch(state))
        self.assertIsNone(next_dispatch(marked))
        with self.assertRaises(ValueError):
            begin_dispatch(marked, InFlight(DispatchKind.APPLY_CANDIDATE, "candidate-a"))

    def test_finishing_without_a_dispatch_is_refused(self):
        with self.assertRaises(ValueError):
            finish_dispatch(staged(), DispatchResult.LANDED, POLICY)

    def test_revision_increases_on_every_change(self):
        states = [initial(KEY), managed(), learned(), staged(), validating()]
        revisions = [state.revision for state in states]
        self.assertEqual(revisions, sorted(set(revisions)))


class BindingTests(unittest.TestCase):
    """Review finding: verdicts and plans must carry the launch and context they belong to."""

    def window(self, binding, verdict=MEETS):
        return ObservationWindow(binding, True, verdict)

    def test_a_window_from_an_earlier_launch_changes_nothing(self):
        state = launched(managed())
        earlier = current_binding(state)
        later = launched(state)
        self.assertEqual(window_refusal(later, self.window(earlier)),
                         "the window belongs to another launch")
        self.assertIs(observe_window(later, self.window(earlier), POLICY), later)

    def test_a_window_under_another_context_or_plan_changes_nothing(self):
        state = validating()
        binding = current_binding(state)
        other_context = dataclasses.replace(
            binding, context=dataclasses.replace(CONTEXT, performance=PerformanceContextRef("gpu-b"))
        )
        other_plan = dataclasses.replace(binding, plan_id="candidate-z")
        for wrong in (other_context, other_plan):
            self.assertIsNotNone(window_refusal(state, self.window(wrong)))
            self.assertIs(observe_window(state, self.window(wrong), POLICY), state)
        self.assertEqual(observe_window(state, self.window(binding), POLICY).meets, 1)

    def test_binding_names_the_plan_windows_judge(self):
        self.assertEqual(current_binding(learned()).plan_id, "")
        self.assertIsNone(current_binding(staged()))  # not yet written: nothing counts
        self.assertEqual(current_binding(validating()).plan_id, "candidate-a")
        locked = feed(validating(), *[(True, MEETS)] * POLICY.accept_windows)
        self.assertEqual(current_binding(locked).plan_id, "candidate-a")
        marked = begin_dispatch(locked, next_dispatch(locked))
        self.assertIsNone(current_binding(marked))  # mid-dispatch: nothing counts

    def test_performance_context_change_revalidates_a_locked_plan(self):
        locked = feed(validating(), *[(True, MEETS)] * POLICY.accept_windows)
        moved = dataclasses.replace(CONTEXT, performance=PerformanceContextRef("gpu-b.tv-4k"))
        state = managed(locked, moved)
        self.assertIs(state.phase, Phase.NEEDS_REVALIDATION)
        self.assertIn("performance", state.reason)
        self.assertIsNone(next_dispatch(state))

    def test_a_candidate_planned_for_another_context_is_refused(self):
        state = learned()
        stale = dataclasses.replace(CONTEXT, game_version="build-6")
        refused = propose_for(state, CANDIDATE, stale, POLICY)
        self.assertFalse(refused.staged)
        self.assertIn("another context", refused.reason)
        self.assertTrue(propose_for(state, CANDIDATE, CONTEXT, POLICY).staged)

    def test_a_context_needs_its_performance_reference(self):
        with self.assertRaises(ValueError):
            OptimizationContext(BALANCED, "build-7", 1, 1, "schema-v5", None)
        for bad in ("", "has space", "x" * 129):
            with self.assertRaises(ValueError):
                PerformanceContextRef(bad)


class PolicyTests(unittest.TestCase):
    def test_placeholder_policy_is_marked_unreviewed(self):
        self.assertEqual(LearningPolicy().policy_version, 0)

    def test_nonsense_thresholds_are_refused(self):
        with self.assertRaises(ValueError):
            LearningPolicy(attempt_budget=0)
        with self.assertRaises(ValueError):
            LearningPolicy(accept_windows=5, validation_window_budget=4)

    def test_lanes_exist_only_for_healthy_modes(self):
        for mode in (OperatingMode.UNKNOWN, OperatingMode.DEGRADED):
            with self.assertRaises(ValueError):
                LaneKey(APP, mode)


if __name__ == "__main__":
    unittest.main()
