"""Offline lifecycle contract tests; no native presenter or hardware is exercised."""
from dataclasses import replace
from types import SimpleNamespace
import unittest

from tests import test_igpu_tv_evidence as evidence_fixtures
from tests.test_presentation_completion import committed, Store
from regear.application.igpu_tv_lifecycle import IgpuTvLifecycle
from regear.application.docked_igpu_exit import DockedIgpuExitStage
from regear.application.presentation_completion import PresentationCompletion
from regear.domain.control_plane import PlacementState, TransitionOutcomeKind
from regear.domain.game_session import ActiveGameIdentity, GameSessionObservation
from regear.domain.gamescope_session import GamescopeSessionObservation
from regear.domain.models import Confidence, GameState
from regear.ports.igpu_tv_lifecycle import IgpuTvObservation
from regear.ports.transition import MechanismResult, VersionedObservation


class Samples:
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def observe(self):
        self.calls += 1
        return self.values.pop(0) if self.values else None


class Presenter:
    def __init__(self):
        self.present_calls = []
        self.release_calls = []
        self.on_release = lambda: None
        self.show_ok = True
        self.release_ok = True

    def present(self, binding, *, expected_generation):
        self.present_calls.append((binding, expected_generation))
        return MechanismResult(self.show_ok, "presenter.result")

    def release(self, binding):
        self.release_calls.append(binding)
        self.on_release()
        return MechanismResult(self.release_ok, "presenter.release")


class Watcher:
    def __init__(self, game):
        self.watch = SimpleNamespace(game=game, gamescope_session_generation="a" * 64,
                                     egpu_stable_id="external-id", stage=DockedIgpuExitStage.WATCHING)
        self.next_stage = DockedIgpuExitStage.PROMOTION_READY
        self.poll_calls = 0
        self.arm_ok = True

    def arm(self):
        return SimpleNamespace(accepted=self.arm_ok, watch=self.watch)

    def poll(self, watch):
        self.poll_calls += 1
        return SimpleNamespace(**{**vars(watch), "stage": self.next_stage})


class Transitions:
    def __init__(self, store):
        self.store = store
        self.calls = []
        self.reconciles = 0
        self.accepted = True
        self.durable = True
        self.kind = TransitionOutcomeKind.SUCCEEDED
        self.archive = True
        self.finalize = True
        self.operation_id = "operation-complete"

    def execute_automatic(self, target, *, expected_generation, standing_consent):
        self.calls.append((target, expected_generation, standing_consent))
        return SimpleNamespace(accepted=self.accepted and standing_consent,
            durable=self.durable, outcome=SimpleNamespace(kind=self.kind),
            operation_id=self.operation_id)

    def reconcile_completion(self, current):
        self.reconciles += 1
        if self.archive:
            self.store.retire_committed(self.operation_id)
        return PresentationCompletion("completion.test", self.finalize)


class IgpuTvLifecycleTests(unittest.TestCase):
    def setUp(self):
        fixture = evidence_fixtures.IgpuTvEvidenceTests()
        fixture.setUp()
        self.base, self.rendering = fixture.snapshot, fixture.evidence
        self.game = ActiveGameIdentity("123", ("game-123.scope",))
        self.consent = True
        receipt = committed()
        receipt = replace(receipt, entries=(replace(receipt.entries[0],
            placement=PlacementState.DOCKED_IGPU), *receipt.entries[1:]))
        self.store = Store(receipt)
        self.presenter = Presenter()
        self.watcher = Watcher(self.game)
        self.transitions = Transitions(self.store)

    def sample(self, number, *, idle=False, egpu=False, presented=True):
        state = GameState.IDLE if idle else GameState.RUNNING
        renderer = "external-id" if egpu else "internal-id"
        tv = replace(self.base.displays[0], active=presented,
            active_confidence=Confidence.VERIFIED, mode_committed=presented)
        snapshot = replace(self.base, game_state=state, displays=(tv,),
            gamescope=replace(self.base.gamescope, render_gpu_stable_id=renderer, output_order=(tv.connector,)),
            gpus=tuple(replace(g, selected_for_render=g.stable_id == renderer) for g in self.base.gpus))
        rendering = replace(self.rendering, game_running=not idle,
            game_instance_id="" if idle else self.rendering.game_instance_id,
            compositor_render_gpu_stable_id=renderer)
        return IgpuTvObservation(VersionedObservation("generation-" + str(number), snapshot, "sample-" + str(number)),
            rendering, GameSessionObservation(state, "idle-generation" if idle else "game-generation",
                "game-sample-" + str(number), None if idle else self.game),
            GamescopeSessionObservation(True, "session.verified", ("b" if egpu else "a") * 64))

    def lifecycle(self, samples=None, *, default_presenter=False):
        self.samples = Samples(samples if samples is not None else [
            self.sample(1, presented=False), self.sample(2), self.sample(3, idle=True),
            self.sample(4, idle=True), self.sample(5, idle=True), self.sample(6, idle=True, egpu=True)])
        return IgpuTvLifecycle(observations=self.samples, watcher=self.watcher,
            transitions=self.transitions, journal=self.store, standing_consent=lambda: self.consent,
            presenter=None if default_presenter else self.presenter)

    def start(self, lifecycle):
        return lifecycle.start(igpu_stable_id="internal-id", egpu_stable_id="external-id", tv_stable_id="edid-tv")

    def test_full_natural_exit_promotion_archives_receipt_and_is_idempotent(self):
        lifecycle = self.lifecycle()
        self.assertEqual(self.start(lifecycle).phase, "waiting_for_game_exit")
        status = lifecycle.tick()
        self.assertEqual(status.phase, "egpu_ready")
        self.assertTrue(status.success_verified)
        self.assertEqual(len(status.completion_id), 64)
        self.assertIsNone(self.store.active)
        self.assertIsNotNone(self.store.receipt)
        self.assertEqual(self.transitions.calls, [(PlacementState.DOCKED_EGPU, "generation-5", True)])
        self.assertEqual(len(self.presenter.release_calls), 1)
        calls = self.samples.calls
        self.assertEqual(lifecycle.tick(), status)
        self.assertEqual(self.start(lifecycle), status)
        self.assertEqual(self.samples.calls, calls)
        self.assertEqual(len(self.transitions.calls), 1)

    def test_real_exit_watcher_composes_through_success(self):
        from tests import test_docked_igpu_exit as real
        egpu = "gpd-g1:0123456789abcdef"
        original = real.docked_igpu()
        tv = next(d for d in original.displays if d.active is True)
        self.watcher = real.watcher(
            snapshots=(VersionedObservation("watch-running", original, "watch-1"),
                VersionedObservation("watch-idle", real.docked_igpu(game_state=GameState.IDLE), "watch-2")),
            games=(real.game_running(sample="watch-game-1"), real.game_running(sample="watch-game-2"),
                   real.game_idle(sample="watch-game-3"), real.game_idle(sample="watch-game-4")))
        samples = []
        for number in range(1, 7):
            value = self.sample(number, idle=number >= 3, egpu=number == 6)
            snapshot = value.current.snapshot
            renderer = egpu if number == 6 else "internal-gpu"
            gpus = tuple(replace(g, stable_id="internal-gpu" if g.stable_id == "internal-id" else egpu)
                         for g in snapshot.gpus)
            displays = (replace(snapshot.displays[0], stable_id=tv.stable_id, owning_gpu_stable_id=egpu),)
            value = replace(value, current=replace(value.current, snapshot=replace(snapshot,
                gpus=gpus, displays=displays, gamescope=replace(snapshot.gamescope, render_gpu_stable_id=renderer))),
                rendering=replace(value.rendering, game_render_gpu_stable_id="internal-gpu",
                    compositor_render_gpu_stable_id=renderer),
                game=replace(value.game, identity=real.GAME if number < 3 else None))
            samples.append(value)
        lifecycle = self.lifecycle(samples)
        self.assertEqual(lifecycle.start(igpu_stable_id="internal-gpu", egpu_stable_id=egpu,
            tv_stable_id=tv.stable_id).phase, "waiting_for_game_exit")
        self.assertTrue(lifecycle.tick().success_verified)
        self.assertEqual(len(self.transitions.calls), 1)

    def test_default_presenter_is_explicitly_unsupported(self):
        lifecycle = self.lifecycle(default_presenter=True)
        self.assertEqual(self.start(lifecycle).result_code, "igpu_tv.presenter_unavailable")
        self.assertEqual(self.watcher.poll_calls, 0)
        self.assertEqual(self.transitions.calls, [])

    def test_post_presentation_replacement_releases_and_never_promotes(self):
        after = self.sample(2)
        variants = [replace(after, rendering=replace(after.rendering, game_instance_id="new-game")),
            replace(after, rendering=replace(after.rendering, session_id="new-session")),
            replace(after, game=replace(after.game, identity=ActiveGameIdentity("456", ("game-456.scope",)))),
            replace(after, gamescope=GamescopeSessionObservation(True, "session.verified", "c" * 64)),
            replace(after, current=replace(after.current, snapshot=replace(after.current.snapshot,
                displays=(replace(after.current.snapshot.displays[0], stable_id="new-tv"),))))]
        for changed in variants:
            with self.subTest(changed=changed):
                lifecycle = self.lifecycle([self.sample(1), changed])
                self.assertEqual(self.start(lifecycle).result_code, "igpu_tv.presentation_unverified")
                self.assertFalse(lifecycle.status.success_verified)
        self.assertEqual(len(self.presenter.release_calls), len(variants))
        self.assertEqual(self.transitions.calls, [])

    def test_stale_or_unknown_sample_cannot_verify_presentation(self):
        first = self.sample(1)
        for after in (None, first, replace(self.sample(2), gamescope=GamescopeSessionObservation(False, "session.unknown"))):
            lifecycle = self.lifecycle([first, after])
            self.assertEqual(self.start(lifecycle).result_code, "igpu_tv.presentation_unverified")
        self.assertEqual(self.transitions.calls, [])

    def test_running_watch_does_not_promote(self):
        self.watcher.next_stage = DockedIgpuExitStage.WATCHING
        lifecycle = self.lifecycle([self.sample(1), self.sample(2), self.sample(3)])
        self.start(lifecycle)
        self.assertEqual(lifecycle.tick().phase, "waiting_for_game_exit")
        self.assertEqual(self.presenter.release_calls, [])
        self.assertEqual(self.transitions.calls, [])

    def test_cancelled_natural_exit_watch_refuses_promotion(self):
        self.watcher.next_stage = DockedIgpuExitStage.CANCELLED
        lifecycle = self.lifecycle()
        self.start(lifecycle)
        self.assertEqual(lifecycle.tick().result_code, "igpu_tv.original_game_exit_unverified")
        self.assertEqual(self.transitions.calls, [])

    def test_unknown_running_changed_or_replayed_idle_after_release_refuses(self):
        after = self.sample(5, idle=True)
        variants = [None, self.sample(5), self.sample(4, idle=True),
            replace(after, game=replace(after.game, generation="changed-idle")),
            replace(after, rendering=replace(after.rendering, game_confidence=Confidence.UNKNOWN)),
            replace(after, gamescope=GamescopeSessionObservation(True, "session.verified", "c" * 64))]
        for changed in variants:
            lifecycle = self.lifecycle([self.sample(1), self.sample(2), self.sample(3, idle=True),
                self.sample(4, idle=True), changed])
            self.start(lifecycle)
            self.assertEqual(lifecycle.tick().result_code, "igpu_tv.idle_unverified")
        self.assertEqual(self.transitions.calls, [])

    def test_consent_withdrawal_before_tick_releases_without_promotion(self):
        lifecycle = self.lifecycle()
        self.start(lifecycle)
        self.consent = False
        self.assertEqual(lifecycle.tick().phase, "cancelled")
        self.assertEqual(len(self.presenter.release_calls), 1)
        self.assertEqual(self.transitions.calls, [])

    def test_non_boolean_consent_never_authorizes_presenter_or_transition(self):
        for invalid in (1, "true", {"enabled": True}, [True], None, False):
            for gate in ("start", "before_present", "tick", "after_release"):
                with self.subTest(consent=invalid, gate=gate):
                    self.setUp()
                    lifecycle = self.lifecycle()
                    if gate == "start":
                        self.consent = invalid
                    elif gate == "before_present":
                        observe = self.samples.observe

                        def withdraw():
                            self.consent = invalid
                            return observe()

                        self.samples.observe = withdraw
                    if gate in {"start", "before_present"}:
                        result = self.start(lifecycle)
                        self.assertEqual(self.presenter.present_calls, [])
                        self.assertEqual(self.presenter.release_calls, [])
                    else:
                        self.start(lifecycle)
                        if gate == "tick":
                            self.consent = invalid
                        else:
                            self.presenter.on_release = lambda: setattr(self, "consent", invalid)
                        result = lifecycle.tick()
                    self.assertEqual(result.phase, "cancelled")
                    self.assertEqual(result.result_code, "igpu_tv.not_enabled")
                    self.assertFalse(result.success_verified)
                    self.assertEqual(self.transitions.calls, [])

    def test_consent_withdrawn_during_release_is_not_success(self):
        lifecycle = self.lifecycle()
        self.start(lifecycle)
        self.presenter.on_release = lambda: setattr(self, "consent", False)
        self.assertFalse(lifecycle.tick().success_verified)
        if self.transitions.calls:
            self.assertFalse(self.transitions.calls[0][2])
        self.assertEqual(self.transitions.reconciles, 0)

    def test_failed_nondurable_and_noop_execution_never_complete(self):
        for field, value in (("accepted", False), ("durable", False), ("kind", TransitionOutcomeKind.NO_OP)):
            with self.subTest(field=field):
                self.setUp()
                setattr(self.transitions, field, value)
                lifecycle = self.lifecycle()
                self.start(lifecycle)
                self.assertEqual(lifecycle.tick().result_code, "igpu_tv.promotion_unverified")
                self.assertEqual(self.transitions.reconciles, 0)

    def test_foreign_missing_and_noop_receipt_never_complete(self):
        original = self.store.active
        variants = [None, replace(original, operation_id="other-operation"),
            replace(original, entries=(*original.entries[:-1], replace(original.entries[-1], code="transition.no_op"))),
            replace(original, entries=(replace(original.entries[0], placement=PlacementState.PORTABLE), *original.entries[1:]))]
        for receipt in variants:
            self.store.active = receipt
            lifecycle = self.lifecycle()
            self.start(lifecycle)
            self.assertEqual(lifecycle.tick().result_code, "igpu_tv.completion_unverified")
        self.assertEqual(self.transitions.reconciles, 0)

    def test_unarchived_receipt_never_emits_success(self):
        self.transitions.archive = False
        lifecycle = self.lifecycle()
        self.start(lifecycle)
        self.assertEqual(lifecycle.tick().result_code, "igpu_tv.completion_unverified")
        self.assertFalse(lifecycle.status.success_verified)

    def test_background_archived_matching_receipt_is_accepted(self):
        self.store.receipt, self.store.active = self.store.active, None
        lifecycle = self.lifecycle()
        self.start(lifecycle)
        self.assertTrue(lifecycle.tick().success_verified)
        self.assertEqual(self.transitions.reconciles, 0)

    def test_archived_exact_receipt_is_authoritative_over_finalize_boolean(self):
        self.transitions.finalize = False
        lifecycle = self.lifecycle()
        self.start(lifecycle)
        self.assertTrue(lifecycle.tick().success_verified)

    def test_cancel_retries_failed_cleanup_without_rearming(self):
        lifecycle = self.lifecycle()
        self.start(lifecycle)
        self.presenter.release_ok = False
        self.assertEqual(lifecycle.cancel().result_code, "igpu_tv.presenter_release_failed")
        self.presenter.release_ok = True
        self.assertEqual(lifecycle.cancel().phase, "cancelled")
        self.assertEqual(self.start(lifecycle).phase, "cancelled")
        self.assertEqual(len(self.presenter.present_calls), 1)
        self.assertEqual(len(self.presenter.release_calls), 2)
        self.assertEqual(self.transitions.calls, [])

    def test_unverified_final_renderer_never_archives(self):
        lifecycle = self.lifecycle([self.sample(1), self.sample(2), self.sample(3, idle=True),
            self.sample(4, idle=True), self.sample(5, idle=True), self.sample(6, idle=True)])
        self.start(lifecycle)
        self.assertEqual(lifecycle.tick().result_code, "igpu_tv.egpu_postconditions_unverified")
        self.assertEqual(self.transitions.reconciles, 0)

    def test_release_failure_never_invokes_transition(self):
        lifecycle = self.lifecycle()
        self.start(lifecycle)
        self.presenter.release_ok = False
        self.assertEqual(lifecycle.tick().result_code, "igpu_tv.presenter_release_failed")
        self.assertEqual(self.transitions.calls, [])


if __name__ == "__main__":
    unittest.main()
