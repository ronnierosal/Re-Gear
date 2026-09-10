"""Privacy-safe payloads for supervised presentation-transition recovery."""

from __future__ import annotations

from typing import Any

from ..application.supervised_transition import SupervisedTransitionStatus


def status_to_payload(status: SupervisedTransitionStatus) -> dict[str, Any]:
    """Expose the durable result that survives a Gamescope/UI restart.

    The acknowledgement ID is intentionally the only operation identity made
    available to Decky.  The journal itself stays backend-owned and private.
    """
    return {
        "schema_version": 1,
        "code": status.code,
        "acknowledgement_required": status.acknowledgement_required,
        "action_required": status.action_required,
        "acknowledgement_id": status.operation_id,
        "durable": status.durable,
        "target": status.target.value,
    }
