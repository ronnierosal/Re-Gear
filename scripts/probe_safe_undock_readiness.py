"""Read-only Safe Undock readiness probe for supervised hardware runs.

Collects one snapshot through the existing read-only diagnostics API, composes
it into the Safe Undock evidence contract, and prints which facts block. Its
purpose during a hardware run is to answer "what is still holding the eGPU right
now" with the same classification the product uses, rather than an ad-hoc check.

`ready_for_revalidation` is NOT clearance to unplug anything. It means the
current observation is internally consistent and complete enough to hand to a
separate supervised validation step. This script performs no device, process,
display, or power action, and writes nothing.

Usage on the device:

    PYTHONPATH=backend python scripts/probe_safe_undock_readiness.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Sequence


if Path(__file__).name != "__main__.py":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.adapters.steamos.discovery import SteamOsDiscovery  # noqa: E402
from regear.adapters.steamos.peripherals import (  # noqa: E402
    SteamOsPeripheralObservationAdapter,
)
from regear.application.safe_undock_evidence import (  # noqa: E402
    build_safe_undock_evidence,
)
from regear.domain.removal_safety import (  # noqa: E402
    REMOVAL_SAFETY_FACTS,
    RemovalSafetyState,
    assess_removal_safety,
)
from regear.application.snapshot import SnapshotService  # noqa: E402
from regear.domain.safe_undock_readiness import (  # noqa: E402
    SafeUndockReadinessState,
    assess_safe_undock_readiness,
)


#: Facts in the order the domain assessor consults them, with the player-facing
#: meaning of each, so a blocked run reads as a next action rather than a code.
FACT_MEANINGS: tuple[tuple[str, str], ...] = (
    ("exact_attachment", "the exact eGPU profile is attached and certified"),
    ("topology_exact", "the eGPU link topology is exact and up"),
    ("client_scan_complete", "the client scan finished"),
    ("clients_clear", "nothing still holds the eGPU nodes"),
    ("portable_display_active", "the handheld panel is the active display"),
    ("portable_render_gpu", "the internal GPU is selected for render"),
    ("portable_audio_active", "audio is on a portable output"),
    ("builtin_controller_active", "the built-in controller is usable"),
    ("external_display_active", "the external display is NOT active"),
)

EXPECTED_VALUES = {name: name != "external_display_active" for name, _ in FACT_MEANINGS}

#: Facts that cannot currently be satisfied for reasons in the code rather than
#: the hardware. Without this, a supervised run reads these as device problems
#: and sends the operator chasing hardware that is working correctly.
KNOWN_STRUCTURAL_GAPS: dict[str, str] = {
    "portable_audio_active": (
        "SteamOsPeripheralObservationAdapter never observes the active output: "
        "even fully mapped it returns exact=False, current_output=UNKNOWN and "
        "failure_code='audio.default_output_unobserved' (see issue #93)"
    ),
    "builtin_controller_active": (
        "requires PeripheralMappingEvidence, which production never supplies, "
        "so the controller subsystem always fails closed (see issue #93)"
    ),
}


def binding_fingerprint(binding: str) -> str:
    """Return a short digest so runs are comparable without emitting the id.

    Safety invariant 12 redacts hardware unique identifiers by default. A digest
    still shows whether the attachment changed between two runs, which is the
    only property this probe needs from it.
    """
    return hashlib.sha256(binding.encode("utf-8")).hexdigest()[:12]


def holders(report) -> list[dict[str, object]]:
    """List what still holds the eGPU, shaped like the product's own preview.

    `ProcessReleasePreviewRow` exposes name and resources only, so this matches
    that redaction rather than inventing a wider one: no PIDs, no command lines,
    no paths. `kind` and `close_eligible` are included because they decide what
    an operator may do next, and neither identifies anything.
    """
    rows = []
    for observed in report.snapshot.disconnect_readiness.clients:
        rows.append(
            {
                "name": observed.name,
                "kind": observed.kind.value,
                "resources": [resource.value for resource in observed.resources],
                "close_eligible": observed.close_eligible,
                "reason": observed.reason,
            }
        )
    return sorted(rows, key=lambda row: (row["kind"], row["name"]))


def describe(report) -> dict[str, object]:
    """Classify one snapshot report and describe every contributing fact."""
    composed = build_safe_undock_evidence(report)
    evidence = composed.evidence
    if evidence is None:
        # Both verdicts report the same failure here: without composed evidence
        # neither can be assessed, and leaving removal safety unset rendered it
        # as "unknown ()", which reads like a third state rather than a stop.
        return {
            "state": SafeUndockReadinessState.EVIDENCE_INSUFFICIENT.value,
            "code": composed.code,
            "removal_safety_state": RemovalSafetyState.EVIDENCE_INSUFFICIENT.value,
            "removal_safety_code": composed.code,
            "safe_to_unplug": False,
            "holders": holders(report),
            "facts": [],
        }
    identity = {
        "expected_attachment_binding": evidence.attachment_binding,
        "expected_generation": evidence.generation,
        "expected_sample_id": evidence.sample_id,
    }
    readiness = assess_safe_undock_readiness(evidence, **identity)
    removal = assess_removal_safety(evidence, **identity)
    facts = []
    for name, meaning in FACT_MEANINGS:
        fact = getattr(evidence, name)
        expected = EXPECTED_VALUES[name]
        satisfied = fact.verified and fact.value is expected
        entry = {
            "fact": name,
            "removal_safety": name in REMOVAL_SAFETY_FACTS,
            "means": meaning,
            "value": fact.value,
            "verified": fact.verified,
            "satisfied": satisfied,
        }
        if not satisfied and name in KNOWN_STRUCTURAL_GAPS:
            entry["known_gap"] = KNOWN_STRUCTURAL_GAPS[name]
        facts.append(entry)
    return {
        "state": readiness.state.value,
        "code": readiness.code,
        "removal_safety_state": removal.state.value,
        "removal_safety_code": removal.code,
        # Never let a readiness state be mistaken for physical clearance.
        "safe_to_unplug": False,
        "game_state": evidence.game_state.value,
        "attachment_fingerprint": binding_fingerprint(evidence.attachment_binding),
        "blocking": [item["fact"] for item in facts if not item["satisfied"]],
        "holders": holders(report),
        "facts": facts,
    }


def render(result: dict[str, object]) -> str:
    lines = [
        f"Safe Undock state : {result['state']}  ({result['code']})",
        f"Removal safety    : {result.get('removal_safety_state', 'unknown')}"
        f"  ({result.get('removal_safety_code', '')})",
        f"Safe to unplug    : no (this probe never grants removal clearance)",
    ]
    if result.get("attachment_fingerprint"):
        lines.append(f"Attachment        : {result['attachment_fingerprint']}")
    if result.get("game_state"):
        lines.append(f"Game state        : {result['game_state']}")
    facts = result.get("facts") or []
    if facts:
        lines.append("")
        for item in facts:
            mark = "ok  " if item["satisfied"] else "BLOCK"
            scope = "removal" if item.get("removal_safety") else "player "
            value = "unknown" if item["value"] is None else str(item["value"]).lower()
            verified = "verified" if item["verified"] else "unverified"
            lines.append(
                f"  [{mark}][{scope}] {item['fact']}: {value} ({verified}) - {item['means']}"
            )
            if item.get("known_gap"):
                lines.append(f"          known code gap, not hardware: {item['known_gap']}")
    rows = result.get("holders") or []
    if rows:
        lines.append("")
        lines.append(f"Still holding the eGPU ({len(rows)}):")
        for row in rows:
            resources = ", ".join(row["resources"]) or "none"
            closable = "closable" if row["close_eligible"] else "PROTECTED"
            lines.append(f"  - {row['name']} [{row['kind']}, {closable}]: {resources}")
            if row.get("reason"):
                lines.append(f"      {row['reason']}")
    blocking = [item for item in facts if not item["satisfied"]]
    hardware = [item for item in blocking if not item.get("known_gap")]
    if blocking:
        lines.append("")
        lines.append(
            f"{len(blocking)} blocking, of which {len(hardware)} are hardware state; "
            f"{len(blocking) - len(hardware)} are known code gaps (issue #93)."
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="emit the machine-readable report"
    )
    parser.add_argument(
        "--exit-on",
        choices=("safe-undock", "removal-safety"),
        default="safe-undock",
        help="which verdict the exit status reflects; 'safe-undock' (default)"
        " keeps the established meaning of zero, 'removal-safety' reports the"
        " narrower verdict that gates a supervised software-removal run",
    )
    arguments = parser.parse_args(argv)
    # `DiagnosticsApi` deliberately wires discovery only, so Safe Undock
    # evidence — which needs controller and audio facts — cannot be composed
    # from it. Compose the same read-only service here with the peripheral
    # observer attached, rather than changing the shared API surface.
    service = SnapshotService(
        SteamOsDiscovery(),
        peripheral_observation=SteamOsPeripheralObservationAdapter(),
    )
    try:
        report = service.observe()
    except OSError as error:
        print(f"Could not collect a snapshot: {error}", file=sys.stderr)
        return 2
    result = describe(report)
    print(json.dumps(result, indent=2, sort_keys=True) if arguments.json else render(result))
    # The default exit status keeps its established meaning: zero only when the
    # full nine-fact Safe Undock contract is satisfied. Removal safety is a
    # narrower verdict, so reporting it by default would let a caller that
    # treats zero as full readiness receive zero while audio and controller
    # readiness are still blocked. Callers gating a supervised removal ask for
    # it explicitly.
    if arguments.exit_on == "removal-safety":
        satisfied = (
            result.get("removal_safety_state")
            == RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL.value
        )
    else:
        satisfied = (
            result["state"] == SafeUndockReadinessState.READY_FOR_REVALIDATION.value
        )
    return 0 if satisfied else 1


if __name__ == "__main__":
    raise SystemExit(main())
