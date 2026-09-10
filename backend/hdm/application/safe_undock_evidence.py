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
from ..domain.removal_safety import (
    RemovalSafety,
    RemovalSafetyState,
    assess_removal_safety,
)
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


def _topology_exact(
    snapshot: ObservedSnapshot,
    attachment_value: bool | None,
    attachment_confidence: Confidence,
) -> tuple[bool | None, Confidence]:
    """Grade link topology by joining the link reading with the exact identity.

    `PcieLinkHealthDiscovery` never returns `Confidence.VERIFIED`: it reads only
    link sysfs for a bridge address and cannot see whether that bridge belongs to
    an exactly matched, certified eGPU, so it correctly refuses to claim more
    than `OBSERVED`. This composer is the first place both halves are available,
    so the join belongs here.

    The upgrade is deliberately narrow. It requires an exactly matched, certified
    attachment verified independently, an applicable link that is up, and both
    negotiated metrics actually present. Anything less passes the adapter's own
    grade through unchanged, so a degraded or ambiguous link never gains
    confidence it did not earn.
    """
    link = snapshot.egpu_link
    if not link.applicable:
        return None, Confidence.UNKNOWN
    up = link.state is EgpuLinkState.UP
    metrics_present = link.speed_gtps is not None and link.width_lanes is not None
    identity_verified = (
        attachment_value is True and attachment_confidence is Confidence.VERIFIED
    )
    if up and metrics_present and identity_verified:
        return True, Confidence.VERIFIED
    if link.state is EgpuLinkState.UNKNOWN:
        return None, link.confidence
    return up, link.confidence


def _inactive_grade(display) -> Confidence:
    """Grade a claim that this display is inactive, checking it against the mode.

    The producing adapter already refuses to verify a not-preferred connector
    that still has a mode committed. This repeats the check where the fact is
    consumed, because the grade and the signal it rests on travel separately:
    they survive serialization, and a second adapter or a hand-built observation
    could present a verified inactive display whose mode is still committed.

    A safety gate should not accept a producer's grade that contradicts a raw
    signal it holds itself, so anything but a definitely released connector is
    unknown here rather than verified inactive.
    """
    if display.mode_committed is False:
        return display.active_confidence
    return Confidence.UNKNOWN


def _display_active(
    snapshot: ObservedSnapshot, kind: DisplayKind
) -> tuple[bool | None, Confidence]:
    """Report whether any display of `kind` is active, not merely connected.

    Safety invariant 6: a connected connector is not proof of an active display,
    so this reads `active` and never falls back to `connected`. A mixed set with
    no active member is unknown rather than inactive.

    The grade comes from `active_confidence`, not `confidence`. The latter
    records whether the connector's connection was observable, and reading it
    here is how `external_display_active` came to report a verified false for a
    connector that was no longer preferred but still had a mode committed --
    still potentially holding the external GPU's scanout resources.
    """
    matching = tuple(display for display in snapshot.displays if display.kind is kind)
    if not matching:
        return False, Confidence.UNKNOWN
    active = tuple(display for display in matching if display.active is True)
    if active:
        return True, min(
            (item.active_confidence for item in active), key=_confidence_rank
        )
    if all(display.active is False for display in matching):
        return False, min(
            (_inactive_grade(item) for item in matching), key=_confidence_rank
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

    topology_value, topology_confidence = _topology_exact(
        snapshot, attachment_value, attachment_confidence
    )

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
    # `builtin_input_verified` records that a player actually pressed something,
    # which no passive observation can establish. Safe Undock asks whether the
    # handheld's own controller is present and exactly identified, so availability
    # under an exact mapping is the right signal; requiring the interactive flag
    # here would make the fact permanently unsatisfiable.
    controller_value = controller.builtin_available is True

    evidence = SafeUndockEvidence(
        attachment_binding=attachment_binding,
        generation=generation,
        sample_id=sample_id,
        game_state=snapshot.game_state,
        exact_attachment=fact(attachment_value, attachment_confidence),
        topology_exact=fact(topology_value, topology_confidence),
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


def assess_removal_safety_report(report: SnapshotReport) -> RemovalSafety:
    """Classify `report` for removal safety only.

    Narrower than `assess_report`: it omits the player-recoverability facts, so
    a supervised software-removal experiment is not gated on whether the player
    would still have sound. See `hdm.domain.removal_safety` for why.
    """
    result = build_safe_undock_evidence(report)
    if result.evidence is None:
        return RemovalSafety(
            RemovalSafetyState.EVIDENCE_INSUFFICIENT, result.code
        )
    evidence = result.evidence
    return assess_removal_safety(
        evidence,
        expected_attachment_binding=evidence.attachment_binding,
        expected_generation=evidence.generation,
        expected_sample_id=evidence.sample_id,
    )
