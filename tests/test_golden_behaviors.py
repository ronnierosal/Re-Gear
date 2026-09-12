"""Regression tests for the golden contract gate itself."""

import copy
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import check_golden_behaviors as gate


class GoldenGateTests(unittest.TestCase):
    # The floor the repository manifest may never fall below. The gate executes
    # whatever contracts/golden-behaviors.json happens to list, so without this
    # a single-file edit that deletes a behavior, or swaps a failing test_id for
    # a passing one, leaves both the checker and this suite green while the
    # regression it was protecting ships. Pinning the floor here is deliberate
    # duplication: weakening coverage becomes a visible edit to the enforcement
    # tests as well as the contract, which is the review docs/GOLDEN_BEHAVIORS.md
    # asks for. Each tuple is a minimum, never a maximum - adding golden
    # coverage stays a one-file change.
    GOLDEN_COVERAGE = {
        "automatic-tv-readiness": (
            "tests.test_connection_readiness.ConnectionReadinessTests.test_per_layer_stages_and_independent_hdmi_audio_quorums",
            "tests.test_connection_readiness.ConnectionReadinessTests.test_identity_change_invalidates_accumulated_stability",
            "tests.test_connection_readiness.ConnectionReadinessTests.test_unknown_game_fails_closed_after_other_layers_are_ready",
            "tests.test_connection_readiness.ConnectionReadinessTests.test_unavailable_session_never_readies_even_with_inconsistent_flags",
        ),
        "automatic-dock-one-shot": (
            "tests.test_automatic_dock.AutomaticDockCoordinatorTests.test_exact_ready_idle_attach_requests_once_until_absent",
            "tests.test_automatic_dock.AutomaticDockCoordinatorTests.test_partial_identity_does_not_rearm_attempt_or_portable_suppression",
            "tests.test_automatic_dock.AutomaticDockCoordinatorTests.test_running_game_and_unready_link_wait_without_consuming_attempt",
            "tests.test_automatic_dock.AutomaticDockCoordinatorTests.test_portable_return_suppresses_same_attachment_until_removed",
        ),
        "automatic-recovery-bounded": (
            "tests.test_automatic_link_recovery.AutomaticRecoveryTests.test_no_restart_from_startup_with_a_dock_already_present",
            "tests.test_automatic_link_recovery.AutomaticRecoveryTests.test_ten_seconds_then_cooldown_after_completion_and_two_attempt_cap",
            "tests.test_automatic_link_recovery.AutomaticRecoveryTests.test_gpu_arrival_stops_retry_even_if_later_observation_loses_gpu",
            "tests.test_automatic_link_recovery.AutomaticRecoveryTests.test_unknown_absence_and_identity_change_do_not_rearm",
        ),
        "automatic-recovery-consent": (
            "tests.test_automatic_link_recovery.AutomaticRecoveryTests.test_recovery_consent_is_separate_default_off_and_persisted",
            "tests.test_automatic_link_recovery.AutomaticRecoveryTests.test_disabled_or_unresolved_transport_never_dispatches",
        ),
        "recovery-fresh-game-guard": (
            "tests.test_main_link_recovery.LinkRecoveryStrategySelectionTests.test_manual_reservation_rechecks_game_user_transport_and_journal",
            "tests.test_main_link_recovery.LinkRecoveryStrategySelectionTests.test_concurrent_confirmed_rpcs_issue_only_one_restart",
            "tests.test_main_link_recovery.AutomaticRecoveryIntegrationTests.test_fresh_guarded_recovery_and_separate_consent",
            "tests.test_automatic_recovery_dispatch.AutomaticRecoveryDispatchTests.test_game_start_at_dispatch_refuses_restart",
            "tests.test_automatic_recovery_dispatch.AutomaticRecoveryDispatchTests.test_unknown_game_at_dispatch_refuses_restart",
            "tests.test_automatic_recovery_dispatch.AutomaticRecoveryDispatchTests.test_idle_dispatch_preserves_recovery",
            "tests.test_automatic_recovery_dispatch.AutomaticRecoveryDispatchTests.test_changed_dispatch_authority_refuses_restart",
        ),
        "safe-disconnect-no-premature-clearance": (
            "tests.test_safe_undock_readiness.SafeUndockReadinessTests.test_complete_portable_evidence_is_ready_only_for_revalidation",
            "tests.test_safe_undock_readiness.SafeUndockReadinessTests.test_protected_or_incomplete_client_scan_never_appears_ready",
            "tests.test_safe_undock_readiness.SafeUndockReadinessTests.test_game_and_portable_fallback_gates_fail_closed",
            "tests.test_safe_undock_readiness.SafeUndockReadinessTests.test_topology_display_staleness_and_binding_change_invalidate_or_block",
        ),
        "restoration-before-presentation": (
            "tests.test_audio_recovery_transition.AudioRecoveryTransitionTests.test_restore_observed_and_persisted_before_presentation",
            "tests.test_audio_recovery_transition.AudioRecoveryTransitionTests.test_unknown_portable_or_changed_identity_blocks_all_presentation_commands",
            "tests.test_audio_recovery_transition.AudioRecoveryTransitionTests.test_uncertain_restore_command_never_runs_presentation",
            "tests.test_audio_recovery_transition.AudioRecoveryTransitionTests.test_pending_blocks_normal_paths_without_implicit_restoration",
        ),
    }

    # The promoted hardware reference. load_manifest only checks that these look
    # like a revision and a digest, so 40 f's and 64 zeros validate cleanly.
    # Promotion is a product decision with its own evidence, so swapping the
    # immutable artifact has to be an explicit edit here too.
    GOLDEN_BASELINE = {
        "id": "checkpoint/0.3.82-auto-tv",
        "source_revision": "09ff57128ca6e0526f4b5376af825d87557c0f2e",
        "artifact_sha256": "c27e48366daa4374d49d02128e40c27e038cafa87488dcf449b3863b1841b06f",
        "evidence": "docs/EGPU_0382_CHECKPOINT.md",
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "evidence.md").write_text("Verified baseline", encoding="utf-8")
        (self.root / "source.py").write_text("", encoding="utf-8")
        self.path = self.root / "manifest.json"
        self.manifest = {
            "schema_version": 1,
            "baseline": {
                "id": "golden-1",
                "source_revision": "a" * 40,
                "artifact_sha256": "b" * 64,
                "evidence": "evidence.md",
            },
            "behaviors": [
                {
                    "id": "preserve",
                    "contract": "Preserve working behavior",
                    "test_ids": ["test_golden_fixture.Example.test_ok"],
                    "source_paths": ["source.py"],
                    "hardware_cases": [],
                }
            ],
        }

    def load(self):
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")
        return gate.load_manifest(self.path, self.root)

    def fixture(self, outcome):
        module = types.ModuleType("test_golden_fixture")

        def test_ok(test):
            if outcome == "skip":
                test.skipTest("missing prerequisites")
            elif outcome == "fail":
                test.fail("regression")
            elif outcome == "error":
                raise RuntimeError("regression")

        module.Example = type(
            "Example",
            (unittest.TestCase,),
            {"__module__": module.__name__, "test_ok": test_ok},
        )
        return patch.dict(sys.modules, {module.__name__: module})

    def test_repository_golden_contracts(self):
        manifest = gate.load_manifest(gate.ROOT / "contracts/golden-behaviors.json")
        test_path = str(gate.ROOT / "tests")
        with patch.object(sys, "path", [test_path, *sys.path]):
            suite = gate.load_tests(manifest)
            output = io.StringIO()
            self.assertTrue(gate.run_tests(suite, output), output.getvalue())

    def repository_manifest(self):
        return gate.load_manifest(gate.ROOT / "contracts/golden-behaviors.json")

    def test_repository_manifest_preserves_every_pinned_behavior_and_test(self):
        """Coverage may grow, never shrink, and never quietly change identity."""
        behaviors = {
            item["id"]: item["test_ids"]
            for item in self.repository_manifest()["behaviors"]
        }
        self.assertEqual(sorted(behaviors), sorted(self.GOLDEN_COVERAGE))
        for name, pinned in self.GOLDEN_COVERAGE.items():
            with self.subTest(behavior=name):
                missing = [test for test in pinned if test not in behaviors[name]]
                self.assertEqual(
                    missing,
                    [],
                    f"{name} no longer claims golden tests it used to claim. "
                    "Renaming or replacing a golden test must preserve its "
                    "assertions and update this floor in the same change, with "
                    "an explanation; dropping one silently is the regression "
                    "this guard exists to block.",
                )

    def test_repository_baseline_provenance_is_pinned(self):
        self.assertEqual(self.repository_manifest()["baseline"], self.GOLDEN_BASELINE)

    def test_valid_manifest_and_passing_test(self):
        with self.fixture("pass"):
            self.assertTrue(gate.run_tests(gate.load_tests(self.load()), io.StringIO()))

    def test_failure_error_and_skip_fail_gate(self):
        for outcome in ("fail", "error", "skip"):
            with self.subTest(outcome=outcome), self.fixture(outcome):
                self.assertFalse(
                    gate.run_tests(gate.load_tests(self.load()), io.StringIO())
                )

    def test_expected_failure_fails_gate(self):
        class ExpectedFailure(unittest.TestCase):
            @unittest.expectedFailure
            def test_regression(self):
                self.fail("Known regression must block golden clearance")

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ExpectedFailure)
        self.assertFalse(gate.run_tests(suite, io.StringIO()))

    def test_empty_suite_fails(self):
        self.assertFalse(gate.run_tests(unittest.TestSuite(), io.StringIO()))

    def test_missing_test_fails_validation(self):
        with self.fixture("pass"):
            self.manifest["behaviors"][0]["test_ids"] = [
                "test_golden_fixture.Example.test_missing"
            ]
            with self.assertRaises(gate.ContractError):
                gate.load_tests(self.load())

    def test_malformed_and_empty_manifests(self):
        originals = copy.deepcopy(self.manifest)
        variants = [
            None,
            {},
            dict(originals, schema_version=True),
            dict(originals, behaviors=[]),
            dict(originals, unexpected="field"),
        ]
        for value in variants:
            with self.subTest(value=value):
                self.manifest = value
                with self.assertRaises(gate.ContractError):
                    self.load()
        self.path.write_text("not json", encoding="utf-8")
        with self.assertRaises(gate.ContractError):
            gate.load_manifest(self.path, self.root)

    def test_duplicate_json_fields_rejected(self):
        self.path.write_text(
            '{"schema_version": 1, "schema_version": 1}', encoding="utf-8"
        )
        with self.assertRaises(gate.ContractError):
            gate.load_manifest(self.path, self.root)

    def test_unsafe_paths_and_missing_evidence(self):
        for value in (
            "../escape",
            "/absolute",
            "C:/absolute",
            "folder\\file",
            "a//b",
            "./file",
            "missing.md",
            "*.md",
            "a\nb",
            None,
        ):
            with self.subTest(value=value):
                self.manifest["baseline"]["evidence"] = value
                with self.assertRaises(gate.ContractError):
                    self.load()

    def test_invalid_contracts(self):
        original = copy.deepcopy(self.manifest["behaviors"][0])
        for key, value in (
            ("id", "Bad ID"),
            ("contract", ""),
            ("test_ids", []),
            ("test_ids", ["test_golden_fixture.Example"]),
            ("test_ids", ["os.system"]),
            (
                "test_ids",
                [
                    "tests.test_golden_behaviors.GoldenGateTests.test_repository_golden_contracts"
                ],
            ),
            ("source_paths", ["../*.py"]),
            ("source_paths", ["missing/*.py"]),
            ("hardware_cases", "none"),
        ):
            with self.subTest(key=key, value=value):
                self.manifest["behaviors"] = [dict(original, **{key: value})]
                with self.assertRaises(gate.ContractError):
                    self.load()
        self.manifest["behaviors"] = [original, original]
        with self.assertRaises(gate.ContractError):
            self.load()

    def test_shared_tests_run_once(self):
        second = copy.deepcopy(self.manifest["behaviors"][0])
        second["id"] = "another"
        self.manifest["behaviors"].append(second)
        with self.fixture("pass"):
            self.assertEqual(gate.load_tests(self.load()).countTestCases(), 1)

    def test_base_report_does_not_filter_suite(self):
        with (
            self.fixture("pass"),
            patch.object(gate, "load_manifest", return_value=self.manifest),
            patch.object(gate, "affected", return_value=[]),
            patch.object(gate, "run_tests", return_value=True) as run,
            patch("sys.stdout", new=io.StringIO()),
        ):
            self.assertEqual(gate.main(["--base", "HEAD"]), 0)
            self.assertEqual(run.call_args.args[0].countTestCases(), 1)

    def test_validate_only_resolves_tests_without_execution(self):
        with (
            self.fixture("fail"),
            patch.object(gate, "load_manifest", return_value=self.manifest),
            patch.object(gate, "run_tests") as run,
            patch("sys.stdout", new=io.StringIO()),
        ):
            self.assertEqual(gate.main(["--validate-only"]), 0)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
