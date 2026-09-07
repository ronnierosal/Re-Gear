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

from hdm.adapters.steamos.discovery import SteamOsDiscovery  # noqa: E402
from hdm.adapters.steamos.peripherals import (  # noqa: E402
    SteamOsPeripheralObservationAdapter,
)
from hdm.application.safe_undock_evidence import (  # noqa: E402
    build_safe_undock_evidence,
)
from hdm.application.snapshot import SnapshotService  # noqa: E402
from hdm.domain.safe_undock_readiness import (  # noqa: E402
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


def binding_fingerprint(binding: str) -> str:
    """Return a short digest so runs are comparable without emitting the id.

    Safety invariant 12 redacts hardware unique identifiers by default. A digest
    still shows whether the attachment changed between two runs, which is the
    only property this probe needs from it.
    """
    return hashlib.sha256(binding.encode("utf-8")).hexdigest()[:12]


def describe(report) -> dict[str, object]:
    """Classify one snapshot report and describe every contributing fact."""
    composed = build_safe_undock_evidence(report)
    evidence = composed.evidence
    if evidence is None:
        return {
            "state": SafeUndockReadinessState.EVIDENCE_INSUFFICIENT.value,
            "code": composed.code,
            "safe_to_unplug": False,
            "facts": [],
        }
    readiness = assess_safe_undock_readiness(
        evidence,
        expected_attachment_binding=evidence.attachment_binding,
        expected_generation=evidence.generation,
        expected_sample_id=evidence.sample_id,
    )
    facts = []
    for name, meaning in FACT_MEANINGS:
        fact = getattr(evidence, name)
        expected = EXPECTED_VALUES[name]
        facts.append(
            {
                "fact": name,
                "means": meaning,
                "value": fact.value,
                "verified": fact.verified,
                "satisfied": fact.verified and fact.value is expected,
            }
        )
    return {
        "state": readiness.state.value,
        "code": readiness.code,
        # Never let a readiness state be mistaken for physical clearance.
        "safe_to_unplug": False,
        "game_state": evidence.game_state.value,
        "attachment_fingerprint": binding_fingerprint(evidence.attachment_binding),
        "blocking": [item["fact"] for item in facts if not item["satisfied"]],
        "facts": facts,
    }


def render(result: dict[str, object]) -> str:
    lines = [
        f"Safe Undock state : {result['state']}",
        f"Code              : {result['code']}",
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
            value = "unknown" if item["value"] is None else str(item["value"]).lower()
            verified = "verified" if item["verified"] else "unverified"
            lines.append(
                f"  [{mark}] {item['fact']}: {value} ({verified}) - {item['means']}"
            )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="emit the machine-readable report"
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
    return (
        0
        if result["state"] == SafeUndockReadinessState.READY_FOR_REVALIDATION.value
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
