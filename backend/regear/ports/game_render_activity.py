"""Private binding and DRM counter boundaries for read-only game evidence."""

from __future__ import annotations

from typing import Protocol

from ..domain.game_render_activity import (
    DrmEngineCounterSample,
    DrmRenderBinding,
)
from ..domain.game_runtime import GameProcessInstance
from ..domain.models import ObservedSnapshot


class DrmRenderBindingPort(Protocol):
    def resolve(self, snapshot: ObservedSnapshot) -> DrmRenderBinding | None: ...


class DrmEngineCounterPort(Protocol):
    def sample(
        self,
        processes: tuple[GameProcessInstance, ...],
        binding: DrmRenderBinding,
    ) -> DrmEngineCounterSample: ...
