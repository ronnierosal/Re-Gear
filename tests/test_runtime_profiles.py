from __future__ import annotations

import json
import re
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.control_plane import CapabilitySupport, PlacementState  # noqa: E402
from regear.domain.models import Confidence  # noqa: E402
from regear.domain.manual_transition import evidence_from_snapshot  # noqa: E402
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.profiles.registry import (  # noqa: E402
    CapabilityAxis,
    CapabilityDiagnostic,
    CapabilityEvidenceBasis,
    EgpuProfileDefinition,
    HostProfileDefinition,
    ProfileResolutionStatus,
    RuntimeProfileCatalog,
    RuntimeProfileDiagnostics,
    resolve_runtime_profiles,
    runtime_profile_diagnostics_to_dict,
)
from regear.profiles.ally_x import CAPABILITIES as ALLY_X_CAPABILITIES  # noqa: E402
from regear.profiles.gpd_g1 import CAPABILITIES as GPD_G1_CAPABILITIES  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def observed(name: str, **changes):
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    value.update(changes)
    for gpu in value["gpus"]:
        if gpu["role"] == "external":
            gpu["stable_id"] = "gpd-g1:0123456789abcdef"
    if value["gamescope"].get("render_gpu_stable_id", "").startswith("gpd-g1"):
        value["gamescope"]["render_gpu_stable_id"] = "gpd-g1:0123456789abcdef"
    return snapshot_from_dict(value)


class RuntimeProfileTests(unittest.TestCase):
    def test_diagnostics_require_each_capability_axis_exactly_once(self):
        item = CapabilityDiagnostic(
            CapabilityAxis.EGPU_SUPPORT,
            "verified",
            Confidence.VERIFIED,
            CapabilityEvidenceBasis.EXACT_HOST_PROFILE,
        )
        with self.assertRaisesRegex(ValueError, "each capability axis once"):
            RuntimeProfileDiagnostics(
                ProfileResolutionStatus.EXACT,
                "host",
                ProfileResolutionStatus.EXACT,
                "egpu",
                (item,),
            )

    def test_exact_snapshot_resolves_ally_g1_without_promoting_experimental(self):
        snapshot = observed("connected-internal.json")
        resolved = resolve_runtime_profiles(snapshot)
        self.assertTrue(resolved.exact_host)
        self.assertTrue(resolved.exact_egpu)
        self.assertEqual(resolved.host_status, ProfileResolutionStatus.EXACT)
        self.assertEqual(resolved.egpu_status, ProfileResolutionStatus.EXACT)
        self.assertEqual(
            resolved.capabilities.display_handoff,
            CapabilitySupport.EXPERIMENTAL,
        )
        evidence = evidence_from_snapshot(
            snapshot,
            observed_generation="generation-1",
            capabilities=resolved.capabilities,
        )
        self.assertEqual(evidence.host_profile_id, "asus-rog-ally-x")
        self.assertEqual(evidence.egpu_stable_id, resolved.egpu_stable_id)
        self.assertTrue(evidence.source_recovery_ready_verified)
        self.assertIsNotNone(evidence.binding())

    def test_unknown_or_ambiguous_identity_gets_no_g1_capabilities(self):
        value = observed("connected-internal.json", support_tier="experimental")
        resolved = resolve_runtime_profiles(value)
        self.assertFalse(resolved.exact_egpu)
        self.assertEqual(resolved.capabilities.egpu_support, CapabilitySupport.VERIFIED)
        self.assertEqual(resolved.capabilities.display_handoff, CapabilitySupport.UNKNOWN)

    def test_exact_g1_resolution_requires_typed_identity_binding(self):
        value = json.loads((FIXTURES / "connected-internal.json").read_text())
        value["disconnect_readiness"]["egpu_stable_id"] = "gpd-g1:fedcba9876543210"
        mismatch = resolve_runtime_profiles(snapshot_from_dict(value))
        self.assertFalse(mismatch.exact_egpu)
        self.assertEqual(mismatch.egpu_status, ProfileResolutionStatus.UNKNOWN)
        self.assertEqual(mismatch.capabilities.display_handoff, CapabilitySupport.UNKNOWN)
        self.assertEqual(mismatch.capabilities.audio_handoff, CapabilitySupport.UNKNOWN)
        self.assertEqual(mismatch.capabilities.sleep_behavior.value, "untested")
        self.assertEqual(mismatch.capabilities.removal_behavior.value, "unknown")

        value = json.loads((FIXTURES / "connected-internal.json").read_text())
        value["gpus"][1]["stable_id"] = "gpd-g1:similar-name"
        value["disconnect_readiness"]["egpu_stable_id"] = "gpd-g1:similar-name"
        similar = resolve_runtime_profiles(snapshot_from_dict(value))
        self.assertFalse(similar.exact_egpu)
        self.assertEqual(similar.capabilities.display_handoff, CapabilitySupport.UNKNOWN)

    def test_diagnostics_keep_capability_axes_and_evidence_independent(self):
        diagnostics = runtime_profile_diagnostics_to_dict(
            resolve_runtime_profiles(observed("connected-internal.json")).diagnostics()
        )
        capabilities = {
            item["axis"]: item for item in diagnostics["capabilities"]
        }
        self.assertEqual(diagnostics["host"]["status"], "exact")
        self.assertEqual(diagnostics["egpu"]["status"], "exact")
        self.assertEqual(capabilities["egpu_transport"]["value"], "usb4")
        self.assertEqual(
            capabilities["external_display_output"]["confidence"], "verified"
        )
        self.assertEqual(capabilities["display_handoff"]["value"], "experimental")
        self.assertEqual(capabilities["audio_handoff"]["confidence"], "observed")
        self.assertEqual(
            capabilities["external_controller_promotion"]["value"], "unknown"
        )
        self.assertEqual(
            capabilities["sleep_behavior"]["value"],
            "disconnect_before_sleep_verified",
        )
        self.assertEqual(
            capabilities["removal_behavior"]["value"],
            "shutdown_before_disconnect",
        )

    def test_unknown_host_and_egpu_emit_no_mutation_capability(self):
        snapshot = observed(
            "ambiguous.json",
            host_profile="unknown",
            support_tier="unknown",
        )
        resolved = resolve_runtime_profiles(snapshot)
        self.assertFalse(resolved.exact_host)
        self.assertFalse(resolved.exact_egpu)
        self.assertEqual(resolved.host_status, ProfileResolutionStatus.UNKNOWN)
        self.assertEqual(resolved.egpu_status, ProfileResolutionStatus.UNKNOWN)
        self.assertEqual(resolved.capabilities.display_handoff, CapabilitySupport.UNKNOWN)
        self.assertEqual(resolved.capabilities.audio_handoff, CapabilitySupport.UNKNOWN)

    def test_docked_source_builds_a_recoverable_exact_binding(self):
        snapshot = observed("tv-docked.json")
        resolved = resolve_runtime_profiles(snapshot)
        evidence = evidence_from_snapshot(
            snapshot,
            observed_generation="generation-2",
            capabilities=resolved.capabilities,
        )
        self.assertTrue(evidence.source_recovery_ready_verified)
        self.assertEqual(evidence.external_display_stable_id, "external-tv")

    def test_missing_internal_fallback_keeps_recovery_unverified(self):
        snapshot = observed("connected-internal.json")
        snapshot = snapshot_from_dict(
            {
                **json.loads((FIXTURES / "connected-internal.json").read_text()),
                "gpus": [
                    {
                        **gpu,
                        "stable_id": "gpd-g1:0123456789abcdef",
                    }
                    for gpu in json.loads(
                        (FIXTURES / "connected-internal.json").read_text()
                    )["gpus"]
                    if gpu["role"] == "external"
                ],
            }
        )
        resolved = resolve_runtime_profiles(snapshot)
        evidence = evidence_from_snapshot(
            snapshot,
            observed_generation="generation-3",
            capabilities=resolved.capabilities,
        )
        self.assertFalse(evidence.source_recovery_ready_verified)
        self.assertIsNone(evidence.binding())

    def test_explicit_catalog_allows_new_profiles_without_registry_conditionals(self):
        host = replace(ALLY_X_CAPABILITIES, profile_id="test-handheld")
        egpu = replace(GPD_G1_CAPABILITIES, profile_id="test-egpu")
        catalog = RuntimeProfileCatalog(
            hosts=(HostProfileDefinition("test-handheld", host),),
            egpus=(
                EgpuProfileDefinition(
                    "test-egpu", re.compile(r"test-egpu:[0-9a-f]{16}"), egpu
                ),
            ),
        )
        current = observed("connected-internal.json")
        external = tuple(
            replace(gpu, stable_id="test-egpu:0123456789abcdef")
            if gpu.role.value == "external"
            else gpu
            for gpu in current.gpus
        )
        snapshot = replace(
            current,
            host_profile="test-handheld",
            gpus=external,
            disconnect_readiness=replace(
                current.disconnect_readiness,
                egpu_stable_id="test-egpu:0123456789abcdef",
            ),
        )
        resolved = resolve_runtime_profiles(snapshot, catalog)
        self.assertTrue(resolved.exact_host)
        self.assertTrue(resolved.exact_egpu)
        self.assertEqual(resolved.capabilities.host_profile_id, "test-handheld")
        self.assertEqual(resolved.capabilities.egpu_profile_id, "test-egpu")

    def test_ambiguous_catalog_match_fails_closed(self):
        host = replace(ALLY_X_CAPABILITIES, profile_id="test-handheld")
        first = replace(GPD_G1_CAPABILITIES, profile_id="test-egpu-one")
        second = replace(GPD_G1_CAPABILITIES, profile_id="test-egpu-two")
        catalog = RuntimeProfileCatalog(
            hosts=(HostProfileDefinition("test-handheld", host),),
            egpus=(
                EgpuProfileDefinition("test-egpu-one", re.compile(r"test:[0-9a-f]{16}"), first),
                EgpuProfileDefinition("test-egpu-two", re.compile(r"test:[0-9a-f]{16}"), second),
            ),
        )
        current = observed("connected-internal.json")
        external = tuple(
            replace(gpu, stable_id="test:0123456789abcdef")
            if gpu.role.value == "external"
            else gpu
            for gpu in current.gpus
        )
        snapshot = replace(
            current,
            host_profile="test-handheld",
            gpus=external,
            disconnect_readiness=replace(
                current.disconnect_readiness, egpu_stable_id="test:0123456789abcdef"
            ),
        )
        resolved = resolve_runtime_profiles(snapshot, catalog)
        self.assertTrue(resolved.exact_host)
        self.assertFalse(resolved.exact_egpu)
        self.assertEqual(resolved.capabilities.display_handoff, CapabilitySupport.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
