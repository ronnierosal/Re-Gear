"""One pre-plan TV flap may retry; hardware attempts never do."""
from dataclasses import replace
import unittest

from test_automatic_dock import current
from test_supervised_transition import Observations, service
from regear.application.automatic_dock import AutomaticDockCoordinator
from regear.application.connection_readiness import ConnectionReadinessStage, ConnectionReadinessStatus
from regear.application.supervised_transition import SupervisedTransitionExecution
from regear.domain.control_plane import PlacementState, TransitionOutcome, TransitionOutcomeKind, WorkflowState
from regear.domain.models import Confidence, GameState


READY = ConnectionReadinessStatus(ConnectionReadinessStage.READY_IDLE, "connection.ready_idle", 1000)
REFUSED = SupervisedTransitionExecution(False, "transition.evidence_changed")


def sample(generation="first", **changes):
    observed = current("connected-internal.json", generation)
    displays = tuple(replace(d, stable_id="display:0123456789abcdef")
                     if d.stable_id == "external-tv" else d for d in observed.snapshot.displays)
    return replace(observed, snapshot=replace(observed.snapshot, displays=displays, **changes))


class AutomaticTvPremutationRetryTests(unittest.TestCase):
    def start(self):
        coordinator = AutomaticDockCoordinator()
        decision = coordinator.update(enabled=True, readiness=READY, current=sample())
        self.assertTrue(decision.should_switch)
        return coordinator, decision

    def refuse(self, coordinator, generation="first", result=REFUSED):
        coordinator.record_execution(result, expected_generation=generation)

    def test_real_service_refusal_then_same_tv_success_runs_one_plan(self):
        coordinator, decision = self.start()
        facade, orchestrator, _ = service(Observations(sample("changed"), sample("retry")))
        result = facade.execute_automatic(PlacementState.DOCKED_EGPU,
            expected_generation=decision.expected_generation, standing_consent=True)
        self.assertEqual(result, REFUSED)
        self.assertEqual(orchestrator.plans, [])
        self.refuse(coordinator, result=result)
        decision = coordinator.update(enabled=True, readiness=READY, current=sample("retry"))
        self.assertTrue(decision.should_switch)
        result = facade.execute_automatic(PlacementState.DOCKED_EGPU,
            expected_generation=decision.expected_generation, standing_consent=True)
        self.assertTrue(result.accepted)
        coordinator.record_execution(result, expected_generation=decision.expected_generation)
        self.assertEqual(len(orchestrator.plans), 1)
        self.assertFalse(coordinator.update(enabled=True, readiness=READY, current=sample("later")).should_switch)

    def test_second_premutation_refusal_exhausts_budget(self):
        coordinator, _ = self.start()
        self.refuse(coordinator)
        self.assertTrue(coordinator.update(enabled=True, readiness=READY, current=sample("retry")).should_switch)
        self.refuse(coordinator, "retry")
        for i in range(10):
            self.assertFalse(coordinator.update(enabled=True, readiness=READY, current=sample(str(i))).should_switch)

    def test_code_only_unknown_accepted_durable_and_operation_results_never_retry(self):
        for result in (replace(REFUSED, accepted=True), replace(REFUSED, accepted=None),
                       replace(REFUSED, durable=True), replace(REFUSED, operation_id="started"),
                       replace(REFUSED, outcome=TransitionOutcome(TransitionOutcomeKind.SUCCEEDED,
                               PlacementState.DOCKED_EGPU, WorkflowState.IDLE)),
                       replace(REFUSED, code="transition.preconditions_changed"),
                       replace(REFUSED, code="transition.observation_unavailable"),
                       replace(REFUSED, code="transition.rollback_failed")):
            with self.subTest(result=result):
                coordinator, _ = self.start()
                self.refuse(coordinator, result=result)
                # A late duplicate refusal cannot reopen a terminal result.
                self.refuse(coordinator)
                self.assertFalse(coordinator.update(enabled=True, readiness=READY, current=sample("next")).should_switch)
        coordinator, _ = self.start()
        coordinator.record_result(REFUSED.code, succeeded=False)
        self.assertFalse(coordinator.update(enabled=True, readiness=READY, current=sample("next")).should_switch)

    def test_fresh_idle_session_and_full_connection_readiness_required(self):
        variants = [sample(), sample("running", game_state=GameState.RUNNING),
                    sample("unknown", game_state=GameState.UNKNOWN),
                    sample("session", gamescope=replace(sample().snapshot.gamescope, running=False)),
                    sample("session-unknown", gamescope=replace(sample().snapshot.gamescope, confidence=Confidence.UNKNOWN))]
        for observed in variants:
            with self.subTest(sample=observed.generation):
                coordinator, _ = self.start()
                self.refuse(coordinator)
                self.assertFalse(coordinator.update(enabled=True, readiness=READY, current=observed).should_switch)
        for stage in (ConnectionReadinessStage.WAITING_FOR_AUDIO, ConnectionReadinessStage.WAITING_FOR_SESSION,
                      ConnectionReadinessStage.READY_DISPLAY_PENDING, ConnectionReadinessStage.STABILIZING):
            coordinator, _ = self.start()
            self.refuse(coordinator)
            self.assertFalse(coordinator.update(enabled=True, readiness=replace(READY, stage=stage), current=sample("next")).should_switch)
            self.assertTrue(coordinator.update(enabled=True, readiness=READY, current=sample("ready")).should_switch)

    def test_changed_tv_cancels_retry_even_if_original_returns(self):
        coordinator, _ = self.start()
        self.refuse(coordinator)
        observed = sample("other")
        observed = replace(observed, snapshot=replace(observed.snapshot, displays=tuple(
            replace(d, stable_id="display:fedcba9876543210") if d.stable_id.startswith("display:") else d
            for d in observed.snapshot.displays)))
        self.assertFalse(coordinator.update(enabled=True, readiness=READY, current=observed).should_switch)
        self.assertFalse(coordinator.update(enabled=True, readiness=READY, current=sample("back")).should_switch)

    def test_missing_hdmi_waits_for_same_panel(self):
        coordinator, _ = self.start()
        self.refuse(coordinator)
        observed = sample("off")
        observed = replace(observed, snapshot=replace(observed.snapshot, displays=observed.snapshot.displays[:1]))
        self.assertFalse(coordinator.update(enabled=True, readiness=READY, current=observed).should_switch)
        self.assertTrue(coordinator.update(enabled=True, readiness=READY, current=sample("back")).should_switch)

    def test_changed_gpu_cancels_while_hdmi_missing(self):
        coordinator, _ = self.start()
        self.refuse(coordinator)
        observed = sample("other-gpu")
        observed = replace(observed, snapshot=replace(observed.snapshot,
            displays=observed.snapshot.displays[:1], gpus=tuple(
                replace(g, stable_id="gpd-g1:fedcba9876543210") if g.stable_id.startswith("gpd-g1:") else g
                for g in observed.snapshot.gpus)))
        self.assertFalse(coordinator.update(enabled=True, readiness=READY, current=observed).should_switch)
        self.refuse(coordinator)  # Late delivery cannot reverse cancellation.
        self.assertFalse(coordinator.update(enabled=True, readiness=READY, current=sample("back")).should_switch)

    def test_suppression_and_stale_result_never_rearm(self):
        for before in (True, False):
            coordinator, _ = self.start()
            if before:
                coordinator.suppress_current_attachment_after_portable_return()
            self.refuse(coordinator)
            if not before:
                coordinator.suppress_current_attachment_after_portable_return()
            self.assertFalse(coordinator.update(enabled=True, readiness=READY, current=sample("next")).should_switch)
        coordinator, _ = self.start()
        self.refuse(coordinator, "foreign")
        self.assertFalse(coordinator.update(enabled=True, readiness=READY, current=sample("next")).should_switch)

    def test_connector_identity_and_truthy_consent_cannot_authorize_retry(self):
        coordinator = AutomaticDockCoordinator()
        observed = current("connected-internal.json")
        coordinator.update(enabled=True, readiness=READY, current=observed)
        self.refuse(coordinator, observed.generation)
        self.assertFalse(coordinator.update(enabled=True, readiness=READY, current=sample("next")).should_switch)
        for consent in (1, "true"):
            coordinator, _ = self.start()
            self.refuse(coordinator)
            self.assertFalse(coordinator.update(enabled=consent, readiness=READY, current=sample("next")).should_switch)


if __name__ == "__main__":
    unittest.main()
