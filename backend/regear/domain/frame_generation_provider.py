"""Frame-generation providers, and an inert LSFG-VK configuration planner.

A provider turns an already-made decision into *proposed* configuration data.
It never decides whether FG should be used -- that is the resolver's job -- and
it never installs, locates, probes, downloads or executes anything. Its only
output is data describing what a launch *would* carry, plus the requirements
that are still unresolved.

LSFG-VK is the first provider. Re-Gear does not redistribute it, its code or
any Lossless Scaling component: the player buys and installs Lossless Scaling
and installs the Linux component themselves, and Re-Gear only generates
configuration for documented interfaces. Generating that configuration is not
a claim of legal clearance or upstream permission, and none is made here.

The environment-variable names below are the v2 contract as recorded in
``docs/research/frame-generation.md`` (Codex's reading of the pinned 2.0.0
documentation). This implementing session could not reach lsfg-vk.dev through
its egress proxy and did not independently re-verify them; re-check against
the selected release before anything depends on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol

from .performance_target_resolver import Decision, RenderMethod, ProviderKind


LSFG_VK_PROVIDER_ID = "lsfg-vk"
#: Tag 2.0.0, as resolved read-only in the research note.
LSFG_VK_REVISION = "2333707d55b68ddd8066fd95404c3b7d07e00d3a"
LSFG_VK_VERSION = "2.0.0"
#: The only pacing mode current upstream documentation lists.
LSFG_VK_PACING = "vsync"

#: Keys this provider may propose. Anything a player already set under one of
#: these, or the opt-out below, is theirs and is never overwritten.
LSFG_VK_ENV_KEYS = (
    "LSFGVK_ENV",
    "LSFGVK_DLL_PATH",
    "LSFGVK_MULTIPLIER",
    "LSFGVK_PACING_MODE",
)
#: File-based configuration routes; their presence means the player already
#: configured LSFG-VK another way.
LSFG_VK_PLAYER_CONFIG_KEYS = ("LSFGVK_CONFIG", "LSFGVK_PROFILE")
#: An explicit player opt-out. Never erased, never worked around.
LSFG_VK_DISABLE_KEY = "DISABLE_LSFGVK"

#: Requirements no configuration can satisfy in this milestone. They are
#: attached to every LSFG-VK plan so that none can read as complete.
LSFG_VK_STANDING_REQUIREMENTS = (
    "launch_interception_seam: no reviewed seam supplies opaque original launch "
    "data and applies a reversible per-launch overlay; Steam launch options are "
    "not written",
    "layer_visibility: Vulkan layer discovery inside Steam's runtime container "
    "and the game's bitness is not established",
    "rights_decision: the integration/distribution model has no recorded rights "
    "decision; configuration generation is not a claim of legal clearance",
)


@dataclass(frozen=True, slots=True)
class ProviderConfiguration:
    """Proposed data for one launch. Describes; never authorises."""

    provider_id: str
    revision: str
    environment_overlay: Mapping[str, str] = field(default_factory=dict)
    unresolved: tuple[str, ...] = ()
    refused: str = ""

    @property
    def proposes_anything(self) -> bool:
        return bool(self.environment_overlay) and not self.refused


class FrameGenerationProvider(Protocol):
    provider_id: str
    revision: str

    def plan(
        self, decision: Decision, original_environment: Mapping[str, str]
    ) -> ProviderConfiguration: ...


@dataclass(frozen=True, slots=True)
class LsfgVkProvider:
    """Inert configuration planner for the pinned LSFG-VK revision.

    ``dll_path`` is supplied by the caller -- in this milestone always a fixture
    path. The provider does not look for the DLL, check that it exists, or
    guess the historical ``Lossless.dll`` name.
    """

    dll_path: str
    provider_id: str = LSFG_VK_PROVIDER_ID
    revision: str = LSFG_VK_REVISION

    def plan(
        self, decision: Decision, original_environment: Mapping[str, str]
    ) -> ProviderConfiguration:
        base = ProviderConfiguration(self.provider_id, self.revision)
        record = decision.record
        if decision.method is not RenderMethod.FRAME_GENERATION or record is None:
            return _refuse(base, "the decision did not select frame generation")
        if record.provider_kind is not ProviderKind.EXTERNAL:
            return _refuse(base, "LSFG-VK is an external provider")
        if record.provider_id != self.provider_id or record.provider_revision != self.revision:
            return _refuse(base, "the decision was made for another provider revision")
        if not self.dll_path or "\n" in self.dll_path or "\0" in self.dll_path:
            return _refuse(base, "no usable DLL path was supplied")
        if LSFG_VK_DISABLE_KEY in original_environment:
            return _refuse(
                base, f"the player set {LSFG_VK_DISABLE_KEY}; that opt-out is respected"
            )
        owned = sorted(
            key
            for key in original_environment
            if key.startswith("LSFGVK_")
        )
        if owned:
            return _refuse(
                base,
                "the player already configures LSFG-VK (" + ", ".join(owned) + "); "
                "their configuration is not overwritten",
            )
        overlay = {
            "LSFGVK_ENV": "1",
            "LSFGVK_DLL_PATH": self.dll_path,
            "LSFGVK_MULTIPLIER": str(decision.multiplier),
            "LSFGVK_PACING_MODE": LSFG_VK_PACING,
        }
        return ProviderConfiguration(
            self.provider_id,
            self.revision,
            overlay,
            unresolved=tuple(decision.unresolved) + LSFG_VK_STANDING_REQUIREMENTS,
        )


def _refuse(base: ProviderConfiguration, reason: str) -> ProviderConfiguration:
    return ProviderConfiguration(base.provider_id, base.revision, {}, (), reason)
