from __future__ import annotations

import ast
import json
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from scripts.build_plugin import (  # noqa: E402
    BUILD_INFO_FILENAME,
    OUTPUT,
    PLUGIN_DIRECTORY,
    archive_mode,
    archive_name,
    included_files,
)


class DeckyContractTests(unittest.TestCase):
    def test_manifest_requests_root_for_observation_and_sleep_guard(self):
        manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["flags"], ["root"])
        self.assertEqual(manifest["api_version"], 1)
        self.assertIn("sleep safety", manifest["publish"]["description"].lower())

    def test_backend_exposes_only_diagnostics_support_and_preparation_rpcs(self):
        path = ROOT / "main.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        plugin = next(
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Plugin"
        )
        public_methods = {
            node.name
            for node in plugin.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }
        self.assertEqual(
            public_methods,
            {
                "get_snapshot",
                "get_peripheral_status",
                "get_action_history",
                "get_automatic_dock_status",
                "set_automatic_dock_enabled",
                "get_docked_igpu_status",
                "acknowledge_docked_igpu_status",
                "get_diagnostic_logging_status",
                "enable_diagnostic_logging",
                "disable_diagnostic_logging",
                "preview_support_bundle",
                "save_support_bundle",
                "preview_presentation_preparation",
                "approve_presentation_preparation",
                "prepare_presentation_integration",
                "preview_supervised_tv_switch",
                "approve_supervised_tv_switch",
                "execute_supervised_tv_switch",
                "approve_supervised_portable_switch",
                "execute_supervised_portable_switch",
                "approve_safe_disconnect_shutdown",
                "execute_safe_disconnect_shutdown",
                "acknowledge_supervised_tv_switch",
                "get_supervised_tv_switch_status",
                "get_transition_journal_status",
                "acknowledge_sleep_journal",
                "get_process_release_status",
                "preview_process_release",
                "approve_process_release",
                "execute_process_release",
                "acknowledge_process_release",
            },
        )
        source = path.read_text(encoding="utf-8")
        self.assertIn("PosixProcessSignalAdapter", source)
        self.assertIn("ProcessReleaseApprovalStore", source)
        self.assertIn("GuardedProcessReleaseService", source)
        self.assertIn("ProcessReleaseRunner", source)
        self.assertIn("RootOwnedRuntimeState", source)
        self.assertIn("PresentationTransitionMechanism", source)
        self.assertIn("audio=self._audio_handoff_service()", source)
        self.assertIn("PipeWireCommandRunner", source)
        self.assertIn("PortableAudioStateStore", source)
        self.assertIn("SafeDisconnectShutdownService", source)
        self.assertIn("SystemPowerCommandRunner", source)
        self.assertIn("SupervisedPresentationTransitionService", source)
        self.assertIn("TransitionOrchestrator", source)
        self.assertIn("config=PresentationConfigStore(presentation_state_root)", source)
        self.assertNotIn("config=PresentationConfigStore(journal_root)", source)
        promotion_source = (
            ROOT / "backend" / "hdm" / "application" / "docked_igpu_promotion.py"
        ).read_text(encoding="utf-8")
        promotion_tree = ast.parse(promotion_source)
        self.assertFalse(
            any(
                isinstance(node, ast.ImportFrom)
                and node.level == 1
                and node.module == "supervised_transition"
                for node in promotion_tree.body
            ),
            "watch-only production import must not load supervised transition code",
        )
        self.assertTrue(
            any(
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and node.test.id == "TYPE_CHECKING"
                for node in promotion_tree.body
            )
        )

    def test_no_argument_rpcs_accept_deckys_request_placeholder(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        plugin = next(
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Plugin"
        )
        no_argument_rpcs = {
            "get_snapshot",
            "get_peripheral_status",
            "get_action_history",
            "get_automatic_dock_status",
            "get_diagnostic_logging_status",
            "disable_diagnostic_logging",
            "get_docked_igpu_status",
            "acknowledge_docked_igpu_status",
            "preview_support_bundle",
            "preview_presentation_preparation",
            "approve_presentation_preparation",
            "preview_supervised_tv_switch",
            "approve_supervised_tv_switch",
            "approve_supervised_portable_switch",
            "approve_safe_disconnect_shutdown",
            "get_supervised_tv_switch_status",
            "get_transition_journal_status",
            "get_process_release_status",
        }
        methods = {
            node.name: node
            for node in plugin.body
            if isinstance(node, ast.AsyncFunctionDef)
        }
        for name in no_argument_rpcs:
            with self.subTest(name=name):
                arguments = methods[name].args
                self.assertEqual([item.arg for item in arguments.args], ["self", "_request"])
                self.assertEqual(len(arguments.defaults), 1)

    def test_frontend_has_explicit_supervised_transition_rpcs(self):
        source = (ROOT / "src" / "backend.ts").read_text(encoding="utf-8")
        self.assertIn('callable<[], SnapshotPayload>("get_snapshot")', source)
        self.assertIn('"get_docked_igpu_status"', source)
        self.assertIn('"acknowledge_docked_igpu_status"', source)
        self.assertIn('"get_diagnostic_logging_status"', source)
        self.assertIn('"get_action_history"', source)
        self.assertIn('"get_automatic_dock_status"', source)
        self.assertIn('"set_automatic_dock_enabled"', source)
        self.assertIn('"enable_diagnostic_logging"', source)
        self.assertIn('"disable_diagnostic_logging"', source)
        self.assertIn('"preview_support_bundle"', source)
        self.assertIn('"preview_presentation_preparation"', source)
        self.assertIn('"approve_presentation_preparation"', source)
        self.assertIn('"prepare_presentation_integration"', source)
        self.assertIn('"preview_supervised_tv_switch"', source)
        self.assertIn('"approve_supervised_tv_switch"', source)
        self.assertIn('"execute_supervised_tv_switch"', source)
        self.assertIn('"approve_supervised_portable_switch"', source)
        self.assertIn('"execute_supervised_portable_switch"', source)
        self.assertIn('"approve_safe_disconnect_shutdown"', source)
        self.assertIn('"execute_safe_disconnect_shutdown"', source)
        self.assertIn('"acknowledge_supervised_tv_switch"', source)
        self.assertIn('"get_supervised_tv_switch_status"', source)
        self.assertIn('"get_transition_journal_status"', source)
        self.assertIn('"acknowledge_sleep_journal"', source)
        ui_source = (ROOT / "src" / "index.tsx").read_text(encoding="utf-8")
        self.assertIn("showPresentationPreparationBlocked", ui_source)
        self.assertIn('title: "Display validation is not ready"', ui_source)
        self.assertIn("Re-Gear will not replace it.", ui_source)
        self.assertIn('"get_process_release_status"', source)
        self.assertIn('"preview_process_release"', source)
        self.assertIn('"approve_process_release"', source)
        self.assertIn('"execute_process_release"', source)
        self.assertIn('"acknowledge_process_release"', source)
        self.assertIn('"save_support_bundle"', source)
        for forbidden in (
            "apply_transition",
            "switch_display",
            "signal_process",
            "force_close",
            "graceful_evidence",
        ):
            self.assertNotIn(forbidden, source.lower())

    def test_support_bundle_save_requires_a_preview_token_and_no_path(self):
        source = (ROOT / "src" / "backend.ts").read_text(encoding="utf-8")
        self.assertIn("callable<[string], SupportBundleSavePayload>", source)
        self.assertNotIn("saveSupportBundle = callable<[string, string]", source)

    def test_verbose_logging_ui_has_only_bounded_confirmed_choices(self):
        source = (ROOT / "src" / "index.tsx").read_text(encoding="utf-8")
        backend = (ROOT / "src" / "backend.ts").read_text(encoding="utf-8")

        self.assertIn('strTitle="Enable verbose Re-Gear diagnostics?"', source)
        self.assertIn('strOKButtonText="Enable"', source)
        self.assertIn("Logs stay on this handheld unless you separately preview", source)
        for duration in ("30_minutes", "1_hour", "2_hours", "until_reboot"):
            self.assertIn(f'"{duration}"', source)
            self.assertIn(f'"{duration}"', backend)
        self.assertNotIn('"forever"', source)
        self.assertNotIn('"forever"', backend)

    def test_attempted_sleep_warning_requires_acknowledgement(self):
        source = (ROOT / "src" / "index.tsx").read_text(encoding="utf-8")
        start = source.index("function showBlockedAttempt(")
        end = source.index("export default definePlugin", start)
        warning = source[start:end]
        self.assertIn("<ConfirmModal", warning)
        self.assertIn('strOKButtonText="OK"', warning)
        self.assertIn("bAlertDialog={true}", warning)
        self.assertIn("bDisableBackgroundDismiss={true}", warning)
        self.assertIn("bHideCloseIcon={true}", warning)
        self.assertIn("BLOCKED_ATTEMPT_MODAL_DELAY_MS", source)
        self.assertIn("window.setTimeout", source)
        self.assertIn("window.clearTimeout", source)
        self.assertIn("bNeverPopOut: true", warning)
        self.assertIn("    window,\n    { strTitle", warning)
        self.assertNotIn("    undefined,\n    { strTitle", warning)

    def test_decky_archive_has_one_top_level_plugin_directory(self):
        self.assertEqual(
            archive_name(ROOT / "plugin.json"),
            f"{PLUGIN_DIRECTORY}/plugin.json",
        )
        if OUTPUT.is_file():
            with zipfile.ZipFile(OUTPUT) as archive:
                top_levels = {name.split("/", 1)[0] for name in archive.namelist()}
                self.assertEqual(top_levels, {PLUGIN_DIRECTORY})
                self.assertIn(f"{PLUGIN_DIRECTORY}/plugin.json", archive.namelist())
                self.assertIn(
                    f"{PLUGIN_DIRECTORY}/{BUILD_INFO_FILENAME}", archive.namelist()
                )

    def test_gamescope_shim_is_packaged_as_executable(self):
        wrapper = ROOT / "bin" / "gamescope"
        self.assertIn(wrapper, included_files())
        self.assertEqual(archive_mode(wrapper) & 0o777, 0o755)

    def test_ci_exposes_only_a_bounded_validation_artifact(self):
        source = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("actions/upload-artifact@v4", source)
        self.assertIn("retention-days: 14", source)
        self.assertIn("out/source-revision.txt", source)
        self.assertIn("out/SHA256SUMS.txt", source)
        self.assertIn("scripts/verify_validation_artifact.py", source)
        self.assertNotIn("action-gh-release", source)
        self.assertNotIn("gh release", source.lower())


if __name__ == "__main__":
    unittest.main()
