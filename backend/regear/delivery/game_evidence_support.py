"""Identity-free delivery mapping for one-shot game/GPU evidence."""

from __future__ import annotations

from ..application.game_evidence_support import SupportGameEvidence


def game_evidence_to_event_details(
    value: SupportGameEvidence,
) -> dict[str, object]:
    return {
        "game_state": value.game_state.value,
        "identity_exact": value.identity_exact,
        "egpu_client": {
            "status": value.egpu_client_status.value,
            "count": value.egpu_client_count,
            "reason": value.egpu_client_reason,
        },
        "internal_render": {
            "status": value.internal_render.status.value,
            "runtime": value.internal_render.runtime_kind.value,
            "active_engine_count": value.internal_render.active_engine_count,
            "reason": value.internal_render.reason_code,
            "placement": value.internal_render.placement.value,
        },
        "external_render": {
            "status": value.external_render.status.value,
            "runtime": value.external_render.runtime_kind.value,
            "active_engine_count": value.external_render.active_engine_count,
            "reason": value.external_render.reason_code,
            "placement": value.external_render.placement.value,
        },
    }
