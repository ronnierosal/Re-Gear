from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.egpu_device_policy import (  # noqa: E402
    MAX_POLICY_DEVICES,
    DevicePolicyState,
    EgpuDeviceNode,
    EgpuDevicePolicy,
    compose_egpu_device_policy,
    missing_required_kinds,
)
from hdm.domain.models import EgpuResourceKind  # noqa: E402


#: The exact set measured on an Ally X with a GPD G1 attached, from
#: /dev/dri/by-path for 0000:08:00.0 and /dev/snd/by-path for 0000:08:00.1.
G1_NODES: tuple[EgpuDeviceNode, ...] = (
    EgpuDeviceNode(EgpuResourceKind.DRM_CARD, 226, 1),
    EgpuDeviceNode(EgpuResourceKind.DRM_RENDER, 226, 129),
    EgpuDeviceNode(EgpuResourceKind.AUDIO_CONTROL, 116, 15),
    EgpuDeviceNode(EgpuResourceKind.AUDIO_HARDWARE, 116, 14),
    EgpuDeviceNode(EgpuResourceKind.AUDIO_PCM, 116, 10),
    EgpuDeviceNode(EgpuResourceKind.AUDIO_PCM, 116, 11),
    EgpuDeviceNode(EgpuResourceKind.AUDIO_PCM, 116, 12),
    EgpuDeviceNode(EgpuResourceKind.AUDIO_PCM, 116, 13),
)

DRM_ONLY = G1_NODES[:2]


class NodeValidationTests(unittest.TestCase):
    def test_device_numbers_must_be_integers(self) -> None:
        with self.assertRaises(ValueError):
            EgpuDeviceNode(EgpuResourceKind.DRM_RENDER, 226, "129")

    def test_major_must_be_in_range(self) -> None:
        with self.assertRaises(ValueError):
            EgpuDeviceNode(EgpuResourceKind.DRM_RENDER, 1 << 12, 1)

    def test_minor_must_be_in_range(self) -> None:
        with self.assertRaises(ValueError):
            EgpuDeviceNode(EgpuResourceKind.DRM_RENDER, 226, 1 << 20)

    def test_number_is_the_compiler_pair(self) -> None:
        self.assertEqual(G1_NODES[1].number, (226, 129))


class MeasuredHardwareTests(unittest.TestCase):
    """The composition rules come from a supervised run; keep them pinned."""

    def test_full_g1_set_composes(self) -> None:
        policy = compose_egpu_device_policy(G1_NODES)
        self.assertIs(policy.state, DevicePolicyState.COMPOSED)
        self.assertTrue(policy.usable)

    def test_full_g1_set_is_eight_devices_within_the_compiler_limit(self) -> None:
        policy = compose_egpu_device_policy(G1_NODES)
        self.assertEqual(len(policy.devices), 8)
        self.assertLessEqual(len(policy.devices), MAX_POLICY_DEVICES)

    def test_drm_only_policy_is_refused(self) -> None:
        """Measured: this released steam and gamescope-wl but not wireplumber."""
        policy = compose_egpu_device_policy(DRM_ONLY)
        self.assertIs(policy.state, DevicePolicyState.EVIDENCE_INCOMPLETE)
        self.assertEqual(policy.code, "device_policy.missing_audio_control")
        self.assertEqual(policy.devices, ())

    def test_audio_only_policy_is_refused(self) -> None:
        policy = compose_egpu_device_policy(G1_NODES[2:])
        self.assertIs(policy.state, DevicePolicyState.EVIDENCE_INCOMPLETE)
        self.assertEqual(policy.code, "device_policy.missing_drm_render")

    def test_missing_both_required_kinds_is_named(self) -> None:
        nodes = (EgpuDeviceNode(EgpuResourceKind.DRM_CARD, 226, 1),)
        policy = compose_egpu_device_policy(nodes)
        self.assertEqual(
            policy.code, "device_policy.missing_audio_control_and_drm_render"
        )

    def test_required_kinds_reported_for_a_partial_observation(self) -> None:
        self.assertEqual(
            missing_required_kinds(DRM_ONLY), (EgpuResourceKind.AUDIO_CONTROL,)
        )

    def test_complete_observation_reports_nothing_missing(self) -> None:
        self.assertEqual(missing_required_kinds(G1_NODES), ())


class CompositionTests(unittest.TestCase):
    def test_devices_are_sorted_for_byte_identical_programs(self) -> None:
        forward = compose_egpu_device_policy(G1_NODES).devices
        reversed_input = compose_egpu_device_policy(tuple(reversed(G1_NODES))).devices
        self.assertEqual(forward, reversed_input)
        self.assertEqual(list(forward), sorted(forward))

    def test_duplicate_device_numbers_collapse(self) -> None:
        nodes = (*G1_NODES, EgpuDeviceNode(EgpuResourceKind.DRM_RENDER, 226, 129))
        self.assertEqual(len(compose_egpu_device_policy(nodes).devices), 8)

    def test_covered_kinds_are_reported(self) -> None:
        policy = compose_egpu_device_policy(G1_NODES)
        self.assertIn(EgpuResourceKind.DRM_RENDER, policy.covered_kinds)
        self.assertIn(EgpuResourceKind.AUDIO_CONTROL, policy.covered_kinds)

    def test_no_nodes_is_incomplete_not_empty_success(self) -> None:
        policy = compose_egpu_device_policy(())
        self.assertIs(policy.state, DevicePolicyState.EVIDENCE_INCOMPLETE)
        self.assertEqual(policy.code, "device_policy.no_nodes_observed")

    def test_non_tuple_input_is_invalid(self) -> None:
        policy = compose_egpu_device_policy(list(G1_NODES))
        self.assertIs(policy.state, DevicePolicyState.INVALID)

    def test_foreign_members_are_invalid(self) -> None:
        policy = compose_egpu_device_policy((*G1_NODES, "not-a-node"))
        self.assertIs(policy.state, DevicePolicyState.INVALID)

    def test_exceeding_the_compiler_limit_is_refused(self) -> None:
        extra = tuple(
            EgpuDeviceNode(EgpuResourceKind.AUDIO_PCM, 116, 100 + index)
            for index in range(MAX_POLICY_DEVICES)
        )
        policy = compose_egpu_device_policy((*G1_NODES, *extra))
        self.assertIs(policy.state, DevicePolicyState.TOO_MANY_DEVICES)
        self.assertEqual(policy.devices, ())

    def test_exactly_the_limit_still_composes(self) -> None:
        extra = tuple(
            EgpuDeviceNode(EgpuResourceKind.AUDIO_PCM, 116, 200 + index)
            for index in range(MAX_POLICY_DEVICES - len(G1_NODES))
        )
        policy = compose_egpu_device_policy((*G1_NODES, *extra))
        self.assertIs(policy.state, DevicePolicyState.COMPOSED)
        self.assertEqual(len(policy.devices), MAX_POLICY_DEVICES)


class PolicyInvariantTests(unittest.TestCase):
    def test_unusable_policy_cannot_carry_devices(self) -> None:
        with self.assertRaises(ValueError):
            EgpuDevicePolicy(
                DevicePolicyState.EVIDENCE_INCOMPLETE, "code", ((226, 129),)
            )

    def test_composed_policy_requires_devices(self) -> None:
        with self.assertRaises(ValueError):
            EgpuDevicePolicy(DevicePolicyState.COMPOSED, "code", ())


if __name__ == "__main__":
    unittest.main()
