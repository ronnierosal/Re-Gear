"""Pure composition of the exact device set an eGPU access filter must deny.

`hdm.delivery.device_filter_program.compile_device_filter` turns exact
`(major, minor)` pairs into a cgroup device policy, but nothing decided which
pairs belong in one. This module makes that decision from observed device nodes,
and refuses to produce a policy that hardware evidence says would be incomplete.

Supervised measurement on an Ally X with a GPD G1 attached, session idle on the
handheld panel:

- Denying only the two DRM nodes released `steam` and `gamescope-wl`, but
  `wireplumber` kept `audio_control` and the eGPU stayed held.
- Denying every DRM *and* ALSA node of both PCI functions released all three,
  and the readiness probe reached `ready_for_supervised_removal`.

So a policy covering only the render path is not merely weaker, it is
ineffective: one retained audio handle keeps `clients_clear` false. That is
encoded here as a required-kind check rather than left to the caller, and the
composition fails closed when evidence for a required kind is missing.

Pure: no I/O, no device or process action, and no removal claim. Producing a
policy authorises nothing on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import EgpuResourceKind


#: Mirrors `compile_device_filter`'s limit. Composing more than the compiler can
#: encode would fail later and further from the cause, so it is rejected here.
MAX_POLICY_DEVICES = 16

#: Linux device-number ranges, 12-bit major and 20-bit minor.
MAX_MAJOR = (1 << 12) - 1
MAX_MINOR = (1 << 20) - 1

#: Kinds a policy must cover to actually clear the device, established by the
#: measurement in this module's docstring. `DRM_RENDER` is what the compositor
#: and client hold; `AUDIO_CONTROL` is what the session audio daemon holds.
REQUIRED_KINDS: frozenset[EgpuResourceKind] = frozenset(
    {EgpuResourceKind.DRM_RENDER, EgpuResourceKind.AUDIO_CONTROL}
)


class DevicePolicyState(StrEnum):
    COMPOSED = "composed"
    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    TOO_MANY_DEVICES = "too_many_devices"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class EgpuDeviceNode:
    """One observed character device belonging to an exact eGPU function."""

    kind: EgpuResourceKind
    major: int
    minor: int

    def __post_init__(self) -> None:
        if type(self.major) is not int or type(self.minor) is not int:
            raise ValueError("device numbers must be integers")
        if not 0 <= self.major <= MAX_MAJOR or not 0 <= self.minor <= MAX_MINOR:
            raise ValueError("device numbers must be within Linux ranges")

    @property
    def number(self) -> tuple[int, int]:
        return (self.major, self.minor)


@dataclass(frozen=True, slots=True)
class EgpuDevicePolicy:
    """An exact, ordered device set ready for the filter compiler."""

    state: DevicePolicyState
    code: str
    devices: tuple[tuple[int, int], ...] = ()
    covered_kinds: tuple[EgpuResourceKind, ...] = ()

    def __post_init__(self) -> None:
        if self.state is DevicePolicyState.COMPOSED:
            if not self.devices:
                raise ValueError("a composed device policy needs devices")
        elif self.devices:
            raise ValueError("only a composed device policy exposes devices")

    @property
    def usable(self) -> bool:
        return self.state is DevicePolicyState.COMPOSED


def missing_required_kinds(
    nodes: tuple[EgpuDeviceNode, ...],
) -> tuple[EgpuResourceKind, ...]:
    """Return the required kinds absent from `nodes`, in a stable order."""
    present = {node.kind for node in nodes}
    return tuple(
        kind for kind in sorted(REQUIRED_KINDS, key=str) if kind not in present
    )


def compose_egpu_device_policy(
    nodes: tuple[EgpuDeviceNode, ...],
) -> EgpuDevicePolicy:
    """Compose the exact device set to deny, or say why it cannot be composed.

    Distinct nodes sharing a device number are collapsed, since the policy is
    expressed in device numbers. Ordering is deterministic so that an unchanged
    observation always compiles to a byte-identical program.
    """
    if type(nodes) is not tuple:
        return EgpuDevicePolicy(
            DevicePolicyState.INVALID, "device_policy.nodes_invalid"
        )
    if not nodes:
        return EgpuDevicePolicy(
            DevicePolicyState.EVIDENCE_INCOMPLETE, "device_policy.no_nodes_observed"
        )
    if any(type(node) is not EgpuDeviceNode for node in nodes):
        return EgpuDevicePolicy(
            DevicePolicyState.INVALID, "device_policy.nodes_invalid"
        )

    missing = missing_required_kinds(nodes)
    if missing:
        # Fail closed: a partial policy leaves a holder and reads as success.
        return EgpuDevicePolicy(
            DevicePolicyState.EVIDENCE_INCOMPLETE,
            "device_policy.missing_" + "_and_".join(kind.value for kind in missing),
        )

    numbers = tuple(sorted({node.number for node in nodes}))
    if len(numbers) > MAX_POLICY_DEVICES:
        return EgpuDevicePolicy(
            DevicePolicyState.TOO_MANY_DEVICES, "device_policy.device_limit_exceeded"
        )
    covered = tuple(sorted({node.kind for node in nodes}, key=str))
    return EgpuDevicePolicy(
        DevicePolicyState.COMPOSED,
        "device_policy.composed",
        numbers,
        covered,
    )
