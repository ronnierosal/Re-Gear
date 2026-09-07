"""Compose Safe Undock evidence from one fresh read-only snapshot report.

`hdm.domain.safe_undock_readiness` already classifies a Safe Undock observation,
but nothing produced a `SafeUndockEvidence` from real hardware, so the contract
could only ever be exercised by its own unit tests. This module is the missing
producer: it maps one already-collected `SnapshotReport` onto that contract.

Composition only. There is no I/O, no device or process action, and no physical
removal claim here; the result stays exactly as conservative as the domain
assessor it feeds. Every fact is deliberately reported unverified unless its
underlying observation is both complete and `Confidence.VERIFIED`, so a missing
or merely-observed signal fails closed rather than reading as clearance.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.models import (
    Confidence,
    DisplayKind,
    EgpuLinkState,
    GpuRole,
    ObservedSnapshot,
    SupportTier,
)
from ..domain.peripheral_handoff import AudioOutput, PeripheralObservation
from ..domain.safe_undock_readiness import (
    SafeUndockEvidence,
    SafeUndockFact,
    SafeUndockReadiness,
    SafeUndockReadinessState,
    assess_safe_undock_readiness,
)
from .snapshot import SnapshotReport


#: Audio outputs that keep sound on the handheld rather than the external GPU.
PORTABLE_AUDIO_OUTPUTS = frozenset({AudioOutput.INTERNAL, AudioOutput.OTHER_PORTABLE})

_CONFIDENCE_RANK = {
    Confidence.UNKNOWN: 0,
    Confidence.OBSERVED: 1,
    Confidence.VERIFIED: 2,
}


@dataclass(frozen=True, slots=True)
class SafeUndockEvidenceResult:
    """Either composed evidence, or the reason it could not be composed."""

    evidence: SafeUndockEvidence | None
    code: str

    @property
    def available(self) -> bool:
        return self.evidence is not None


def _confidence_rank(confidence: Confidence) -> int:
    return _CONFIDENCE_RANK[confidence]


def _fact(
    value: bool | None,
    confidence: Confidence,
    *,
    generation: str,
    sample_id: str,
) -> SafeUndockFact:
    """Build one fact, treating anything short of VERIFIED as unverified."""
    verified = confidence is Confidence.VERIFIED and value is not None
    return SafeUndockFact(value, verified, generation, sample_id)


def _subsystem_confidence(complete: bool, exact: bool) -> Confidence:
    """Map a peripheral subsystem's complete/exact pair onto Confidence."""
    if complete and exact:
        return Confidence.VERIFIED
    if complete:
        return Confidence.OBSERVED
    return Confidence.UNKNOWN


def _external_gpu_present(snapshot: ObservedSnapshot) -> tuple[bool | None, Confidence]:
    external = tuple(gpu for gpu in snapshot.gpus if gpu.role is GpuRole.EXTERNAL)
    if not external:
        return False, Confidence.UNKNOWN
    gpu = external[0]
    exact = gpu.present and snapshot.support_tier is SupportTier.CERTIFIED
    return exact, gpu.confidence


def _internal_render_selected(
    snapshot: ObservedSnapshot,
) -> tuple[bool | None, Confidence]:
    internal = tuple(gpu for gpu in snapshot.gpus if gpu.role is GpuRole.INTERNAL)
    if not internal:
        return None, Confidence.UNKNOWN
    gpu = internal[0]
    return gpu.selected_for_render, gpu.confidence


def _display_active(
    snapshot: ObservedSnapshot, kind: DisplayKind
) -> tuple[bool | None, Confidence]:
    """Report whether any display of `kind` is active, not merely connected.

    Safety invariant 6: a connected connector is not proof of an active display,
    so this reads `active` and never falls back to `connected`. A mixed set with
    no active member is unknown rather than inactive.
    """
    matching = tuple(display for display in snapshot.displays if display.kind is kind)
    if not matching:
        return False, Confidence.UNKNOWN
    active = tuple(display for display in matching if display.active is True)
    if active:
        return True, min((item.confidence for item in active), key=_confidence_rank)
    if all(display.active is False for display in matching):
        return False, min(
            (item.confidence for item in matching), key=_confidence_rank
        )
    return None, Confidence.UNKNOWN


def build_safe_undock_evidence(report: SnapshotReport) -> SafeUndockEvidenceResult:
    """Map one snapshot report onto the Safe Undock evidence contract."""
    peripheral: PeripheralObservation | None = report.peripheral
    if peripheral is None:
        return SafeUndockEvidenceResult(
            None, "safe_undock.peripheral_observation_missing"
        )
    snapshot = report.snapshot
    readiness = snapshot.disconnect_readiness
    attachment_binding = readiness.egpu_stable_id
    if not attachment_binding:
        return SafeUndockEvidenceResult(None, "safe_undock.attachment_binding_missing")

    # The peripheral observation is the only subsystem carrying an observation
    # identity, so it defines the generation and sample every fact binds to.
    generation = peripheral.generation
    sample_id = peripheral.sample_id

    def fact(value: bool | None, confidence: Confidence) -> SafeUndockFact:
        return _fact(value, confidence, generation=generation, sample_id=sample_id)

    attachment_value, attachment_confidence = _external_gpu_present(snapshot)
    render_value, render_confidence = _internal_render_selected(snapshot)
    portable_display, portable_display_confidence = _display_active(
        snapshot, DisplayKind.INTERNAL
    )
    external_display, external_display_confidence = _display_active(
        snapshot, DisplayKind.EXTERNAL
    )

    link = snapshot.egpu_link
    topology_value = link.state is EgpuLinkState.UP if link.applicable else None

    # Every observed client holds one of the exact eGPU nodes, so a clear scan
    # is an empty one. `scan_complete` stays a separate fact so the domain can
    # tell "nothing holds it" apart from "we could not finish looking".
    clients_clear = len(readiness.clients) == 0
    scan_confidence = (
        Confidence.VERIFIED if readiness.applicable else Confidence.UNKNOWN
    )

    audio = peripheral.audio
    audio_confidence = _subsystem_confidence(audio.complete, audio.exact)
    audio_value = (
        audio.current_output in PORTABLE_AUDIO_OUTPUTS
        and audio.current_output_usable_verified
    )

    controller = peripheral.controller
    controller_confidence = _subsystem_confidence(controller.complete, controller.exact)
    controller_value = (
        controller.builtin_available is True and controller.builtin_input_verified
    )

    evidence = SafeUndockEvidence(
        attachment_binding=attachment_binding,
        generation=generation,
        sample_id=sample_id,
        game_state=snapshot.game_state,
        exact_attachment=fact(attachment_value, attachment_confidence),
        topology_exact=fact(topology_value, link.confidence),
        client_scan_complete=fact(readiness.scan_complete, scan_confidence),
        clients_clear=fact(clients_clear, scan_confidence),
        portable_display_active=fact(portable_display, portable_display_confidence),
        portable_render_gpu=fact(render_value, render_confidence),
        portable_audio_active=fact(audio_value, audio_confidence),
        builtin_controller_active=fact(controller_value, controller_confidence),
        external_display_active=fact(external_display, external_display_confidence),
    )
    return SafeUndockEvidenceResult(evidence, "safe_undock.evidence_composed")


def assess_report(report: SnapshotReport) -> SafeUndockReadiness:
    """Compose evidence from `report` and classify it in one step."""
    result = build_safe_undock_evidence(report)
    if result.evidence is None:
        return SafeUndockReadiness(
            SafeUndockReadinessState.EVIDENCE_INSUFFICIENT, result.code
        )
    evidence = result.evidence
    return assess_safe_undock_readiness(
        evidence,
        expected_attachment_binding=evidence.attachment_binding,
        expected_generation=evidence.generation,
        expected_sample_id=evidence.sample_id,
    )
