"""Production-composed regressions: retained results are not synthetic success."""
import inspect
import ast
import json
import tempfile
import unittest
from contextlib import nullcontext
from contextlib import contextmanager
from types import SimpleNamespace
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from tests.test_transition_orchestrator import snapshot, experimental_plan, FakeClockWaiter
from regear.adapters.transition_runtime import SnapshotTransitionObservationAdapter
from regear.application.transition_orchestrator import TransitionOrchestrator
from regear.application.supervised_transition import SupervisedPresentationTransitionService
from regear.delivery.transition_journal_store import FileTransitionJournalStore
from regear.domain.transition_journal import JournalEventKind, journal_to_dict
from regear.domain.models import GameState, Confidence
from regear.ports.audio_recovery import AudioRecoveryBlocked

OLD_BOOT = "11111111-1111-4111-8111-111111111111"
NEW_BOOT = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 10, 3, 7, 0, tzinfo=timezone.utc)


def supported(constructor, **kwargs):
    # Execute the unchanged production path on the old source as well.
    signature = inspect.signature(constructor)
    return constructor(**{k: v for k, v in kwargs.items() if k in signature.parameters})


class BootRetirementCompositionTests(unittest.TestCase):
    def test_acknowledgement_between_boot_audit_and_unlink_stays_removed(self):
        original = self.create_retained()
        acknowledgement = FileTransitionJournalStore(self.root)
        unlink = Path.unlink
        acknowledged = False

        def race(path, *args, **kwargs):
            nonlocal acknowledged
            if path == self.root / "active-transition.json" and not acknowledged:
                acknowledged = True
                acknowledgement.clear_terminal(original.operation_id)
            return unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", race):
            self.store.retire_after_boot(original.operation_id, OLD_BOOT, NEW_BOOT)
        self.assertTrue(acknowledged)
        self.assertIsNone(self.store.load_current())
        self.assertFalse(self.service().status().acknowledgement_required)
        audit = json.loads((self.root / "boot-retired-presentation.json").read_text())
        self.assertEqual(audit["journal"], journal_to_dict(original))
        self.assertEqual(self.mechanism.mock_calls, [])

    def test_interrupted_tunnel_claim_does_not_deadlock_boot_result_retirement(self):
        self.create_retained()
        self.boot = NEW_BOOT
        guard, _ = self.production_guard(claim=SimpleNamespace(stage="tunnel_remove_intent"))
        self.assertTrue(self.service(guard).reconcile_completion(self.port.observe()).finalized)
        self.assertIsNone(self.store.load_current())
        self.assertEqual(self.mechanism.mock_calls, [])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = FileTransitionJournalStore(self.root)
        self.discovery = Mock()
        self.port = SnapshotTransitionObservationAdapter(self.discovery)
        self.mechanism = Mock()
        self.clock = FakeClockWaiter()
        self.boot = OLD_BOOT
        self.engine = supported(TransitionOrchestrator,
            observations=self.port, mechanism=self.mechanism, journal_store=self.store,
            clock=self.clock, waiter=self.clock, read_boot_id=lambda: self.boot)

    def service(self, guard=nullcontext):
        return supported(SupervisedPresentationTransitionService,
            observations=self.port, orchestrator=self.engine, journal_store=self.store,
            integration_ready=lambda: True, read_boot_id=lambda: self.boot,
            boot_retirement_now=lambda: NOW, boot_retirement_guard=guard)

    def create_retained(self, failure=False):
        plan = experimental_plan(snapshot("connected-internal.json"))
        self.discovery.collect_snapshot.return_value = None if failure else self.portable()
        result = self.engine.run(plan)
        self.assertTrue(result.durable)
        self.assertEqual(result.journal.entries[-1].kind,
                         JournalEventKind.FAILED if failure else JournalEventKind.BLOCKED)
        self.assertTrue(self.service().status().acknowledgement_required)
        self.assertEqual(self.mechanism.mock_calls, [])
        return result.journal

    def portable(self):
        return replace(snapshot("portable.json"), observed_at=NOW.isoformat())

    def reconcile(self):
        current = self.port.observe()
        return self.service().reconcile_completion(current)

    def test_actual_blocked_result_retires_after_new_boot(self):
        original = self.create_retained()
        self.boot = NEW_BOOT
        result = self.reconcile()
        self.assertTrue(result.finalized)
        self.assertFalse(self.service().status().acknowledgement_required)
        audit = json.loads((self.root / "boot-retired-presentation.json").read_text())
        self.assertEqual(audit["journal"], journal_to_dict(original))
        self.assertEqual(audit["reason"], "presentation.new_boot_acknowledgement_retired")
        self.assertEqual(self.mechanism.mock_calls, [])

    def test_actual_predispatch_failure_retires_preserving_failure(self):
        original = self.create_retained(failure=True)
        self.discovery.collect_snapshot.return_value = self.portable()
        self.boot = NEW_BOOT
        result = self.reconcile()
        self.assertTrue(result.finalized)
        self.assertFalse(self.service().status().acknowledgement_required)
        audit = json.loads((self.root / "boot-retired-presentation.json").read_text())
        self.assertEqual(audit["journal"], journal_to_dict(original))
        self.assertEqual(audit["journal"]["entries"][-1]["kind"], "failed")
        self.assertEqual(self.mechanism.mock_calls, [])

    def test_same_boot_service_reload_retains(self):
        original = self.create_retained()
        self.assertFalse(self.reconcile().finalized)
        self.assertEqual(self.store.load_current(), original)

    def test_legacy_journal_cannot_be_retrofitted(self):
        original = self.create_retained()
        value = journal_to_dict(original)
        value.pop("origin_boot_id", None)
        (self.root / "presentation-origin-boot.json").unlink(missing_ok=True)
        (self.root / "active-transition.json").write_text(json.dumps(value))
        self.boot = NEW_BOOT
        self.assertFalse(self.reconcile().finalized)
        self.assertTrue(self.service().status().acknowledgement_required)

    def test_invalid_unavailable_or_changing_boot_retains(self):
        original = self.create_retained()
        for boot in ("", "unknown", "00000000-0000-0000-0000-000000000000"):
            self.boot = boot
            self.assertFalse(self.reconcile().finalized)
            self.assertEqual(self.store.load_current(), original)
        self.boot = NEW_BOOT
        service = self.service()
        service._read_boot_id = Mock(side_effect=[NEW_BOOT, OLD_BOOT])
        self.assertFalse(service.reconcile_completion(self.port.observe()).finalized)
        self.assertEqual(self.store.load_current(), original)

    def test_supplied_good_cache_cannot_override_live_unsafe_observation(self):
        original = self.create_retained()
        cached = self.port.observe()
        self.boot = NEW_BOOT
        for fresh in (snapshot("connected-internal.json"),
                      replace(self.portable(), game_state=GameState.RUNNING),
                      replace(self.portable(), game_state=GameState.UNKNOWN),
                      replace(self.portable(), observed_at="2026-10-03T06:59:00+00:00"),
                      replace(self.portable(), observed_at="2026-10-03T07:00:01+00:00"),
                      replace(self.portable(), observed_at="bad"),
                      replace(self.portable(), gamescope=replace(self.portable().gamescope,
                                                               confidence=Confidence.UNKNOWN)), None):
            with self.subTest(fresh=fresh):
                self.discovery.collect_snapshot.return_value = fresh
                self.assertFalse(self.service().reconcile_completion(cached).finalized)
                self.assertEqual(self.store.load_current(), original)
        self.assertEqual(self.mechanism.mock_calls, [])

    def test_guard_failure_and_audio_block_preserve(self):
        original = self.create_retained()
        self.boot = NEW_BOOT
        for failure in (ValueError("unresolved whole dock"), AudioRecoveryBlocked("audio.recovery_required")):
            service = self.service(guard=Mock(side_effect=failure))
            result = service.reconcile_completion(self.port.observe())
            self.assertFalse(result.finalized)
            self.assertTrue(result.hold_portable)
            self.assertEqual(self.store.load_current(), original)

    def test_archive_failure_and_active_identity_mismatch_preserve(self):
        original = self.create_retained()
        self.boot = NEW_BOOT
        with patch.object(self.store, "_replace", side_effect=OSError("archive failed")):
            self.assertFalse(self.reconcile().finalized)
        self.assertEqual(self.store.load_current(), original)
        with self.assertRaises(ValueError):
            self.store.retire_after_boot("different-operation", OLD_BOOT, NEW_BOOT)
        self.assertEqual(self.store.load_current(), original)

    def test_strict_sync_before_removal_and_post_removal_failure_restore(self):
        original = self.create_retained()
        self.boot = NEW_BOOT
        with patch.object(self.store, "_sync_directory", side_effect=OSError("archive sync")):
            self.assertFalse(self.reconcile().finalized)
        self.assertEqual(self.store.load_current(), original)
        with patch.object(self.store, "_sync_directory", side_effect=[None, OSError("unlink sync"), None]) as sync:
            self.assertFalse(self.reconcile().finalized)
            self.assertTrue(all(call.kwargs.get("strict") for call in sync.call_args_list))
        self.assertEqual(self.store.load_current(), original)

    def test_foreign_trial_and_non_observation_failures_retain(self):
        original = self.create_retained(failure=True)
        self.discovery.collect_snapshot.return_value = self.portable()
        self.boot = NEW_BOOT
        source = journal_to_dict(original)
        for kind in ("foreign", "trial", "other_failure", "incomplete"):
            value = json.loads(json.dumps(source))
            if kind == "foreign":
                value["entries"][0]["details"]["capability"] = "sleep"
            elif kind == "trial":
                value["entries"][0]["details"]["launch_policy"] = "future_trial"
            elif kind == "other_failure":
                value["entries"][-1]["details"]["reason_code"] = "journal.persist_failed"
            else:
                value["entries"].pop()
            (self.root / "active-transition.json").write_text(json.dumps(value))
            self.assertFalse(self.reconcile().finalized)
            self.assertIsNotNone(self.store.load_current())

    def test_origin_identity_cannot_change_on_progress(self):
        self.create_retained()
        active = self.store.load_current()
        current = replace(active, entries=active.entries[:1])
        (self.root / "active-transition.json").write_text(json.dumps(journal_to_dict(current)))
        for origin in ("", NEW_BOOT):
            with self.assertRaises(ValueError):
                self.store.save(replace(current, origin_boot_id=origin))

    def test_actual_main_composition_wires_private_boot_and_guard(self):
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        method = next(n for n in ast.walk(ast.parse(source))
                      if isinstance(n, ast.FunctionDef) and n.name == "_presentation_transition_service")
        calls = {n.func.id: n for n in ast.walk(method)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id in {"TransitionOrchestrator", "SupervisedPresentationTransitionService"}}
        for name in calls:
            args = {k.arg: ast.unparse(k.value) for k in calls[name].keywords}
            self.assertEqual(args["read_boot_id"], "self._boot_session_id")
        self.assertEqual({k.arg: ast.unparse(k.value) for k in calls[
            "SupervisedPresentationTransitionService"].keywords}["boot_retirement_guard"], "boot_retirement_guard")

    def production_guard(self, *, audio_pending=None, claim=None, trial=None, stat_error=None):
        # Execute the actual nested production guard, not a reimplementation.
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        guard = next(n for n in ast.walk(ast.parse(source))
                     if isinstance(n, ast.FunctionDef) and n.name == "boot_retirement_guard")
        audio = Mock()
        audio.pending.return_value = audio_pending
        audio_store = Mock()
        audio_store.transaction.return_value = nullcontext(audio)
        claim_store, trial_store = Mock(), Mock()
        claim_store.load.return_value = claim
        trial_store.read.return_value = trial
        path = Mock()
        if stat_error is not None:
            path.lstat.side_effect = stat_error
        namespace = dict(contextmanager=contextmanager, nullcontext=nullcontext,
            Path=Mock(return_value=path), AUDIO_TRIAL_ROOT="/fixture/audio",
            AudioTrialStore=Mock(return_value=audio_store),
            WholeDockClaimStore=Mock(return_value=claim_store),
            PortableTrialStore=Mock(return_value=trial_store), journal_root=self.root,
            presentation_state_root=self.root)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[guard], type_ignores=[])),
                     "production-main-boot-guard", "exec"), namespace)
        return namespace["boot_retirement_guard"], namespace

    def test_production_guard_retains_pending_audio_whole_dock_or_trial(self):
        original = self.create_retained()
        self.boot = NEW_BOOT
        for kwargs in (dict(audio_pending=object()), dict(claim=SimpleNamespace(stage="prepared")),
                       dict(claim=SimpleNamespace(stage="unknown")), dict(trial={"operation_id": "trial"}),
                       dict(stat_error=PermissionError("unreadable root"))):
            with self.subTest(kwargs=kwargs):
                guard, namespace = self.production_guard(**kwargs)
                self.assertFalse(self.service(guard).reconcile_completion(self.port.observe()).finalized)
                self.assertEqual(self.store.load_current(), original)
        self.assertEqual(self.mechanism.mock_calls, [])

    def test_production_guard_verified_no_transactions_retires(self):
        original = self.create_retained()
        self.boot = NEW_BOOT
        guard, namespace = self.production_guard()
        self.assertTrue(self.service(guard).reconcile_completion(self.port.observe()).finalized)
        namespace["AudioTrialStore"].assert_called_once()
        namespace["WholeDockClaimStore"].assert_called_once_with(self.root)
        self.assertEqual(self.mechanism.mock_calls, [])

    def test_production_guard_missing_audio_root_does_not_invent_pending_trial(self):
        self.create_retained(failure=True)
        self.discovery.collect_snapshot.return_value = self.portable()
        self.boot = NEW_BOOT
        guard, namespace = self.production_guard(stat_error=FileNotFoundError("no audio trial root"))
        self.assertTrue(self.service(guard).reconcile_completion(self.port.observe()).finalized)
        namespace["AudioTrialStore"].assert_not_called()

    def test_mutation_started_blocked_and_recovered_histories_retain(self):
        original = self.create_retained()
        self.boot = NEW_BOOT
        requested, observed, blocked = journal_to_dict(original)["entries"]
        for tail in (("validated", "planned", "step_started", "blocked"),
                     ("validated", "planned", "recovery_started", "recovery_verified"),
                     ("validated", "planned", "step_started", "failed")):
            value = journal_to_dict(original)
            entries = [requested, observed]
            for event in tail:
                entry = json.loads(json.dumps(blocked))
                entry["sequence"] = len(entries) + 1
                entry["kind"] = event
                entries.append(entry)
            value["entries"] = entries
            (self.root / "active-transition.json").write_text(json.dumps(value))
            self.assertFalse(self.reconcile().finalized)
            self.assertIsNotNone(self.store.load_current())


if __name__ == "__main__":
    unittest.main()
