"""Private, pure evidence guards for preserving an iGPU game on an eGPU TV.

These contracts do not collect evidence or implement cross-GPU presentation.
The application must supply fresh, mutually consistent observations, bound to the same sample/generation. Instance IDs
must include process birth identity (and boot/session identity), never PID alone.
Renderer grades describe actual rendering evidence, not environment selectors or
an open DRM descriptor. Do not serialize these private identities to public status.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Confidence, DisplayKind, GameState, GpuRole, ObservedSnapshot


@dataclass(frozen=True, slots=True)
class GameSessionEvidence:
    session_id: str
    game_instance_id: str
    game_running: bool | None
    game_confidence: Confidence
    game_render_gpu_stable_id: str
    game_render_confidence: Confidence
    compositor_instance_id: str
    compositor_render_gpu_stable_id: str
    compositor_render_confidence: Confidence


@dataclass(frozen=True, slots=True)
class IgpuTvBinding:
    session_id: str
    game_instance_id: str
    compositor_instance_id: str
    igpu_stable_id: str
    egpu_stable_id: str
    tv_stable_id: str
    tv_connector: str


@dataclass(frozen=True, slots=True)
class BindingResult:
    binding: IgpuTvBinding | None
    blockers: tuple[str, ...]


def bind_igpu_tv(
    snapshot: ObservedSnapshot,
    evidence: GameSessionEvidence,
    *,
    igpu_stable_id: str,
    egpu_stable_id: str,
    tv_stable_id: str,
) -> BindingResult:
    """Bind one exact original game/session and target, or return no binding."""
    displays = [d for d in snapshot.displays if d.stable_id == tv_stable_id]
    binding = IgpuTvBinding(
        evidence.session_id, evidence.game_instance_id,
        evidence.compositor_instance_id, igpu_stable_id, egpu_stable_id,
        tv_stable_id, displays[0].connector if len(displays) == 1 else "",
    )
    blockers = check_igpu_tv(snapshot, evidence, binding)
    return BindingResult(None if blockers else binding, blockers)


def check_igpu_tv(
    snapshot: ObservedSnapshot,
    evidence: GameSessionEvidence,
    binding: IgpuTvBinding,
    *,
    require_presented: bool = False,
    allow_idle: bool = False,
) -> tuple[str, ...]:
    """Revalidate preservation; post-presentation also requires verified scanout.

    Empty blockers prove only the supplied observations satisfy this contract.
    They never authorize a mechanism, GPU migration, or physical disconnect.
    """
    # Idle here is an observation, not proof of natural exit. The application
    # must independently prove the original game exited before promotion.
    idle = (allow_idle and snapshot.game_state == GameState.IDLE
            and evidence.game_running is False
            and evidence.game_confidence == Confidence.VERIFIED)
    blockers: list[str] = []
    for name in ("session_id", "game_instance_id", "compositor_instance_id"):
        if name == "game_instance_id" and idle:
            continue
        bound = getattr(binding, name)
        if not bound or getattr(evidence, name) != bound:
            blockers.append(f"{name}_changed_or_unknown")
    if not idle and (snapshot.game_state != GameState.RUNNING
            or evidence.game_running is not True
            or evidence.game_confidence != Confidence.VERIFIED):
        blockers.append("original_game_not_verified_running")
    if (not binding.igpu_stable_id or not binding.egpu_stable_id
            or binding.igpu_stable_id == binding.egpu_stable_id):
        blockers.append("gpu_binding_invalid")
    for identity, role, label in (
        (binding.igpu_stable_id, GpuRole.INTERNAL, "igpu"),
        (binding.egpu_stable_id, GpuRole.EXTERNAL, "egpu"),
    ):
        matches = [g for g in snapshot.gpus if g.stable_id == identity]
        if (len(matches) != 1 or matches[0].present is not True
                or matches[0].role != role
                or matches[0].confidence != Confidence.VERIFIED):
            blockers.append(f"{label}_identity_not_verified")
    if not idle and (evidence.game_render_confidence != Confidence.VERIFIED
            or evidence.game_render_gpu_stable_id != binding.igpu_stable_id):
        blockers.append("game_renderer_not_verified_igpu")
    if (evidence.compositor_render_confidence != Confidence.VERIFIED
            or evidence.compositor_render_gpu_stable_id != binding.igpu_stable_id
            or snapshot.gamescope.running is not True
            or snapshot.gamescope.confidence != Confidence.VERIFIED
            or snapshot.gamescope.render_gpu_stable_id != binding.igpu_stable_id):
        blockers.append("compositor_renderer_not_verified_igpu")
    displays = [d for d in snapshot.displays if d.stable_id == binding.tv_stable_id]
    connectors = [d for d in snapshot.displays if d.connector == binding.tv_connector]
    if (not binding.tv_stable_id or not binding.tv_connector
            or len(displays) != 1 or len(connectors) != 1
            or displays[0].connector != binding.tv_connector):
        blockers.append("tv_identity_changed_or_ambiguous")
        return tuple(blockers)
    tv = displays[0]
    if (tv.kind != DisplayKind.EXTERNAL or tv.connected is not True
            or tv.edid_ready is not True or tv.confidence != Confidence.VERIFIED):
        blockers.append("tv_connection_not_verified")
    if (tv.owning_gpu_stable_id != binding.egpu_stable_id
            or tv.owning_gpu_confidence != Confidence.VERIFIED):
        blockers.append("tv_owner_not_verified_egpu")
    if require_presented and (
        tv.active is not True or tv.active_confidence != Confidence.VERIFIED
        or tv.mode_committed is not True
    ):
        blockers.append("tv_presentation_not_verified")
    return tuple(blockers)
