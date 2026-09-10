from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.presentation_activation import (  # noqa: E402
    PresentationActivationApprovalStore,
    PresentationActivationService,
)
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.ports.presentation_activation import (  # noqa: E402
    GamescopeUserContext,
    GamescopeUserResolution,
    UserServiceOperation,
)
from regear.ports.transition import VersionedObservation  # noqa: E402
from regear.delivery.gamescope_integration import GamescopeIntegrationStore  # noqa: E402
from regear.delivery.user_directory import UserDirectory  # noqa: E402


USER = GamescopeUserContext(
    "deck",
    1000,
    1000,
    Path("/home/deck"),
    Path("/run/user/1000"),
    Path("/run/user/1000/bus"),
)
FINGERPRINT = hashlib.sha256(b"integration").hexdigest()


def portable():
    value = json.loads(
        (ROOT / "tests" / "fixtures" / "portable.json").read_text(encoding="utf-8")
    )
    return snapshot_from_dict(value)


def attached():
    value = json.loads(
        (ROOT / "tests" / "fixtures" / "connected-internal.json").read_text(
            encoding="utf-8"
        )
    )
    return snapshot_from_dict(value)


class Observations:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self):
        return self.values.pop(0) if self.values else None


class FakeIntegration:
    def __init__(
        self,
        events,
        *,
        ready=False,
        error="",
        activate_ok=True,
        fingerprint_after_activate=FINGERPRINT,
    ):
        self.events = events
        self.user = USER
        self.ready = ready
        self.error = error
        self.activate_ok = activate_ok
        self.fingerprint_after_activate = fingerprint_after_activate
        self.installed = ready

    def status(self):
        self.events.append("integration.status")
        return SimpleNamespace(
            ready=self.ready,
            shim_ready=True,
            error_code=self.error,
        )

    def activation_fingerprint(self):
        self.events.append("integration.fingerprint")
        return self.fingerprint_after_activate if self.installed else FINGERPRINT

    def preparation_fingerprint(self):
        return FINGERPRINT

    def rollback_activation(self):
        return self.deactivate()

    def activate(self):
        self.events.append("integration.activate")
        changed = not self.installed
        self.installed = self.activate_ok
        self.ready = self.activate_ok
        return SimpleNamespace(ok=self.activate_ok, changed=changed)

    def deactivate(self):
        self.events.append("integration.deactivate")
        changed = self.installed
        self.installed = False
        self.ready = False
        return SimpleNamespace(ok=False, changed=changed)


class ScriptedCommands:
    def __init__(self, events, outcomes=()):
        self.events = events
        self.outcomes = list(outcomes)

    def run(self, operation, **identity):
        self.events.append(f"command.{operation.value}")
        ok = self.outcomes.pop(0) if self.outcomes else True
        return SimpleNamespace(ok=ok)


def approval_store():
    return PresentationActivationApprovalStore(
        ttl_seconds=30,
        monotonic=lambda: 10,
        token_factory=lambda: "presentation_token_0001",
    )


def service(observations, integration, commands):
    return PresentationActivationService(
        observations=observations,
        integration=integration,
        commands=commands,
        resolve_user=lambda: GamescopeUserResolution(USER),
        approvals=approval_store(),
    )


class PresentationActivationServiceTests(unittest.TestCase):
    def test_preview_requires_consent_and_reports_conflicts_without_token(self):
        events = []
        integration = FakeIntegration(events)
        inspection = service(
            Observations(VersionedObservation("generation-1", portable())),
            integration,
            ScriptedCommands(events),
        ).preview(user_confirmed=False)
        self.assertFalse(inspection.approved)
        self.assertFalse(inspection.blockers)

        events = []
        integration = FakeIntegration(events, error="path_override_conflict")
        preview = service(
            Observations(VersionedObservation("generation-1", portable())),
            integration,
            ScriptedCommands(events),
        ).preview(user_confirmed=True)
        self.assertFalse(preview.approved)
        self.assertIn("integration.path_override_conflict", preview.blockers)

    def test_preparation_requires_the_egpu_to_be_disconnected(self):
        events = []
        preview = service(
            Observations(VersionedObservation("generation-1", attached())),
            FakeIntegration(events),
            ScriptedCommands(events),
        ).preview(user_confirmed=True)
        self.assertIn("egpu.disconnected_required", preview.blockers)
        self.assertFalse(preview.token)

    def test_exact_preview_token_prepares_without_restarting_gamescope(self):
        events = []
        integration = FakeIntegration(events)
        commands = ScriptedCommands(events)
        value = service(
            Observations(
                VersionedObservation("generation-1", portable()),
                VersionedObservation("generation-1", portable()),
            ),
            integration,
            commands,
        )
        preview = value.preview(user_confirmed=True)
        self.assertTrue(preview.approved)
        outcome = value.execute(preview.token)
        self.assertTrue(outcome.prepared)
        self.assertTrue(outcome.changed)
        self.assertEqual(outcome.code, "activation.prepared")
        self.assertEqual(
            events[-4:],
            [
                "integration.activate",
                "integration.fingerprint",
                "command.daemon_reload",
                "command.verify_gamescope_unit",
            ],
        )
        self.assertNotIn("command.restart_gamescope_session", events)

    def test_semantic_change_consumes_token_without_mutation(self):
        events = []
        integration = FakeIntegration(events)
        value = service(
            Observations(
                VersionedObservation("generation-1", portable()),
                VersionedObservation("generation-2", portable()),
            ),
            integration,
            ScriptedCommands(events),
        )
        token = value.preview(user_confirmed=True).token
        outcome = value.execute(token)
        self.assertEqual(outcome.code, "activation.evidence_changed")
        self.assertNotIn("integration.activate", events)
        self.assertEqual(
            value.execute(token).code,
            "activation.approval_invalid",
        )

    def test_post_install_fingerprint_change_removes_unloaded_dropin(self):
        events = []
        integration = FakeIntegration(
            events,
            fingerprint_after_activate=hashlib.sha256(b"changed").hexdigest(),
        )
        value = service(
            Observations(
                VersionedObservation("generation-1", portable()),
                VersionedObservation("generation-1", portable()),
            ),
            integration,
            ScriptedCommands(events),
        )
        outcome = value.execute(value.preview(user_confirmed=True).token)
        self.assertEqual(outcome.code, "activation.evidence_changed")
        self.assertTrue(outcome.rollback_succeeded)
        self.assertIn("integration.deactivate", events)
        self.assertNotIn("command.daemon_reload", events)

    def test_reload_failure_removes_new_dropin_and_reloads_again(self):
        events = []
        integration = FakeIntegration(events)
        commands = ScriptedCommands(events, outcomes=(False, True))
        value = service(
            Observations(
                VersionedObservation("generation-1", portable()),
                VersionedObservation("generation-1", portable()),
            ),
            integration,
            commands,
        )
        outcome = value.execute(value.preview(user_confirmed=True).token)
        self.assertEqual(outcome.code, "activation.daemon_reload_failed")
        self.assertTrue(outcome.rollback_attempted)
        self.assertTrue(outcome.rollback_succeeded)
        self.assertEqual(events.count("command.daemon_reload"), 2)
        self.assertIn("integration.deactivate", events)

    def test_failed_rollback_is_action_required(self):
        events = []
        integration = FakeIntegration(events)
        commands = ScriptedCommands(events, outcomes=(False, False))
        value = service(
            Observations(
                VersionedObservation("generation-1", portable()),
                VersionedObservation("generation-1", portable()),
            ),
            integration,
            commands,
        )
        outcome = value.execute(value.preview(user_confirmed=True).token)
        self.assertEqual(outcome.code, "activation.rollback_failed")
        self.assertFalse(outcome.rollback_succeeded)

    def test_effective_unit_mismatch_rolls_back_new_dropin(self):
        events = []
        value = service(
            Observations(VersionedObservation('generation-1', portable()),
                         VersionedObservation('generation-1', portable())),
            FakeIntegration(events), ScriptedCommands(events))
        value._verify_prepared = lambda: False
        outcome = value.execute(value.preview(user_confirmed=True).token)
        self.assertEqual(outcome.code, 'activation.unit_mismatch')
        self.assertTrue(outcome.rollback_succeeded)
        self.assertNotIn('command.restart_gamescope_session', events)


class PresentationActivationMigrationTests(unittest.TestCase):
    """Exercise the actual store behind approval, execution and rollback."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        home = root / "home"
        home.mkdir()
        uid = getattr(os, "getuid", lambda: 1000)()
        gid = getattr(os, "getgid", lambda: 1000)()
        self.user = GamescopeUserContext("deck", uid, gid, home,
                                        Path("/run/user/1000"), Path("/run/user/1000/bus"))
        plugin = root / "Re-Gear"
        shim = plugin / "bin" / "gamescope"
        shim.parent.mkdir(parents=True)
        shim.write_text("#!/usr/bin/python3\n# Handheld Dock Mode Gamescope argument shim\n",
                        encoding="utf-8", newline="\n")
        shim.chmod(0o755)
        self.store = GamescopeIntegrationStore(plugin_root=plugin, user=self.user,
                                              effective_uid=lambda: 0)
        self.store.target.parent.mkdir(parents=True)
        self.legacy = self.store.expected_text().replace(
            (plugin / "bin").as_posix(), (root / "HandheldDockMode" / "bin").as_posix()
        ).encode("utf-8")
        self.store.target.write_bytes(self.legacy)
        self.events = []

    def service(self, outcomes=(), verify=None, approvals=None):
        return PresentationActivationService(
            observations=Observations(*(VersionedObservation("same", portable()) for _ in range(12))),
            integration=self.store, commands=ScriptedCommands(self.events, outcomes),
            resolve_user=lambda: GamescopeUserResolution(self.user),
            approvals=approvals or approval_store(), verify_prepared=verify,
        )

    def test_old_install_reaches_approval_execution_and_idempotent_retry(self):
        value = self.service()
        preview = value.preview(user_confirmed=True)
        self.assertTrue(preview.approved, preview.blockers)
        self.assertFalse(preview.already_ready)
        result = value.execute(preview.token)
        self.assertTrue(result.prepared, result)
        self.assertEqual(self.store.target.read_bytes(), self.store.expected_text().encode())
        self.assertEqual(value.execute(preview.token).code, "activation.approval_invalid")
        retry = value.execute(value.preview(user_confirmed=True).token)
        self.assertTrue(retry.prepared)
        self.assertFalse(retry.changed)
        self.assertNotIn("command.restart_gamescope_session", self.events)

    def test_stale_token_refuses_even_a_known_rendering_change(self):
        value = self.service()
        token = value.preview(user_confirmed=True).token
        current = self.store.expected_text().encode()
        self.store.target.write_bytes(current)
        result = value.execute(token)
        self.assertEqual(result.code, "activation.evidence_changed")
        self.assertEqual(self.store.target.read_bytes(), current)
        self.assertEqual(self.events, [])

    def test_expired_migration_approval_preserves_old_install(self):
        clock = [0]
        approvals = PresentationActivationApprovalStore(
            ttl_seconds=30, monotonic=lambda: clock[0],
            token_factory=lambda: "presentation_token_0001")
        value = self.service(approvals=approvals)
        token = value.preview(user_confirmed=True).token
        clock[0] = 31
        self.assertEqual(value.execute(token).code, "activation.approval_invalid")
        self.assertEqual(self.store.target.read_bytes(), self.legacy)

    def test_reload_and_verification_failures_restore_old_rendering_and_can_retry(self):
        for outcomes, verify, expected in (
            ((False, True), None, "activation.daemon_reload_failed"),
            ((True, False, True), None, "activation.unit_unavailable"),
            ((True, True, True), lambda: False, "activation.unit_mismatch"),
        ):
            with self.subTest(expected=expected):
                self.store.target.write_bytes(self.legacy)
                value = self.service(outcomes, verify)
                result = value.execute(value.preview(user_confirmed=True).token)
                self.assertEqual(result.code, expected)
                self.assertTrue(result.rollback_succeeded)
                self.assertEqual(self.store.target.read_bytes(), self.legacy)
                retry = self.service()
                self.assertTrue(retry.execute(retry.preview(user_confirmed=True).token).prepared)

    def test_player_edit_or_unsafe_prior_never_gets_approval(self):
        self.store.target.write_bytes(self.legacy + b"# player edit\n")
        self.assertFalse(self.service().preview(user_confirmed=True).approved)
        self.store.target.write_bytes(self.legacy)
        with patch.object(self.store, "_managed_file_safe", return_value=False):
            self.assertFalse(self.service().preview(user_confirmed=True).approved)
        self.assertEqual(self.store.target.read_bytes(), self.legacy)

    def test_superseded_dropin_cannot_hide_competing_path_override(self):
        (self.store.target.parent / "50-player.conf").write_text(
            '[Service]\nEnvironment="PATH=/other/bin"\n', encoding="utf-8")
        result = self.service().preview(user_confirmed=True)
        self.assertIn("integration.path_override_conflict", result.blockers)
        self.assertFalse(result.approved)
        self.assertFalse(self.store.activate().changed)
        self.assertEqual(self.store.target.read_bytes(), self.legacy)

    def test_edit_after_activation_is_not_overwritten_by_rollback(self):
        edited = b"# edited while verifying\n"
        def verify():
            self.store.target.write_bytes(edited)
            return False
        value = self.service(verify=verify)
        result = value.execute(value.preview(user_confirmed=True).token)
        self.assertEqual(result.code, "activation.rollback_failed")
        self.assertFalse(result.rollback_succeeded)
        self.assertEqual(self.store.target.read_bytes(), edited)

    def test_persistent_publication_failure_reports_mutation_and_preserves_recovery(self):
        value = self.service()
        token = value.preview(user_confirmed=True).token
        with patch.object(UserDirectory, "publish", side_effect=OSError("persistent failure")):
            result = value.execute(token)
        self.assertEqual(result.code, "activation.rollback_failed")
        self.assertTrue(result.changed)
        self.assertTrue(result.rollback_attempted)
        self.assertFalse(result.rollback_succeeded)
        self.assertFalse(self.store.target.exists())
        self.assertEqual(self.store._activation_rollback[0], self.legacy)
        # A fresh activation cannot overwrite the retained prior with 'absent'.
        self.assertEqual(self.store.activate().status.error_code, "activation_recovery_required")
        self.assertTrue(self.store.rollback_activation().changed)
        self.assertEqual(self.store.target.read_bytes(), self.legacy)
        retry = self.service()
        self.assertTrue(retry.execute(retry.preview(user_confirmed=True).token).prepared)

    def test_unlink_then_fsync_failure_restores_exact_prior_and_reports_mutation(self):
        value = self.service()
        token = value.preview(user_confirmed=True).token
        remove = UserDirectory.remove_matching
        def remove_then_fail(directory, name, expected, limit):
            remove(directory, name, expected, limit)
            raise OSError("directory fsync failed after unlink")
        with patch.object(UserDirectory, "remove_matching", remove_then_fail):
            result = value.execute(token)
        self.assertEqual(result.code, "activation.install_failed")
        self.assertTrue(result.changed)
        self.assertTrue(result.rollback_attempted)
        self.assertTrue(result.rollback_succeeded)
        self.assertEqual(self.store.target.read_bytes(), self.legacy)
        self.assertIn("command.daemon_reload", self.events)

    def test_failed_upgrade_recovery_refuses_a_concurrent_edit(self):
        value = self.service()
        token = value.preview(user_confirmed=True).token
        with patch.object(UserDirectory, "publish", side_effect=OSError("persistent failure")):
            value.execute(token)
        edited = b"# player recovery\n"
        self.store.target.write_bytes(edited)
        self.assertFalse(self.store.rollback_activation().changed)
        self.assertEqual(self.store.target.read_bytes(), edited)


if __name__ == "__main__":
    unittest.main()
