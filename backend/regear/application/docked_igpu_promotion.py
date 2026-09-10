"""Opaque backend composition of game-exit watch and supervised preview."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..domain.control_plane import PlacementState
from .docked_igpu_exit import (
    WATCH_ID_RE,
    DockedIgpuExitArmResult,
    DockedIgpuExitStage,
    DockedIgpuExitWatch,
    DockedIgpuGameExitWatcher,
)

if TYPE_CHECKING:
    from .supervised_transition import SupervisedTransitionPreview


class SupervisedPreviewPort(Protocol):
    def preview(
        self,
        target: PlacementState,
        *,
        user_confirmed: bool,
        expected_generation: str = "",
    ) -> SupervisedTransitionPreview: ...


@dataclass(frozen=True, slots=True)
class DockedIgpuPromotionPollResult:
    accepted: bool
    code: str
    watch: DockedIgpuExitWatch | None = None


@dataclass(frozen=True, slots=True)
class DockedIgpuPromotionPrepareResult:
    accepted: bool
    code: str
    preview: SupervisedTransitionPreview | None = None


class DockedIgpuPromotionFacade:
    """Keep private watch state and generation out of delivery input."""

    def __init__(
        self,
        *,
        watcher: DockedIgpuGameExitWatcher,
        transitions: SupervisedPreviewPort | None = None,
    ) -> None:
        self._watcher = watcher
        self._transitions = transitions
        self._current: DockedIgpuExitWatch | None = None
        self._lock = threading.Lock()

    @property
    def inspection_supported(self) -> bool:
        return self._transitions is not None

    def arm(self) -> DockedIgpuExitArmResult:
        with self._lock:
            if self._current is not None:
                return DockedIgpuExitArmResult(
                    False, "docked_igpu.watch_already_active"
                )
            result = self._watcher.arm()
            if result.accepted:
                self._current = result.watch
            return result

    def poll(self, watch_id: str) -> DockedIgpuPromotionPollResult:
        if not WATCH_ID_RE.fullmatch(watch_id):
            return DockedIgpuPromotionPollResult(
                False, "docked_igpu.watch_identity_invalid"
            )
        with self._lock:
            if self._current is None or self._current.watch_id != watch_id:
                return DockedIgpuPromotionPollResult(
                    False, "docked_igpu.watch_changed"
                )
            self._current = self._watcher.poll(self._current)
            return DockedIgpuPromotionPollResult(
                True, self._current.reason_code, self._current
            )

    def prepare(
        self, watch_id: str, *, user_confirmed: bool
    ) -> DockedIgpuPromotionPrepareResult:
        if not WATCH_ID_RE.fullmatch(watch_id):
            return DockedIgpuPromotionPrepareResult(
                False, "docked_igpu.watch_identity_invalid"
            )
        with self._lock:
            watch = self._current
            if watch is None or watch.watch_id != watch_id:
                return DockedIgpuPromotionPrepareResult(
                    False, "docked_igpu.watch_changed"
                )
            if watch.stage is not DockedIgpuExitStage.PROMOTION_READY:
                return DockedIgpuPromotionPrepareResult(
                    False, "docked_igpu.promotion_not_ready"
                )
            if self._transitions is None:
                return DockedIgpuPromotionPrepareResult(
                    False, "docked_igpu.preview_unavailable"
                )
            try:
                preview = self._transitions.preview(
                    PlacementState.DOCKED_EGPU,
                    user_confirmed=user_confirmed,
                    expected_generation=watch.ready_snapshot_generation,
                )
            except Exception:
                return DockedIgpuPromotionPrepareResult(
                    False, "docked_igpu.preview_unavailable"
                )
            if not preview.ready:
                return DockedIgpuPromotionPrepareResult(
                    False, "docked_igpu.preview_blocked", preview
                )
            if preview.current is not PlacementState.DOCKED_IGPU:
                return DockedIgpuPromotionPrepareResult(
                    False, "docked_igpu.placement_changed", preview
                )
            if user_confirmed and preview.approval_token:
                self._current = None
            return DockedIgpuPromotionPrepareResult(
                True, "docked_igpu.preview_ready", preview
            )

    def cancel(self, watch_id: str) -> bool:
        if not WATCH_ID_RE.fullmatch(watch_id):
            return False
        with self._lock:
            if self._current is None or self._current.watch_id != watch_id:
                return False
            self._current = None
            return True
