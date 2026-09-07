from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.application.safe_undock_evidence import (  # noqa: E402
    assess_report,
    build_safe_undock_evidence,
)
from hdm.application.snapshot import SnapshotReport  # noqa: E402
from hdm.domain.inference import infer_operating_mode  # noqa: E402
from hdm.domain.models import (  # noqa: E402
    Confidence,
    EgpuClientKind,
    EgpuClientObservation,
    EgpuLinkObservation,
    EgpuLinkState,
    EgpuResourceKind,
    GameState,
)
from hdm.domain.peripheral_handoff import (  # noqa: E402
    AudioOutput,
    AudioPeripheralState,
    ControllerPeripheralState,
    PeripheralObservation,
)
from hdm.domain.safe_undock_readiness import SafeUndockReadinessState  # noqa: E402
from hdm.domain.serialization import snapshot_from_dict  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"
EGPU_ID = "egpu-stable-id"


def peripheral(
    *,
    controller: ControllerPeripheralState | None = None,
    audio: AudioPeripheralState | None = None,
) -> PeripheralObservation:
    return PeripheralObservation(
        1,
        "peripheral-generation",
        "peripheral-sample",
        controller
        or ControllerPeripheralState(
            True, True, "", "builtin", True, True, True, "external", True, True
        ),
        audio
        or AudioPeripheralState(
            True,
            True,
            "",
            AudioOutput.INTERNAL,
            "current",
            True,
            "external-audio",
            True,
            True,
            "portable-audio",
            True,
            True,
            True,
        ),
    )


def client() -> EgpuClientObservation:
    return EgpuClientObservation(
        instance_id="instance",
        pid=4321,
        name="steam",
        kind=EgpuClientKind.PROTECTED,
        resources=(EgpuResourceKind.DRM_RENDER,),
        close_eligible=False,
        reason="protected client fixture",
        process_start_time="1000",
    )


def report(
    fixture: str = "tv-docked.json",
    *,
    clients: tuple[EgpuClientObservation, ...] = (),
    scan_complete: bool = True,
    applicable: bool = True,
    egpu_stable_id: str = EGPU_ID,
    link: EgpuLinkObservation | None = None,
    displays=None,
    gpus=None,
    game_state: GameState | None = None,
    with_peripheral: bool = True,
    controller: ControllerPeripheralState | None = None,
    audio: AudioPeripheralState | None = None,
) -> SnapshotReport:
    raw = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    snapshot = snapshot_from_dict(raw)
    snapshot = dataclasses.replace(
        snapshot,
        disconnect_readiness=dataclasses.replace(
            snapshot.disconnect_readiness,
            applicable=applicable,
            scan_complete=scan_complete,
            ready=not clients,
            egpu_stable_id=egpu_stable_id,
            clients=clients,
        ),
        egpu_link=link
        or EgpuLinkObservation(True, EgpuLinkState.UP, Confidence.VERIFIED),
    )
    if displays is not None:
        snapshot = dataclasses.replace(snapshot, displays=displays)
    if gpus is not None:
        snapshot = dataclasses.replace(snapshot, gpus=gpus)
    if game_state is not None:
        snapshot = dataclasses.replace(snapshot, game_state=game_state)
    return SnapshotReport(
        snapshot=snapshot,
        inference=infer_operating_mode(snapshot),
        peripheral=peripheral(controller=controller, audio=audio)
        if with_peripheral
        else None,
    )


def returned_to_portable(**kwargs) -> SnapshotReport:
    """The real target state: back on the Ally with the eGPU still attached."""
    base = json.loads((FIXTURES / "tv-docked.json").read_text(encoding="utf-8"))
    snapshot = snapshot_from_dict(base)
    displays = tuple(
        dataclasses.replace(display, active=display.kind.value == "internal")
        for display in snapshot.displays
    )
    gpus = tuple(
        dataclasses.replace(gpu, selected_for_render=gpu.role.value == "internal")
        for gpu in snapshot.gpus
    )
    kwargs.setdefault("displays", displays)
    kwargs.setdefault("gpus", gpus)
    return report(**kwargs)


class EvidenceCompositionTests(unittest.TestCase):
    def test_missing_peripheral_cannot_compose(self) -> None:
        result = build_safe_undock_evidence(report(with_peripheral=False))
        self.assertFalse(result.available)
        self.assertEqual(result.code, "safe_undock.peripheral_observation_missing")

    def test_missing_attachment_binding_cannot_compose(self) -> None:
        result = build_safe_undock_evidence(report(egpu_stable_id=""))
        self.assertFalse(result.available)
        self.assertEqual(result.code, "safe_undock.attachment_binding_missing")

    def test_every_fact_binds_to_one_observation_identity(self) -> None:
        evidence = build_safe_undock_evidence(returned_to_portable()).evidence
        assert evidence is not None
        self.assertEqual(evidence.generation, "peripheral-generation")
        self.assertEqual(evidence.sample_id, "peripheral-sample")
        for fact in evidence.facts:
            self.assertEqual(fact.generation, evidence.generation)
            self.assertEqual(fact.sample_id, evidence.sample_id)

    def test_attachment_binding_is_the_opaque_stable_id(self) -> None:
        evidence = build_safe_undock_evidence(returned_to_portable()).evidence
        assert evidence is not None
        self.assertEqual(evidence.attachment_binding, EGPU_ID)


class DisplayEvidenceTests(unittest.TestCase):
    def test_connected_but_inactive_external_display_is_not_active(self) -> None:
        """Safety invariant 6: connected is not proof of an active display."""
        evidence = build_safe_undock_evidence(returned_to_portable()).evidence
        assert evidence is not None
        external = evidence.external_display_active
        self.assertIs(external.value, False)
        self.assertTrue(external.verified)

    def test_active_external_display_is_reported_active(self) -> None:
        evidence = build_safe_undock_evidence(report()).evidence
        assert evidence is not None
        self.assertIs(evidence.external_display_active.value, True)

    def test_unverified_display_confidence_is_not_verified(self) -> None:
        base = returned_to_portable()
        displays = tuple(
            dataclasses.replace(display, confidence=Confidence.OBSERVED)
            for display in base.snapshot.displays
        )
        evidence = build_safe_undock_evidence(
            returned_to_portable(displays=displays)
        ).evidence
        assert evidence is not None
        self.assertFalse(evidence.portable_display_active.verified)


class ReadinessTests(unittest.TestCase):
    def test_returned_to_portable_is_ready_for_revalidation(self) -> None:
        readiness = assess_report(returned_to_portable())
        self.assertIs(
            readiness.state, SafeUndockReadinessState.READY_FOR_REVALIDATION
        )
        self.assertIsNotNone(readiness.revalidation)

    def test_still_on_the_tv_blocks_on_the_handheld_panel_first(self) -> None:
        """Docked on the TV, the handheld panel is inactive, which blocks first."""
        readiness = assess_report(report())
        self.assertIs(readiness.state, SafeUndockReadinessState.NOT_READY)
        self.assertEqual(readiness.code, "safe_undock.portable_display_unverified")

    def test_unverified_active_external_display_blocks(self) -> None:
        base = returned_to_portable()
        displays = tuple(
            dataclasses.replace(display, active=True, confidence=Confidence.OBSERVED)
            if display.kind.value == "external"
            else display
            for display in base.snapshot.displays
        )
        readiness = assess_report(returned_to_portable(displays=displays))
        self.assertIs(readiness.state, SafeUndockReadinessState.NOT_READY)
        self.assertEqual(readiness.code, "safe_undock.external_display_still_active")

    def test_remaining_client_blocks(self) -> None:
        readiness = assess_report(returned_to_portable(clients=(client(),)))
        self.assertIs(readiness.state, SafeUndockReadinessState.NOT_READY)
        self.assertEqual(readiness.code, "safe_undock.clients_active_or_protected")

    def test_running_game_blocks(self) -> None:
        readiness = assess_report(returned_to_portable(game_state=GameState.RUNNING))
        self.assertIs(readiness.state, SafeUndockReadinessState.NOT_READY)
        self.assertEqual(readiness.code, "safe_undock.game_running")

    def test_unknown_game_state_is_insufficient(self) -> None:
        readiness = assess_report(returned_to_portable(game_state=GameState.UNKNOWN))
        self.assertIs(readiness.state, SafeUndockReadinessState.EVIDENCE_INSUFFICIENT)
        self.assertEqual(readiness.code, "safe_undock.game_state_unknown")

    def test_incomplete_client_scan_is_insufficient(self) -> None:
        readiness = assess_report(returned_to_portable(scan_complete=False))
        self.assertIs(readiness.state, SafeUndockReadinessState.EVIDENCE_INSUFFICIENT)
        self.assertEqual(readiness.code, "safe_undock.client_scan_incomplete")

    def test_inapplicable_scan_is_insufficient(self) -> None:
        readiness = assess_report(returned_to_portable(applicable=False))
        self.assertIs(readiness.state, SafeUndockReadinessState.EVIDENCE_INSUFFICIENT)
        self.assertEqual(readiness.code, "safe_undock.client_scan_incomplete")

    def test_unknown_link_state_is_insufficient(self) -> None:
        readiness = assess_report(
            returned_to_portable(
                link=EgpuLinkObservation(
                    True, EgpuLinkState.UNKNOWN, Confidence.UNKNOWN
                )
            )
        )
        self.assertIs(readiness.state, SafeUndockReadinessState.EVIDENCE_INSUFFICIENT)
        self.assertEqual(readiness.code, "safe_undock.topology_unverified")

    def test_external_audio_blocks(self) -> None:
        readiness = assess_report(
            returned_to_portable(
                audio=AudioPeripheralState(
                    True,
                    True,
                    "",
                    AudioOutput.EXTERNAL,
                    "current",
                    True,
                    "external-audio",
                    True,
                    True,
                    "portable-audio",
                    True,
                    True,
                    True,
                )
            )
        )
        self.assertIs(readiness.state, SafeUndockReadinessState.NOT_READY)
        self.assertEqual(readiness.code, "safe_undock.portable_audio_unverified")

    def test_unavailable_builtin_controller_blocks(self) -> None:
        readiness = assess_report(
            returned_to_portable(
                controller=ControllerPeripheralState(
                    True, True, "", "builtin", False, False, True, "external", True, True
                )
            )
        )
        self.assertIs(readiness.state, SafeUndockReadinessState.NOT_READY)
        self.assertEqual(
            readiness.code, "safe_undock.builtin_controller_unverified"
        )

    def test_missing_peripheral_assesses_as_insufficient(self) -> None:
        readiness = assess_report(report(with_peripheral=False))
        self.assertIs(readiness.state, SafeUndockReadinessState.EVIDENCE_INSUFFICIENT)
        self.assertEqual(
            readiness.code, "safe_undock.peripheral_observation_missing"
        )

    def test_both_displays_active_is_contradictory(self) -> None:
        base = returned_to_portable()
        displays = tuple(
            dataclasses.replace(display, active=True)
            for display in base.snapshot.displays
        )
        readiness = assess_report(returned_to_portable(displays=displays))
        self.assertIs(readiness.state, SafeUndockReadinessState.EVIDENCE_INSUFFICIENT)
        self.assertEqual(readiness.code, "safe_undock.display_contradictory")

    def test_readiness_is_never_a_removal_claim(self) -> None:
        """`ready_for_revalidation` returns opaque evidence, not clearance."""
        readiness = assess_report(returned_to_portable())
        assert readiness.revalidation is not None
        self.assertEqual(readiness.revalidation.attachment_binding, EGPU_ID)
        self.assertEqual(readiness.code, "safe_undock.ready_for_revalidation")


if __name__ == "__main__":
    unittest.main()
