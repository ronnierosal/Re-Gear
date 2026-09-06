"""Retire proven successes, preserving durable Portable intent across reloads.

No display/session mutation occurs here. Failed, recovered, foreign and incomplete
journals retain their existing explicit acknowledgement/recovery paths.
"""
from dataclasses import dataclass

from ..domain.control_plane import PlacementState
from ..domain.inference import infer_placement
from ..domain.models import GameState
from ..domain.transition_journal import JournalEventKind
from ..profiles.registry import resolve_runtime_profiles
from .automatic_dock import verified_egpu_absent


@dataclass(frozen=True, slots=True)
class PresentationCompletion:
    code: str
    finalized: bool = False
    hold_portable: bool = False


def committed_target(journal) -> PlacementState:
    if not journal or not journal.entries:
        return PlacementState.UNKNOWN
    first, last = journal.entries[0], journal.entries[-1]
    if (
        first.code != "request.accepted"
        or dict(first.details).get("capability") != "presentation_transition"
        or last.kind is not JournalEventKind.COMMITTED
        or last.code not in {"transition.committed", "transition.no_op"}
    ):
        return PlacementState.UNKNOWN
    target = dict(first.details).get("target_placement")
    if target not in {PlacementState.PORTABLE.value, PlacementState.DOCKED_EGPU.value}:
        return PlacementState.UNKNOWN
    return last.placement if last.placement.value == target else PlacementState.UNKNOWN


def reconcile_presentation_completion(store, current) -> PresentationCompletion:
    """Called under the presentation owner's lock with fresh observed evidence."""
    try:
        active = store.load_current()
        finalized = False
        if active is not None:
            if active.entries and dict(active.entries[0].details).get('launch_policy') == 'portable_vulkan_trial':
                return PresentationCompletion("completion.explicit_result_required", hold_portable=True)
            target = committed_target(active)
            if target is PlacementState.UNKNOWN:
                return PresentationCompletion("completion.explicit_result_required")
            snapshot = current.snapshot
            profiles = resolve_runtime_profiles(snapshot)
            if (
                not current.sample_id
                or not current.generation
                or not profiles.exact_host
                or snapshot.game_state is not GameState.IDLE
                or infer_placement(snapshot) is not target
                or (target is PlacementState.DOCKED_EGPU and not profiles.exact_egpu)
            ):
                return PresentationCompletion("completion.postconditions_unverified")
            # Archive before releasing the active slot. If this fails, do not
            # erase evidence or re-arm automatic docking.
            store.retire_committed(active.operation_id)
            finalized = True
        receipt = store.load_completed()
        target = committed_target(receipt)
        if receipt is not None and target is PlacementState.UNKNOWN:
            return PresentationCompletion("completion.receipt_unverified", hold_portable=True)
        if target is PlacementState.PORTABLE:
            if verified_egpu_absent(current.snapshot):
                store.clear_completed(receipt.operation_id)
                return PresentationCompletion("completion.portable_released", finalized)
            return PresentationCompletion("completion.portable_held", finalized, True)
        return PresentationCompletion(
            "completion.tv_finalized" if finalized else "completion.idle", finalized
        )
    except Exception:
        # Failure to load a durable hold must not silently permit redocking.
        return PresentationCompletion("completion.storage_unavailable", hold_portable=True)
