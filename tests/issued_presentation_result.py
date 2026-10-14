"""Issue a real blocked result through preview/execute; fixtures perform no OS actions."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
from tests.test_transition_orchestrator import snapshot, FakeClockWaiter
from tests.test_main_process_delivery import load_main_module
from regear.adapters.transition_runtime import SnapshotTransitionObservationAdapter
from regear.application.transition_orchestrator import TransitionOrchestrator
from regear.application.supervised_transition import SupervisedPresentationTransitionService
from regear.application.shared_transition_journal import SharedTransitionJournalService
from regear.delivery import build_profile_config
from regear.delivery.transition_journal_store import FileTransitionJournalStore
from regear.domain.control_plane import PlacementState


def issue_result(root):
    discovery = Mock()
    discovery.collect_snapshot.side_effect = [snapshot("connected-internal.json"),
        snapshot("connected-internal.json"), snapshot("portable.json")]
    observations = SnapshotTransitionObservationAdapter(discovery)
    store = FileTransitionJournalStore(root)
    mechanism, clock = Mock(), FakeClockWaiter()
    engine = TransitionOrchestrator(observations=observations, mechanism=mechanism,
        journal_store=store, clock=clock, waiter=clock)
    service = SupervisedPresentationTransitionService(observations=observations,
        orchestrator=engine, journal_store=store, integration_ready=lambda: True)
    preview = service.preview(PlacementState.DOCKED_EGPU, user_confirmed=True)
    assert preview.ready, preview.blockers
    result = service.execute(preview.approval_token)
    assert result.accepted and result.outcome.kind.value == "blocked", result
    assert not mechanism.mock_calls
    assert len(result.operation_id) == 24
    with patch.object(build_profile_config, "BUILD_PROFILE", "production"):
        module = load_main_module(real_dock_gate=True)
    plugin = module.Plugin.__new__(module.Plugin)
    plugin._presentation_transition_service = Mock(return_value=service)
    plugin._transition_journal_service = Mock(return_value=SharedTransitionJournalService(store))
    plugin._automatic_dock, plugin._topology_wakeup = Mock(), Mock()
    return plugin, store, result.operation_id


async def emitted():
    with tempfile.TemporaryDirectory() as directory:
        plugin, store, identity = issue_result(Path(directory).resolve())
        return {"operation_id": identity,
                "journal": await plugin.get_transition_journal_status(),
                "status": await plugin.get_supervised_tv_switch_status()}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(emitted())))
