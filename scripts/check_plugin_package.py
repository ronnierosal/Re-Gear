"""Validate the Decky plugin layout and narrow 0.2 delivery contract."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


REQUIRED_FILES = (
    "LICENSE",
    "backend/hdm/api.py",
    "backend/hdm/adapters/steamos/sleep_inhibitor.py",
    "backend/hdm/adapters/steamos/peripherals.py",
    "backend/hdm/application/support_bundle.py",
    "backend/hdm/delivery/support_export.py",
    "backend/hdm/delivery/gamescope_wrapper.py",
    "backend/hdm/delivery/gamescope_integration.py",
    "backend/hdm/delivery/presentation_config.py",
    "backend/hdm/adapters/steamos/gamescope_user.py",
    "backend/hdm/adapters/presentation_transition.py",
    "backend/hdm/application/presentation_activation.py",
    "backend/hdm/application/supervised_transition.py",
    "backend/hdm/application/safe_disconnect_shutdown.py",
    "backend/hdm/application/shared_transition_journal.py",
    "backend/hdm/application/guarded_process_release.py",
    "backend/hdm/application/docked_igpu_lifecycle.py",
    "backend/hdm/application/docked_igpu_promotion.py",
    "backend/hdm/adapters/steamos/gamescope_session.py",
    "backend/hdm/adapters/steamos/process_signal.py",
    "backend/hdm/delivery/process_release.py",
    "backend/hdm/delivery/docked_igpu_lifecycle.py",
    "backend/hdm/delivery/docked_igpu_scheduler.py",
    "backend/hdm/delivery/diagnostic_logging.py",
    "backend/hdm/delivery/runtime_state.py",
    "backend/hdm/delivery/transition_journal_store.py",
    "backend/hdm/ports/presentation_activation.py",
    "backend/hdm/ports/system_power.py",
    "backend/hdm/ports/gamescope_session.py",
    "backend/hdm/domain/gamescope_session.py",
    "bin/gamescope",
    "dist/index.js",
    "dist/index.js.map",
    "main.py",
    "package.json",
    "plugin.json",
)
FORBIDDEN_RPC_TERMS = (
    "apply_transition",
    "restart_gamescope",
    "set_gpu",
    "switch_display",
    "signal_process",
    "force_close",
    "approve_docked_igpu",
    "execute_docked_igpu",
)


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    failures: list[str] = []
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            failures.append(f"missing {relative}")

    manifest_path = root / "plugin.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("flags") != ["root"]:
            failures.append("plugin.json must request only the root delivery flag")
        description = str(manifest.get("publish", {}).get("description", "")).lower()
        if "sleep safety" not in description:
            failures.append("plugin.json must describe the approved sleep-safety scope")

    main_path = root / "main.py"
    if main_path.is_file():
        tree = ast.parse(main_path.read_text(encoding="utf-8"), filename=str(main_path))
        plugin_classes = [
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Plugin"
        ]
        public_methods = {
            node.name
            for plugin in plugin_classes
            for node in plugin.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }
        allowed_methods = {
            "get_snapshot",
            "get_peripheral_status",
            "classify_offline_details",
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
        }
        if public_methods != allowed_methods:
            failures.append(
                "Decky RPCs must remain limited to diagnostics/logging, read-only offline report classification and peripheral/watcher/action-history status, automatic-dock preference/status, approved support export, supervised presentation, confirmed shutdown-before-disconnect, and guarded process release"
            )

    delivery_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (root / "main.py", root / "src" / "backend.ts")
        if path.is_file()
    ).lower()
    for term in FORBIDDEN_RPC_TERMS:
        if term in delivery_sources:
            failures.append(f"delivery layer contains forbidden mutation RPC term {term!r}")

    if failures:
        print("Plugin package check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(
        "Plugin package check passed: diagnostics/logging, read-only peripheral/watcher/action-history status, automatic-dock preference/status, support export, sleep guard, supervised presentation, confirmed shutdown-before-disconnect, and guarded process release only."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
