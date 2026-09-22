"""Synthetic fixtures for the inert frame-generation prototype.

Every value here is invented for tests. The AppID is deliberately outside the
range Steam has issued, so it cannot be mistaken for a real game, and none of
the frame rates is a measurement: "stable 30 with 2x" is the scenario the
assignment asks the prototype to demonstrate, not a finding about any game or
any hardware.

The adapter reuses the accepted foundation's schema fixture, so the prototype
composes with the existing GameSettingsAdapter/GraphicsProfile contracts rather
than defining a parallel profile system.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from graphics_profile_fixtures import (  # noqa: E402
    FRAME_LIMIT,
    SHADOW,
    TEXTURE,
    sample_schema,
)
from regear.domain.frame_generation_provider import (  # noqa: E402
    LSFG_VK_PROVIDER_ID,
    LSFG_VK_REVISION,
)
from regear.domain.graphics_game_adapter import GameSettingsAdapter  # noqa: E402
from regear.domain.mode_profiles import ExperienceTarget  # noqa: E402
from regear.domain.models import OperatingMode  # noqa: E402
from regear.domain.performance_target_resolver import (  # noqa: E402
    CompatibilityRecord,
    EvidenceStatus,
    InjectionEligibility,
    LimiterState,
    PresentationContext,
    ProfileBinding,
    ProviderState,
    RenderMethod,
    VrrState,
)


#: Outside every AppID Steam has issued; unmistakably synthetic.
FIXTURE_APP_ID = "4000000001"
#: The assignment's future supervised-validation candidate. Used only to show
#: that, without evidence, it resolves to no automatic change.
FF7_REMAKE_APP_ID = "1462040"

FIXTURE_BUILD = "fixture-build-1"
FIXTURE_RUNTIME = "fixture-proton/fixture-dxvk/fixture-driver"
FIXTURE_GPU = "fixture-render-gpu"
FIXTURE_DISPLAY = "fixture-tv"
FIXTURE_DLL = "/fixture/lossless-scaling/lsfg-vk.dll"


def adapter() -> GameSettingsAdapter:
    schema, validators = sample_schema()
    return GameSettingsAdapter(
        adapter_id="regear-fixture-framegen-game",
        steam_app_ids=(FIXTURE_APP_ID,),
        config_filename="graphics.ini",
        relative_dir="ReGearFixtureGame/Config",
        schema=schema,
        owned_keys=validators,
        declared_settings={
            ExperienceTarget.BALANCED: {TEXTURE: "2", SHADOW: "2", FRAME_LIMIT: "60"},
            ExperienceTarget.QUALITY: {TEXTURE: "3", SHADOW: "3", FRAME_LIMIT: "60"},
        },
    )


def context(**overrides) -> PresentationContext:
    values = dict(
        steam_app_id=FIXTURE_APP_ID,
        game_build=FIXTURE_BUILD,
        mode=OperatingMode.TV_DOCKED,
        render_gpu=FIXTURE_GPU,
        display_owner=FIXTURE_DISPLAY,
        runtime=FIXTURE_RUNTIME,
        refresh_hz=60,
        vrr=VrrState.OFF,
    )
    values.update(overrides)
    return PresentationContext(**values)


def binding(target: ExperienceTarget = ExperienceTarget.QUALITY) -> ProfileBinding:
    schema, _ = sample_schema()
    return ProfileBinding(
        adapter_id="regear-fixture-framegen-game",
        target=target,
        profile_version=1,
        schema_id=schema.schema_id,
    )


def native(record_id: str = "native-quality", fps: int = 30, **overrides) -> CompatibilityRecord:
    values = dict(
        record_id=record_id,
        steam_app_id=FIXTURE_APP_ID,
        game_build=FIXTURE_BUILD,
        mode=OperatingMode.TV_DOCKED,
        render_gpu=FIXTURE_GPU,
        runtime=FIXTURE_RUNTIME,
        refresh_hz=60,
        profile=binding(),
        method=RenderMethod.NATIVE,
        status=EvidenceStatus.VALIDATED,
        stable_base_fps=fps,
        output_fps=fps,
        evidence_revision="fixture-evidence-1",
    )
    values.update(overrides)
    return CompatibilityRecord(**values)


def upscaled(record_id: str = "upscaled-balanced", fps: int = 60, **overrides) -> CompatibilityRecord:
    return native(
        record_id,
        fps,
        method=RenderMethod.UPSCALED,
        profile=binding(ExperienceTarget.BALANCED),
        **overrides,
    )


def frame_generation(
    record_id: str = "fg-quality-2x",
    base: int = 30,
    multiplier: int = 2,
    **overrides,
) -> CompatibilityRecord:
    values = dict(
        record_id=record_id,
        steam_app_id=FIXTURE_APP_ID,
        game_build=FIXTURE_BUILD,
        mode=OperatingMode.TV_DOCKED,
        render_gpu=FIXTURE_GPU,
        runtime=FIXTURE_RUNTIME,
        refresh_hz=60,
        profile=binding(),
        method=RenderMethod.FRAME_GENERATION,
        status=EvidenceStatus.VALIDATED,
        stable_base_fps=base,
        output_fps=base * multiplier,
        multiplier=multiplier,
        provider_id=LSFG_VK_PROVIDER_ID,
        provider_revision=LSFG_VK_REVISION,
        injection=InjectionEligibility.ELIGIBLE,
        requires_vrr=VrrState.OFF,
        base_limiter=LimiterState.UNRESOLVED,
        compared_against=("native-quality",),
        evidence_revision="fixture-evidence-1",
    )
    values.update(overrides)
    return CompatibilityRecord(**values)


def providers(**overrides) -> dict[str, ProviderState]:
    values = dict(
        provider_id=LSFG_VK_PROVIDER_ID,
        revision=LSFG_VK_REVISION,
        available=True,
        # Fixture only: which multipliers the pinned release supports is not
        # established by this prototype.
        supported_multipliers=(2,),
    )
    values.update(overrides)
    return {LSFG_VK_PROVIDER_ID: ProviderState(**values)}
