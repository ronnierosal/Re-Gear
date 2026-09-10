"""Serialized lifecycle ownership for the read-only Docked-iGPU exit watch."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ..domain.control_plane import PlacementState
from .docked_igpu_exit import (
    DockedIgpuExitArmResult,
    DockedIgpuExitStage,
)
from .docked_igpu_promotion import (
    DockedIgpuPromotionPollResult,
    DockedIgpuPromotionPrepareResult,
)


CODE_RE = re.compile(r"^[a-z0-9_.-]{1,96}$")
MIN_POLL_INTERVAL_MS = 250
MAX_POLL_INTERVAL_MS = 5000
MAX_IDLE_POLL_INTERVAL_MS = 60000


class DockedIgpuLifecycleStage(StrEnum):
    IDLE = "idle"
    WATCHING = "watching"
    PROMOTION_READY = "promotion_ready"
    ACTION_REQUIRED = "action_required"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class DockedIgpuLifecycleStatus:
    stage: DockedIgpuLifecycleStage
    code: str
    poll_after_ms: int
    inspection_available: bool = False
    acknowledgement_required: bool = False

    def __post_init__(self) -> None:
        if not CODE_RE.fullmatch(self.code):
            raise ValueError("Docked-iGPU lifecycle code is invalid")
        if self.stage is DockedIgpuLifecycleStage.WATCHING:
            if not MIN_POLL_INTERVAL_MS <= self.poll_after_ms <= MAX_POLL_INTERVAL_MS:
                raise ValueError("Docked-iGPU lifecycle poll interval is invalid")
        elif self.stage is DockedIgpuLifecycleStage.IDLE:
            if not MIN_POLL_INTERVAL_MS <= self.poll_after_ms <= MAX_IDLE_POLL_INTERVAL_MS:
                raise ValueError("Docked-iGPU lifecycle idle interval is invalid")
        elif (
            self.stage is DockedIgpuLifecycleStage.PROMOTION_READY
            and not self.inspection_available
        ):
            if not MIN_POLL_INTERVAL_MS <= self.poll_after_ms <= MAX_POLL_INTERVAL_MS:
                raise ValueError("Docked-iGPU lifecycle ready interval is invalid")
        elif self.poll_after_ms != 0:
            raise ValueError("terminal Docked-iGPU lifecycle cannot request polling")
        if (
            self.inspection_available
            and self.stage is not DockedIgpuLifecycleStage.PROMOTION_READY
        ):
            raise ValueError("Docked-iGPU lifecycle inspection state is invalid")
        if self.acknowledgement_required != (
            self.stage is DockedIgpuLifecycleStage.ACTION_REQUIRED
        ):
            raise ValueError("Docked-iGPU lifecycle acknowledgement state is invalid")


@dataclass(frozen=True, slots=True)
class DockedIgpuLifecycleInspection:
    accepted: bool
    code: str
    current: PlacementState = PlacementState.UNKNOWN
    target: PlacementState = PlacementState.DOCKED_EGPU
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not CODE_RE.fullmatch(self.code):
            raise ValueError("Docked-iGPU lifecycle inspection code is invalid")
        if any(not CODE_RE.fullmatch(value) for value in self.blockers):
            raise ValueError("Docked-iGPU lifecycle blocker code is invalid")


class DockedIgpuPromotionLifecyclePort(Protocol):
    @property
    def inspection_supported(self) -> bool: ...

    def arm(self) -> DockedIgpuExitArmResult: ...

    def poll(self, watch_id: str) -> DockedIgpuPromotionPollResult: ...

    def prepare(
        self, watch_id: str, *, user_confirmed: bool
    ) -> DockedIgpuPromotionPrepareResult: ...

    def cancel(self, watch_id: str) -> bool: ...


class DockedIgpuWatchLifecycle:
    """Own exactly one private watch without creating transition authority."""

    def __init__(
        self,
        promotion: DockedIgpuPromotionLifecyclePort,
        *,
        poll_interval_ms: int = 1000,
        idle_poll_interval_ms: int = 15000,
    ) -> None:
        if not MIN_POLL_INTERVAL_MS <= poll_interval_ms <= MAX_POLL_INTERVAL_MS:
            raise ValueError("Docked-iGPU lifecycle poll interval is invalid")
        if not MIN_POLL_INTERVAL_MS <= idle_poll_interval_ms <= MAX_IDLE_POLL_INTERVAL_MS:
            raise ValueError("Docked-iGPU lifecycle idle interval is invalid")
        self._promotion = promotion
        self._poll_interval_ms = poll_interval_ms
        self._idle_poll_interval_ms = idle_poll_interval_ms
        self._watch_id = ""
        self._status = self._idle("docked_igpu.lifecycle_idle")
        self._closed = False
        self._lock = threading.Lock()

    def status(self) -> DockedIgpuLifecycleStatus:
        with self._lock:
            return self._status

    def tick(self) -> DockedIgpuLifecycleStatus:
        with self._lock:
            if self._closed:
                return self._status
            if self._status.stage is DockedIgpuLifecycleStage.ACTION_REQUIRED:
                return self._status
            if self._status.stage is DockedIgpuLifecycleStage.PROMOTION_READY:
                if self._status.inspection_available:
                    return self._status
                if not self._cancel_locked():
                    self._status = self._action("docked_igpu.cancel_incomplete")
                else:
                    self._status = self._idle("docked_igpu.promotion_observed")
                return self._status
            if not self._watch_id:
                return self._arm_locked()
            return self._poll_locked()

    def acknowledge_action(self) -> bool:
        with self._lock:
            if (
                self._closed
                or self._status.stage is not DockedIgpuLifecycleStage.ACTION_REQUIRED
                or not self._watch_id
            ):
                return False
            if not self._cancel_locked():
                return False
            self._status = self._idle("docked_igpu.action_acknowledged")
            return True

    def inspect_ready(self) -> DockedIgpuLifecycleInspection:
        """Preview readiness without exposing identity or creating authority."""

        with self._lock:
            if (
                self._status.stage is DockedIgpuLifecycleStage.PROMOTION_READY
                and not self._status.inspection_available
            ):
                return DockedIgpuLifecycleInspection(
                    False, "docked_igpu.inspection_unavailable"
                )
            if (
                self._closed
                or self._status.stage is not DockedIgpuLifecycleStage.PROMOTION_READY
                or not self._watch_id
            ):
                return DockedIgpuLifecycleInspection(
                    False, "docked_igpu.inspection_not_ready"
                )
            try:
                result = self._promotion.prepare(
                    self._watch_id, user_confirmed=False
                )
            except Exception:
                result = None
            if result is None:
                return DockedIgpuLifecycleInspection(
                    False, "docked_igpu.preview_unavailable"
                )
            preview = result.preview
            code = self._safe_code(result.code, "docked_igpu.preview_rejected")
            if preview is None:
                if code in {
                    "docked_igpu.watch_changed",
                    "docked_igpu.placement_changed",
                }:
                    self._status = self._action(code)
                return DockedIgpuLifecycleInspection(False, code)
            if preview.approval_token:
                self._status = self._action(
                    "docked_igpu.unexpected_transition_authority"
                )
                return DockedIgpuLifecycleInspection(
                    False,
                    "docked_igpu.unexpected_transition_authority",
                    current=preview.current,
                    target=preview.target,
                )
            blockers = tuple(
                self._safe_code(value, "transition.blocker_unavailable")
                for value in preview.blockers
            )
            if code in {
                "docked_igpu.watch_changed",
                "docked_igpu.placement_changed",
            }:
                self._status = self._action(code)
            return DockedIgpuLifecycleInspection(
                result.accepted and preview.ready,
                code,
                current=preview.current,
                target=preview.target,
                blockers=blockers,
            )

    def close(self) -> DockedIgpuLifecycleStatus:
        with self._lock:
            if self._closed:
                if (
                    self._status.code == "docked_igpu.lifecycle_close_incomplete"
                    and self._watch_id
                    and self._cancel_locked()
                ):
                    self._status = DockedIgpuLifecycleStatus(
                        DockedIgpuLifecycleStage.CLOSED,
                        "docked_igpu.lifecycle_closed",
                        0,
                    )
                return self._status
            cancelled = not self._watch_id or self._cancel_locked()
            self._closed = True
            self._status = DockedIgpuLifecycleStatus(
                DockedIgpuLifecycleStage.CLOSED,
                (
                    "docked_igpu.lifecycle_closed"
                    if cancelled
                    else "docked_igpu.lifecycle_close_incomplete"
                ),
                0,
            )
            return self._status

    def _arm_locked(self) -> DockedIgpuLifecycleStatus:
        try:
            result = self._promotion.arm()
        except Exception:
            result = None
        if result is None:
            self._status = self._idle("docked_igpu.arm_unavailable")
            return self._status
        if not result.accepted or result.watch is None:
            if result.code == "docked_igpu.watch_already_active":
                self._status = self._action("docked_igpu.watch_ownership_lost")
            else:
                self._status = self._idle(
                    self._safe_code(result.code, "docked_igpu.arm_rejected")
                )
            return self._status
        self._watch_id = result.watch.watch_id
        self._status = self._from_watch(result.watch.stage, result.watch.reason_code)
        return self._status

    def _poll_locked(self) -> DockedIgpuLifecycleStatus:
        try:
            result = self._promotion.poll(self._watch_id)
        except Exception:
            result = None
        if result is None or not result.accepted or result.watch is None:
            self._status = self._action(
                self._safe_code(result.code, "docked_igpu.poll_rejected")
                if result is not None
                else "docked_igpu.poll_unavailable"
            )
            return self._status
        watch = result.watch
        if watch.stage is DockedIgpuExitStage.CANCELLED:
            code = self._safe_code(
                watch.reason_code, "docked_igpu.watch_cancelled"
            )
            if not self._cancel_locked():
                self._status = self._action("docked_igpu.cancel_incomplete")
            else:
                self._status = self._idle(code)
            return self._status
        self._status = self._from_watch(watch.stage, watch.reason_code)
        return self._status

    def _cancel_locked(self) -> bool:
        watch_id = self._watch_id
        if not watch_id:
            return True
        try:
            cancelled = self._promotion.cancel(watch_id) is True
        except Exception:
            cancelled = False
        if cancelled:
            self._watch_id = ""
        return cancelled

    def _from_watch(
        self, stage: DockedIgpuExitStage, code: str
    ) -> DockedIgpuLifecycleStatus:
        code = self._safe_code(code, "docked_igpu.watch_invalid")
        if stage is DockedIgpuExitStage.WATCHING:
            return DockedIgpuLifecycleStatus(
                DockedIgpuLifecycleStage.WATCHING,
                code,
                self._poll_interval_ms,
            )
        if stage is DockedIgpuExitStage.PROMOTION_READY:
            inspection_available = self._promotion.inspection_supported
            return DockedIgpuLifecycleStatus(
                DockedIgpuLifecycleStage.PROMOTION_READY,
                code,
                0 if inspection_available else self._poll_interval_ms,
                inspection_available=inspection_available,
            )
        if stage is DockedIgpuExitStage.ACTION_REQUIRED:
            return self._action(code)
        return self._idle(code)

    def _idle(self, code: str) -> DockedIgpuLifecycleStatus:
        return DockedIgpuLifecycleStatus(
            DockedIgpuLifecycleStage.IDLE,
            code,
            self._idle_poll_interval_ms,
        )

    @staticmethod
    def _action(code: str) -> DockedIgpuLifecycleStatus:
        return DockedIgpuLifecycleStatus(
            DockedIgpuLifecycleStage.ACTION_REQUIRED,
            code,
            0,
            acknowledgement_required=True,
        )

    @staticmethod
    def _safe_code(value: str, fallback: str) -> str:
        return value if CODE_RE.fullmatch(value) else fallback
