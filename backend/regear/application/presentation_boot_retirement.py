"""Retire acknowledgement only; never reinterpret a failure as successful work."""
from datetime import datetime, timezone

from ..domain.control_plane import PlacementState
from ..domain.inference import infer_placement
from ..domain.models import Confidence, GameState
from ..domain.transition_journal import JournalEventKind, valid_boot_id
from .automatic_dock import verified_egpu_absent
from .presentation_completion import PresentationCompletion


def eligible_boot_result(journal) -> bool:
    if not journal or not journal.terminal or not valid_boot_id(journal.origin_boot_id):
        return False
    first, last = journal.entries[0], journal.entries[-1]
    details = dict(first.details)
    if (first.kind is not JournalEventKind.REQUESTED or first.code != "request.accepted"
            or details.get("capability") != "presentation_transition"
            or details.get("target_placement") not in {"portable", "docked_egpu"}
            or any("launch_policy" in dict(entry.details) for entry in journal.entries)):
        return False
    # Only pre-dispatch blocks and this exact pre-dispatch observation failure
    # have affirmative evidence that no safety transaction started.
    if last.kind is JournalEventKind.FAILED:
        return (len(journal.entries) == 2 and last.code == "transition.failed"
                and dict(last.details) == {"reason_code": "observation.unavailable"})
    if last.kind is JournalEventKind.BLOCKED:
        return (last.code == "transition.blocked" and all(entry.kind in {
            JournalEventKind.REQUESTED, JournalEventKind.OBSERVED,
            JournalEventKind.VALIDATED, JournalEventKind.PLANNED,
            JournalEventKind.BLOCKED} for entry in journal.entries))
    return False


def reconcile_boot_result(store, observations, read_boot_id, now, guard):
    """None means ordinary completion policy still owns the result."""
    if read_boot_id is None or guard is None:
        return None
    try:
        active = store.load_current()
        if not eligible_boot_result(active):
            return None
        before = read_boot_id()
        if not valid_boot_id(before) or before == active.origin_boot_id:
            return None
        with guard():
            # Never trust the supplied observer-loop cache for boot retirement.
            started = now()
            fresh = observations.observe()
            after = read_boot_id()
            ended = now()
            if before != after or not valid_boot_id(after):
                return PresentationCompletion("completion.boot_unverified", hold_portable=True)
            snapshot = fresh.snapshot
            timestamp = datetime.fromisoformat(snapshot.observed_at.replace("Z", "+00:00"))
            if (timestamp.tzinfo is None or started.tzinfo is None or ended.tzinfo is None
                    or ended < started or not 0 <= (ended - timestamp).total_seconds() <= 5
                    or timestamp < started
                    or not fresh.sample_id or not fresh.generation
                    or snapshot.game_state is not GameState.IDLE
                    or snapshot.gamescope.confidence is not Confidence.VERIFIED
                    or not snapshot.gamescope.running
                    or infer_placement(snapshot) is not PlacementState.PORTABLE
                    or not verified_egpu_absent(snapshot)):
                return PresentationCompletion("completion.boot_postconditions_unverified", hold_portable=True)
            store.retire_after_boot(active.operation_id, active.origin_boot_id, after)
            return PresentationCompletion("completion.boot_acknowledgement_retired", finalized=True)
    except Exception:
        return PresentationCompletion("completion.boot_retirement_unavailable", hold_portable=True)


def utc_now():
    return datetime.now(timezone.utc)
