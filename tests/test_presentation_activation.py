from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.application.presentation_activation import (  # noqa: E402
    PresentationActivationApprovalStore,
    PresentationActivationService,
)
from hdm.domain.serialization import snapshot_from_dict  # noqa: E402
from hdm.ports.presentation_activation import (  # noqa: E402
    GamescopeUserContext,
    GamescopeUserResolution,
    UserServiceOperation,
)
from hdm.ports.transition import VersionedObservation  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
