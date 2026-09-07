from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from hdm.application.safe_undock_evidence import (  # noqa: E402
    assess_removal_safety_report,
    build_safe_undock_evidence,
)
from hdm.domain.models import Confidence, GameState  # noqa: E402
from hdm.domain.peripheral_handoff import (  # noqa: E402
    AudioOutput,
    AudioPeripheralState,
    ControllerPeripheralState,
)
from hdm.domain.removal_safety import (  # noqa: E402
    REMOVAL_SAFETY_FACTS,
    RemovalSafetyState,
    assess_removal_safety,
)
from hdm.domain.safe_undock_readiness import (  # noqa: E402
    SafeUndockReadinessState,
    assess_safe_undock_readiness,
)

from test_safe_undock_evidence import (  # noqa: E402
    client,
    report,
    returned_to_portable,
)


UNOBSERVED_AUDIO = AudioPeripheralState(
    True,
    False,
    "audio.default_output_unobserved",
    AudioOutput.UNKNOWN,
    "current",
    False,
    "external-audio",
    True,
    False,
    "portable-audio",
    True,
    False,
    False,
)

UNMAPPED_CONTROLLER = ControllerPeripheralState(
    True, False, "controller.identity_unmapped", "", None, False, False, "", None, False
)


def as_shipped(**kwargs):
    """The real device state: audio and controller unverifiable (issue #93)."""
    kwargs.setdefault("audio", UNOBSERVED_AUDIO)
    kwargs.setdefault("controller", UNMAPPED_CONTROLLER)
    return returned_to_portable(**kwargs)


class ScopeTests(unittest.TestCase):
    def test_player_recoverability_facts_are_excluded(self) -> None:
        self.assertNotIn("portable_audio_active", REMOVAL_SAFETY_FACTS)
        self.assertNotIn("builtin_controller_active", REMOVAL_SAFETY_FACTS)

    def test_every_removal_fact_exists_on_the_evidence(self) -> None:
        evidence = build_safe_undock_evidence(returned_to_portable()).evidence
        assert evidence is not None
        for name in REMOVAL_SAFETY_FACTS:
            self.assertTrue(hasattr(evidence, name), name)

    def test_invariant_20_facts_are_all_covered(self) -> None:
        """Render, display, and client evidence are exactly what invariant 20 names."""
        for name in (
            "exact_attachment",
            "portable_render_gpu",
            "portable_display_active",
            "external_display_active",
            "client_scan_complete",
            "clients_clear",
        ):
            self.assertIn(name, REMOVAL_SAFETY_FACTS)


class RemovalSafetyTests(unittest.TestCase):
    def test_unobservable_audio_no_longer_blocks_removal(self) -> None:
        """The whole point of the split: #93's code gaps stop gating removal."""
        removal = assess_removal_safety_report(as_shipped())
        self.assertIs(
            removal.state, RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL
        )
        self.assertIsNotNone(removal.revalidation)

    def test_the_full_contract_still_blocks_on_the_same_state(self) -> None:
        """Nothing is relaxed: Safe Undock keeps its nine-fact requirement."""
        readiness = assess_safe_undock_readiness(
            build_safe_undock_evidence(as_shipped()).evidence,
            expected_attachment_binding="egpu-stable-id",
            expected_generation="peripheral-generation",
            expected_sample_id="peripheral-sample",
        )
        self.assertIs(readiness.state, SafeUndockReadinessState.NOT_READY)

    def test_remaining_holder_still_blocks_removal(self) -> None:
        removal = assess_removal_safety_report(as_shipped(clients=(client(),)))
        self.assertIs(removal.state, RemovalSafetyState.NOT_READY)
        self.assertEqual(removal.code, "removal_safety.clients_active_or_protected")

    def test_running_game_still_blocks_removal(self) -> None:
        removal = assess_removal_safety_report(
            as_shipped(game_state=GameState.RUNNING)
        )
        self.assertIs(removal.state, RemovalSafetyState.NOT_READY)
        self.assertEqual(removal.code, "removal_safety.game_running")

    def test_unknown_game_state_is_insufficient(self) -> None:
        removal = assess_removal_safety_report(
            as_shipped(game_state=GameState.UNKNOWN)
        )
        self.assertIs(removal.state, RemovalSafetyState.EVIDENCE_INSUFFICIENT)

    def test_active_external_display_still_blocks_removal(self) -> None:
        base = as_shipped()
        displays = tuple(
            dataclasses.replace(display, active=True, confidence=Confidence.OBSERVED)
            if display.kind.value == "external"
            else display
            for display in base.snapshot.displays
        )
        removal = assess_removal_safety_report(as_shipped(displays=displays))
        self.assertIs(removal.state, RemovalSafetyState.NOT_READY)
        self.assertEqual(removal.code, "removal_safety.external_display_still_active")

    def test_incomplete_client_scan_is_insufficient(self) -> None:
        removal = assess_removal_safety_report(as_shipped(scan_complete=False))
        self.assertIs(removal.state, RemovalSafetyState.EVIDENCE_INSUFFICIENT)
        self.assertEqual(removal.code, "removal_safety.client_scan_incomplete")

    def test_docked_on_the_tv_blocks_removal(self) -> None:
        removal = assess_removal_safety_report(
            report(audio=UNOBSERVED_AUDIO, controller=UNMAPPED_CONTROLLER)
        )
        self.assertIs(removal.state, RemovalSafetyState.NOT_READY)

    def test_missing_peripheral_is_insufficient(self) -> None:
        removal = assess_removal_safety_report(report(with_peripheral=False))
        self.assertIs(removal.state, RemovalSafetyState.EVIDENCE_INSUFFICIENT)

    def test_stale_evidence_is_invalidated(self) -> None:
        evidence = build_safe_undock_evidence(as_shipped()).evidence
        assert evidence is not None
        removal = assess_removal_safety(
            evidence,
            expected_attachment_binding="a-different-attachment",
            expected_generation=evidence.generation,
            expected_sample_id=evidence.sample_id,
        )
        self.assertIs(removal.state, RemovalSafetyState.INVALIDATED)
        self.assertEqual(removal.code, "safe_undock.attachment_changed")

    def test_ready_state_requires_revalidation_evidence(self) -> None:
        with self.assertRaises(ValueError):
            from hdm.domain.removal_safety import RemovalSafety

            RemovalSafety(
                RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL, "code", None
            )


if __name__ == "__main__":
    unittest.main()
