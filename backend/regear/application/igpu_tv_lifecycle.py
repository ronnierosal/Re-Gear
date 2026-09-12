"""Offline composition of preserved-game presentation and idle promotion.

Compose with the existing shared supervised presentation owner, never a second
engine. Watch/consent state is deliberately not restored on reload. The existing
durable transition journal remains authoritative for completed promotion.
"""
from dataclasses import dataclass
from hashlib import sha256
from threading import Lock
from typing import Callable

from ..domain.control_plane import PlacementState, TransitionOutcomeKind
from ..domain.igpu_tv_evidence import bind_igpu_tv, check_igpu_tv
from ..domain.inference import infer_placement
from ..domain.models import Confidence, DisplayKind, GameState, GpuRole
from ..ports.igpu_tv_lifecycle import IgpuTvObservationPort, IgpuTvPresenterPort, UnsupportedIgpuTvPresenter
from ..ports.transition_journal import TransitionJournalPort
from .docked_igpu_exit import DockedIgpuExitStage, DockedIgpuGameExitWatcher
from .presentation_completion import committed_target
from .supervised_transition import SupervisedPresentationTransitionService


@dataclass(frozen=True, slots=True)
class IgpuTvStatus:
    """Last operation result, not a continuously valid current-ready claim.

Completion IDs identify persisted engine receipts. Lifecycle correlation and
popup replay across process reload still require an owning runtime adapter.
"""
    phase: str = "waiting_for_tv"
    result_code: str = "igpu_tv.not_started"
    completion_id: str = ""
    success_verified: bool = False


class IgpuTvLifecycle:
    def __init__(self, *, observations: IgpuTvObservationPort,
                 watcher: DockedIgpuGameExitWatcher,
                 transitions: SupervisedPresentationTransitionService,
                 journal: TransitionJournalPort, standing_consent: Callable[[], bool],
                 presenter: IgpuTvPresenterPort | None = None):
        self._observations = observations
        self._watcher = watcher
        self._transitions = transitions
        self._journal = journal
        self._consent = standing_consent
        self._presenter = presenter or UnsupportedIgpuTvPresenter()
        self._lock = Lock()
        self._status = IgpuTvStatus()
        self._binding = None
        self._watch = None
        self._last_sample = ""
        self._owns_resources = False

    @property
    def status(self) -> IgpuTvStatus:
        return self._status

    def _set(self, phase, code):
        self._status = IgpuTvStatus(phase, code)
        return self._status

    def _sample(self):
        value = self._observations.observe()
        if (value is None or not value.current.generation or not value.current.sample_id
                or value.current.sample_id == self._last_sample or not value.game.exact
                or not value.gamescope.exact
                or value.game.state != value.current.snapshot.game_state):
            return None
        self._last_sample = value.current.sample_id
        return value

    def _stop(self, code, phase="action_required"):
        if self._owns_resources and self._binding is not None:
            try:
                if not self._presenter.release(self._binding).succeeded:
                    return self._set("action_required", "igpu_tv.presenter_release_failed")
                self._owns_resources = False
            except Exception:
                return self._set("action_required", "igpu_tv.presenter_release_failed")
        return self._set(phase, code)

    def start(self, *, igpu_stable_id: str, egpu_stable_id: str, tv_stable_id: str):
        if not self._lock.acquire(blocking=False):
            return IgpuTvStatus("action_required", "igpu_tv.busy")
        try:
            # A terminal run cannot silently restart or reuse its consent/watch.
            if self._status.phase != "waiting_for_tv":
                return self._status
            if not self._consent():
                return self._set("cancelled", "igpu_tv.not_enabled")
            before = self._sample()
            if before is None:
                return self._set("action_required", "igpu_tv.observation_unavailable")
            result = bind_igpu_tv(before.current.snapshot, before.rendering,
                igpu_stable_id=igpu_stable_id, egpu_stable_id=egpu_stable_id,
                tv_stable_id=tv_stable_id)
            if result.binding is None:
                return self._set("action_required", "igpu_tv.preservation_unverified")
            self._binding = result.binding
            if not self._consent():
                return self._set("cancelled", "igpu_tv.not_enabled")
            # A failing mechanism may have partially acquired resources.
            self._owns_resources = True
            shown = self._presenter.present(self._binding,
                                           expected_generation=before.current.generation)
            if not shown.succeeded:
                code = ("igpu_tv.presenter_unavailable"
                        if shown.code == "igpu_tv.presenter_unavailable"
                        else "igpu_tv.presentation_failed")
                return self._stop(code)
            after = self._sample()
            if (after is None or check_igpu_tv(after.current.snapshot, after.rendering,
                    self._binding, require_presented=True)
                    or after.game.identity != before.game.identity
                    or after.gamescope.generation != before.gamescope.generation):
                return self._stop("igpu_tv.presentation_unverified")
            armed = self._watcher.arm()
            if (not armed.accepted or armed.watch.game != before.game.identity
                    or armed.watch.gamescope_session_generation != before.gamescope.generation
                    or armed.watch.egpu_stable_id != self._binding.egpu_stable_id):
                return self._stop("igpu_tv.watch_unverified")
            self._watch = armed.watch
            return self._set("waiting_for_game_exit", "igpu_tv.original_game_on_tv")
        except Exception:
            return self._stop("igpu_tv.operation_unavailable")
        finally:
            self._lock.release()

    def tick(self):
        if not self._lock.acquire(blocking=False):
            return IgpuTvStatus("action_required", "igpu_tv.busy")
        try:
            if self._status.phase != "waiting_for_game_exit":
                return self._status
            if not self._consent():
                return self._stop("igpu_tv.not_enabled", "cancelled")
            sample = self._sample()
            if (sample is None or check_igpu_tv(sample.current.snapshot, sample.rendering,
                    self._binding, require_presented=True, allow_idle=True)
                    or sample.gamescope.generation != self._watch.gamescope_session_generation):
                return self._stop("igpu_tv.preservation_unverified")
            self._watch = self._watcher.poll(self._watch)
            if self._watch.stage == DockedIgpuExitStage.WATCHING:
                return self._status
            if self._watch.stage != DockedIgpuExitStage.PROMOTION_READY:
                return self._stop("igpu_tv.original_game_exit_unverified")
            # The terminal watch is not reusable evidence. Bracket resource release
            # with new idle samples, then let the engine recheck that generation.
            before = self._sample()
            if not self._idle_preserved(before):
                return self._stop("igpu_tv.idle_unverified")
            released = self._presenter.release(self._binding)
            if not released.succeeded:
                return self._set("action_required", "igpu_tv.presenter_release_failed")
            self._owns_resources = False
            after = self._sample()
            if (not self._idle_preserved(after) or before.game.generation != after.game.generation
                    or before.game.sample_id == after.game.sample_id):
                return self._stop("igpu_tv.idle_unverified")
            source = infer_placement(after.current.snapshot)
            if source not in {PlacementState.PORTABLE, PlacementState.DOCKED_IGPU}:
                return self._stop("igpu_tv.source_unverified")
            self._set("promoting_to_egpu", "igpu_tv.promoting")
            execution = self._transitions.execute_automatic(PlacementState.DOCKED_EGPU,
                expected_generation=after.current.generation, standing_consent=self._consent())
            if (not execution.accepted or not execution.durable or execution.outcome is None
                    or execution.outcome.kind != TransitionOutcomeKind.SUCCEEDED):
                return self._set("action_required", "igpu_tv.promotion_unverified")
            self._set("verifying_egpu", "igpu_tv.verifying")
            final = self._sample()
            if not self._egpu_verified(final):
                return self._set("action_required", "igpu_tv.egpu_postconditions_unverified")
            receipt = self._journal.load_current()
            archived = receipt is None
            if archived:
                receipt = self._journal.load_completed()
            if not self._receipt_matches(receipt, execution.operation_id, source):
                return self._set("action_required", "igpu_tv.completion_unverified")
            # Shared owner performs archive mutation under its existing lock.
            if not archived:
                self._transitions.reconcile_completion(final.current)
            saved = self._journal.load_completed()
            if saved != receipt:
                return self._set("action_required", "igpu_tv.completion_unverified")
            token = sha256((saved.operation_id + ":" + saved.request_id).encode()).hexdigest()
            self._status = IgpuTvStatus("egpu_ready", "igpu_tv.egpu_ready", token, True)
            return self._status
        except Exception:
            return self._stop("igpu_tv.operation_unavailable")
        finally:
            self._lock.release()

    def cancel(self):
        """Stop or retry owned-resource cleanup without rearming promotion."""
        if not self._lock.acquire(blocking=False):
            return IgpuTvStatus("action_required", "igpu_tv.busy")
        try:
            return self._stop("igpu_tv.cancelled", "cancelled")
        finally:
            self._lock.release()

    def _idle_preserved(self, sample):
        return (sample is not None and sample.game.state == GameState.IDLE
            and sample.gamescope.generation == self._watch.gamescope_session_generation
            and not check_igpu_tv(sample.current.snapshot, sample.rendering,
                                 self._binding, allow_idle=True))

    def _egpu_verified(self, sample):
        if sample is None:
            return False
        snapshot, rendering, binding = sample.current.snapshot, sample.rendering, self._binding
        gpus = [g for g in snapshot.gpus if g.stable_id == binding.egpu_stable_id]
        tvs = [d for d in snapshot.displays if d.stable_id == binding.tv_stable_id]
        connectors = [d for d in snapshot.displays if d.connector == binding.tv_connector]
        return (snapshot.game_state == GameState.IDLE and rendering.game_running is False
            and rendering.game_confidence == Confidence.VERIFIED
            and len(gpus) == 1 and gpus[0].role == GpuRole.EXTERNAL
            and gpus[0].present is True and gpus[0].confidence == Confidence.VERIFIED
            and len(tvs) == 1 and len(connectors) == 1 and tvs[0] == connectors[0]
            and tvs[0].kind == DisplayKind.EXTERNAL
            and tvs[0].connected is True and tvs[0].edid_ready is True
            and tvs[0].confidence == Confidence.VERIFIED
            and tvs[0].owning_gpu_stable_id == binding.egpu_stable_id
            and tvs[0].owning_gpu_confidence == Confidence.VERIFIED
            and tvs[0].active is True and tvs[0].active_confidence == Confidence.VERIFIED
            and tvs[0].mode_committed is True
            and bool(rendering.session_id) and bool(rendering.compositor_instance_id)
            and rendering.compositor_render_gpu_stable_id == binding.egpu_stable_id
            and rendering.compositor_render_confidence == Confidence.VERIFIED
            and snapshot.gamescope.running is True
            and snapshot.gamescope.confidence == Confidence.VERIFIED
            and snapshot.gamescope.render_gpu_stable_id == binding.egpu_stable_id)

    @staticmethod
    def _receipt_matches(receipt, operation_id, source):
        return (receipt is not None and receipt.operation_id == operation_id
            and committed_target(receipt) == PlacementState.DOCKED_EGPU
            and receipt.entries[0].placement == source
            and receipt.entries[-1].code == "transition.committed")
