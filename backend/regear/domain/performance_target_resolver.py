"""Resolve a player's performance target into one validated rendering choice.

The player asks for an experience -- "60 FPS" -- and Re-Gear decides how to get
there, in a fixed order: native rendering, then validated upscaling, then
eligible frame generation (FG). If nothing reaches the target, the highest
validated lower target is chosen when the player allows it; otherwise Advisor.
Generated presentation frames are never evidence of base rate or input
responsiveness, so FG is always the last resort and never the default.

Everything here is pure and deterministic. The resolver reads no hardware,
probes no provider, discovers no files and runs nothing. It is handed the
intent, the context and the evidence, and it answers with a decision.

Two rules shape it more than any other.

**No number is invented.** There is no default base rate, no universal
"30 FPS is enough", no assumed multiplier. Every figure in a decision comes
from a versioned compatibility record that was measured for this exact game,
build, runtime, placement, GPU and display. A record measured anywhere else is
not evidence here; it is stale, and it is rejected with a reason.

**Frame generation must earn its place.** A native or upscaled option that
falls short of the target does not automatically hand over to FG. FG is chosen
over a validated simpler option only when its own record declares that it was
compared against that option. Otherwise the simpler option is kept and the
shortfall is stated honestly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from .graphics_game_adapter import GameSettingsAdapter
from .graphics_profiles import SUPPORTED_MODES, GraphicsProfile
from .mode_profiles import ExperienceTarget
from .models import GameState, OperatingMode
from .semantic_profiles import Resolution, UpscalingMode


INTENT_SCHEMA_VERSION = 1
EVIDENCE_RECORD_VERSION = 2
MAX_FPS = 1000


class RenderMethod(StrEnum):
    NATIVE = "native"
    UPSCALED = "upscaled"
    FRAME_GENERATION = "frame_generation"


#: The fixed precedence. Lower is preferred.
METHOD_RANK = {
    RenderMethod.NATIVE: 0,
    RenderMethod.UPSCALED: 1,
    RenderMethod.FRAME_GENERATION: 2,
}


class EvidenceStatus(StrEnum):
    THEORETICAL = "theoretical"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    EXPERIMENTAL = "experimental"
    VALIDATED = "validated"


class ProviderKind(StrEnum):
    NATIVE_GAME = "native_game"
    EXTERNAL = "external"


class ScalingLocation(StrEnum):
    GAME = "game"
    COMPOSITOR = "compositor"


@dataclass(frozen=True, slots=True)
class UpscalingChoice:
    provider_id: str
    mode: UpscalingMode
    location: ScalingLocation = ScalingLocation.GAME

    def __post_init__(self) -> None:
        if not self.provider_id or self.mode not in (
            UpscalingMode.QUALITY, UpscalingMode.BALANCED, UpscalingMode.PERFORMANCE
        ) or not isinstance(self.location, ScalingLocation):
            raise ValueError("an upscaler needs a provider, concrete mode and location")


class InjectionEligibility(StrEnum):
    """Whether an external in-process provider may be used with this game.

    UNKNOWN is not permission. Proton support does not grant it, and the
    absence of a crash or ban during one run does not establish it.
    """

    UNKNOWN = "unknown"
    INELIGIBLE = "ineligible"
    ELIGIBLE = "eligible"


class VrrState(StrEnum):
    ON = "on"
    OFF = "off"
    UNKNOWN = "unknown"


class FrameGenerationPolicy(StrEnum):
    AUTO = "auto"
    OFF = "off"


class LimiterState(StrEnum):
    """Whether the base-rate limiter's owner and placement are established.

    Limiting the game's real rendering to 30 is not the same as capping the
    post-FG compositor to 30, and this milestone does not decide which owner
    applies it. UNRESOLVED is carried forward into the plan as an unresolved
    requirement; it is never quietly treated as satisfied.
    """

    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"


class Outcome(StrEnum):
    NATIVE = "performance.native"
    UPSCALED = "performance.upscaled"
    FRAME_GENERATION = "performance.frame_generation"
    LOWER_TARGET = "performance.lower_target"
    ADVISOR = "performance.advisor"
    DEFERRED = "performance.deferred"


METHOD_OUTCOME = {
    RenderMethod.NATIVE: Outcome.NATIVE,
    RenderMethod.UPSCALED: Outcome.UPSCALED,
    RenderMethod.FRAME_GENERATION: Outcome.FRAME_GENERATION,
}


def _positive(value: int | None, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or not 0 < value <= MAX_FPS:
        raise ValueError(f"{name} must be a positive frame rate")


@dataclass(frozen=True, slots=True)
class PerformanceIntent:
    """What the player asked for. Nothing here is a measured fact."""

    requested_fps: int
    fg_policy: FrameGenerationPolicy = FrameGenerationPolicy.AUTO
    #: The player's own floor for real frames, if they set one. No default.
    minimum_base_fps: int | None = None
    allow_lower_target: bool = True
    schema_version: int = INTENT_SCHEMA_VERSION
    provider_priority: tuple[str, ...] = ()
    upscaling_allowed: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != INTENT_SCHEMA_VERSION:
            raise ValueError("performance intent schema version is not supported")
        _positive(self.requested_fps, "requested FPS")
        if self.requested_fps is None:
            raise ValueError("requested FPS is required")
        _positive(self.minimum_base_fps, "minimum base FPS")
        if len(set(self.provider_priority)) != len(self.provider_priority):
            raise ValueError("provider priority cannot contain duplicates")


@dataclass(frozen=True, slots=True)
class PresentationContext:
    """The exact situation a decision is for. Supplied, never discovered.

    Rendering GPU and display owner are separate facts: an eGPU can render
    while the internal panel presents, and neither implies the other.
    """

    steam_app_id: str
    game_build: str
    mode: OperatingMode
    render_gpu: str | None
    display_owner: str | None
    runtime: str
    refresh_hz: int | None
    vrr: VrrState = VrrState.UNKNOWN
    output_resolution: Resolution | None = None
    vrr_range: tuple[int, int] | None = None
    capabilities: frozenset[str] = frozenset()
    presentation_stack: str = ""

    def __post_init__(self) -> None:
        _positive(self.refresh_hz, "refresh rate")
        if self.vrr_range is not None:
            low, high = self.vrr_range
            _positive(low, "VRR minimum")
            _positive(high, "VRR maximum")
            if low > high:
                raise ValueError("VRR range is reversed")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))


@dataclass(frozen=True, slots=True)
class ProfileBinding:
    """Which existing adapter profile a measurement was taken under.

    This is how the resolver composes with the accepted graphics-profile
    foundation instead of competing with it: evidence names the adapter, the
    experience target and the profile/schema versions it was measured with,
    and the adapter -- not this module -- still owns the game's keys.
    """

    adapter_id: str
    target: ExperienceTarget
    profile_version: int
    schema_id: str


@dataclass(frozen=True, slots=True)
class CompatibilityRecord:
    """One measured, versioned result for one exact context."""

    record_id: str
    steam_app_id: str
    game_build: str
    mode: OperatingMode
    render_gpu: str
    runtime: str
    refresh_hz: int | None
    profile: ProfileBinding
    method: RenderMethod
    status: EvidenceStatus
    #: Sustained real frame rate *with any FG overhead included*.
    stable_base_fps: int
    output_fps: int
    evidence_revision: str
    multiplier: int = 1
    provider_id: str | None = None
    provider_revision: str | None = None
    injection: InjectionEligibility = InjectionEligibility.UNKNOWN
    #: A VRR requirement proven for this record, or None if none applies.
    requires_vrr: VrrState | None = None
    base_limiter: LimiterState = LimiterState.UNRESOLVED
    #: Simpler records this FG result was explicitly compared against.
    compared_against: tuple[str, ...] = ()
    #: A per-game floor established by this evidence, if any.
    minimum_base_fps: int | None = None
    record_version: int = EVIDENCE_RECORD_VERSION
    #: The game's swapchain output, separately observed from internal render
    #: and the physical display output. Required by the engine preview bridge.
    game_output_resolution: Resolution | None = None
    render_resolution: Resolution | None = None
    output_resolution: Resolution | None = None
    display_owner: str | None = None
    presentation_stack: str = ""
    upscalers: tuple[UpscalingChoice, ...] = ()
    provider_kind: ProviderKind = ProviderKind.EXTERNAL
    required_capabilities: frozenset[str] = frozenset()
    required_vrr_range: tuple[int, int] | None = None
    stable: bool = True
    quality_acceptable: bool = True

    def __post_init__(self) -> None:
        if not self.record_id or not self.evidence_revision:
            raise ValueError("a compatibility record needs an id and an evidence revision")
        _positive(self.stable_base_fps, "stable base FPS")
        if self.stable_base_fps is None or self.output_fps is None:
            raise ValueError("base and output frame rates are required")
        _positive(self.output_fps, "output FPS")
        _positive(self.refresh_hz, "refresh rate")
        _positive(self.minimum_base_fps, "minimum base FPS")
        if not isinstance(self.multiplier, int) or isinstance(self.multiplier, bool):
            raise ValueError("multiplier must be an integer")
        object.__setattr__(self, "upscalers", tuple(self.upscalers))
        object.__setattr__(self, "required_capabilities", frozenset(self.required_capabilities))
        if self.method is RenderMethod.FRAME_GENERATION:
            if self.multiplier < 2:
                raise ValueError("a frame-generation record needs a multiplier of at least 2")
            if self.output_fps != self.stable_base_fps * self.multiplier:
                raise ValueError("frame-generation output must be base multiplied exactly")
            if not self.provider_id or not self.provider_revision:
                raise ValueError("a frame-generation record must name its provider revision")
        else:
            if self.multiplier != 1:
                raise ValueError("only frame generation has a multiplier")
            if self.output_fps != self.stable_base_fps:
                raise ValueError("without frame generation, output is the real frame rate")
            if self.provider_id is not None:
                raise ValueError("native and upscaled records do not name an external provider")


@dataclass(frozen=True, slots=True)
class ProviderState:
    """What the caller established about one provider. Injected, not probed.

    ``available`` says the provider is present in the right place. It is never
    permission to write files or to execute anything.
    """

    provider_id: str
    revision: str
    available: bool
    reason: str = ""
    supported_multipliers: tuple[int, ...] = ()
    kind: ProviderKind = ProviderKind.EXTERNAL
    requires_refresh_match: bool = True


@dataclass(frozen=True, slots=True)
class Decision:
    outcome: Outcome
    requested_fps: int
    achievable_fps: int | None = None
    record: CompatibilityRecord | None = None
    #: Measured preset only; PerformancePlan supplies the final cap/resolution.
    #: Never apply this raw preset independently of the provider plan.
    profile: GraphicsProfile | None = None
    required_stable_base_fps: int | None = None
    multiplier: int = 1
    reasons: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    rejected: tuple[tuple[str, str], ...] = ()
    next_launch: bool = False

    @property
    def method(self) -> RenderMethod | None:
        return self.record.method if self.record is not None else None


@dataclass(frozen=True, slots=True)
class _Screen:
    accepted: tuple[CompatibilityRecord, ...] = ()
    rejected: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def resolve(
    intent: PerformanceIntent,
    context: PresentationContext,
    game_state: GameState,
    adapter: GameSettingsAdapter | None,
    records: tuple[CompatibilityRecord, ...],
    providers: Mapping[str, ProviderState],
) -> Decision:
    """Choose one rendering method for this intent in this exact context."""
    requested = intent.requested_fps

    # A running or ambiguous game is never reconfigured underneath itself, and
    # a plan computed now would be stale by the next launch. Keep only the
    # intent; resolve again against fresh context when the game is next idle.
    if game_state is not GameState.IDLE:
        return Decision(
            Outcome.DEFERRED,
            requested,
            reasons=(
                f"game state is {game_state.value}; the request is kept for the "
                "next launch and resolved again then, not planned now",
            ),
            next_launch=True,
        )
    if context.mode not in SUPPORTED_MODES:
        return Decision(
            Outcome.ADVISOR,
            requested,
            reasons=(f"placement {context.mode.value} selects no automatic change",),
        )
    if context.render_gpu is None:
        return Decision(
            Outcome.ADVISOR,
            requested,
            reasons=("the rendering GPU is not identified, so no evidence can match",),
        )
    if adapter is None or not adapter.serves(context.steam_app_id):
        return Decision(
            Outcome.ADVISOR,
            requested,
            reasons=("no game adapter serves this AppID",),
        )

    target = min(requested, context.refresh_hz) if context.refresh_hz else requested

    screen = _screen(intent, context, adapter, records, providers)
    accepted = screen.accepted
    rejected = list(screen.rejected)

    simple = sorted(
        (r for r in accepted if r.method is not RenderMethod.FRAME_GENERATION),
        key=lambda r: (METHOD_RANK[r.method], r.record_id),
    )
    for record in simple:
        if record.output_fps >= target:
            return _decided(record, adapter, context, requested, target, rejected)

    # Nothing simpler reaches the target. FG may, but only where its record
    # was explicitly compared against every simpler validated option here.
    best_simple = _best_lower(simple, target)
    priority = {name: index for index, name in enumerate(intent.provider_priority)}
    for record in sorted(
        (r for r in accepted if r.method is RenderMethod.FRAME_GENERATION),
        key=lambda r: (priority.get(r.provider_id, len(priority)), r.record_id),
    ):
        if record.output_fps != target:
            rejected.append((record.record_id, "frame-generation output does not equal the target"))
            continue
        missing = [r.record_id for r in simple if r.record_id not in record.compared_against]
        if missing:
            rejected.append(
                (
                    record.record_id,
                    "no declared comparison against simpler validated option(s) "
                    + ", ".join(missing),
                )
            )
            continue
        if target < requested and not intent.allow_lower_target:
            continue
        return _decided(record, adapter, context, requested, target, rejected)

    if best_simple is not None and intent.allow_lower_target:
        decision = _decided(
            best_simple, adapter, context, requested, best_simple.output_fps, rejected
        )
        return Decision(
            Outcome.LOWER_TARGET,
            requested,
            achievable_fps=best_simple.output_fps,
            record=best_simple,
            profile=decision.profile,
            required_stable_base_fps=best_simple.stable_base_fps,
            reasons=(
                f"{requested} FPS is not reachable with validated evidence here; "
                f"the highest validated result is {best_simple.output_fps} FPS "
                f"({best_simple.method.value})",
            ),
            rejected=tuple(rejected),
        )
    reasons = ["no validated option for this exact context reaches the target"]
    if best_simple is not None:
        reasons.append("a lower validated target exists but the player did not allow one")
    return Decision(
        Outcome.ADVISOR, requested, reasons=tuple(reasons), rejected=tuple(rejected)
    )


def _best_lower(
    simple: list[CompatibilityRecord], requested: int
) -> CompatibilityRecord | None:
    lower = [r for r in simple if r.output_fps < requested]
    if not lower:
        return None
    return sorted(lower, key=lambda r: (-r.output_fps, METHOD_RANK[r.method], r.record_id))[0]


def _decided(
    record: CompatibilityRecord,
    adapter: GameSettingsAdapter,
    context: PresentationContext,
    requested: int,
    achievable: int,
    rejected: list[tuple[str, str]],
) -> Decision:
    profile = adapter.profile_for(context.steam_app_id, context.mode, record.profile.target)
    unresolved: list[str] = []
    if record.method is RenderMethod.FRAME_GENERATION:
        if record.base_limiter is LimiterState.UNRESOLVED:
            unresolved.append(
                "base_limiter: the owner and placement of the "
                f"{record.stable_base_fps} FPS real-frame cap are not established"
            )
        if record.provider_kind is ProviderKind.EXTERNAL:
            unresolved.append(
                "provider_initialization_failure: recovery after in-process layer "
                "failure is an unmet production gate; a preflight fallback cannot "
                "catch a failure that happens inside the running game"
            )
    return Decision(
        Outcome.LOWER_TARGET if achievable < requested else METHOD_OUTCOME[record.method],
        requested,
        achievable_fps=achievable,
        record=record,
        profile=profile,
        required_stable_base_fps=achievable // record.multiplier,
        multiplier=record.multiplier,
        unresolved=tuple(unresolved),
        reasons=(f"requested {requested}; planned {achievable} presentation FPS",),
        rejected=tuple(rejected),
    )


def _screen(
    intent: PerformanceIntent,
    context: PresentationContext,
    adapter: GameSettingsAdapter,
    records: tuple[CompatibilityRecord, ...],
    providers: Mapping[str, ProviderState],
) -> _Screen:
    accepted: list[CompatibilityRecord] = []
    rejected: list[tuple[str, str]] = []
    counts: dict[str, int] = {}
    for record in records:
        counts[record.record_id] = counts.get(record.record_id, 0) + 1
    for record in sorted(records, key=lambda r: r.record_id):
        if counts[record.record_id] != 1:
            rejected.append((record.record_id, "ambiguous duplicate evidence identity"))
            continue
        reason = _rejection(intent, context, adapter, record, providers)
        if reason is None:
            accepted.append(record)
        else:
            rejected.append((record.record_id, reason))
    return _Screen(tuple(accepted), tuple(rejected))


def _rejection(
    intent: PerformanceIntent,
    context: PresentationContext,
    adapter: GameSettingsAdapter,
    record: CompatibilityRecord,
    providers: Mapping[str, ProviderState],
) -> str | None:
    """Why this record is not evidence for this context, or None if it is."""
    if record.record_version != EVIDENCE_RECORD_VERSION:
        return "evidence record version is not one this build understands"
    if not record.stable or not record.quality_acceptable:
        return "base stability or latency/artifact/pacing acceptance is not established"
    if record.output_resolution != context.output_resolution:
        return "measured at another display output resolution"
    if record.display_owner != context.display_owner:
        return "measured on another display owner"
    if record.presentation_stack != context.presentation_stack:
        return "measured with another compositor/overlay/limiter stack"
    if not record.required_capabilities <= context.capabilities:
        return "required GPU/runtime capabilities are unavailable"
    if record.required_vrr_range is not None and record.required_vrr_range != context.vrr_range:
        return "required VRR range is not established"
    if record.requires_vrr is not None and context.vrr is not record.requires_vrr:
        return f"requires VRR {record.requires_vrr.value}"
    planned = min(intent.requested_fps, context.refresh_hz or intent.requested_fps,
                  record.output_fps)
    if record.requires_vrr is VrrState.ON and context.vrr_range is not None:
        if not context.vrr_range[0] <= planned <= context.vrr_range[1]:
            return "planned rate is outside the validated VRR range; LFC is not assumed"
    if len(record.upscalers) > 1:
        return "conflicting scaling technologies; only one upscaler may be selected"
    if record.upscalers and not intent.upscaling_allowed:
        return "the player turned upscaling off"
    if record.method is RenderMethod.NATIVE and record.upscalers:
        return "native rendering cannot also enable an upscaler"
    if record.method is RenderMethod.UPSCALED and not record.upscalers:
        return "upscaled evidence must name its upscaler"
    if context.refresh_hz and context.refresh_hz < intent.requested_fps and not intent.allow_lower_target:
        return "display refresh is below the requested target and lower targets are disabled"
    if record.steam_app_id != context.steam_app_id:
        return "evidence is for another game"
    # A record measured anywhere else is stale here, never "close enough".
    if record.game_build != context.game_build:
        return "stale: measured on another game build"
    if record.runtime != context.runtime:
        return "stale: measured on another runtime/driver"
    if record.mode is not context.mode:
        return "measured in another placement"
    if record.render_gpu != context.render_gpu:
        return "measured on another rendering GPU"
    if record.refresh_hz is not None and record.refresh_hz != context.refresh_hz:
        return "measured at another refresh rate"
    if record.status is EvidenceStatus.EXPERIMENTAL:
        return "experimental evidence is never selected automatically"
    if record.status is not EvidenceStatus.VALIDATED:
        return f"evidence status is {record.status.value}"
    binding = record.profile
    if binding.adapter_id != adapter.adapter_id:
        return "measured under another game adapter"
    profile = adapter.profile_for(context.steam_app_id, context.mode, binding.target)
    if profile is None:
        return f"the adapter declares no {binding.target.value} profile for this placement"
    if (
        profile.profile_version != binding.profile_version
        or profile.schema_id != binding.schema_id
    ):
        return "stale: measured under another profile or schema version"
    floor = max(
        value
        for value in (intent.minimum_base_fps, record.minimum_base_fps, 1)
        if value is not None
    )
    if record.stable_base_fps < floor:
        return f"stable base {record.stable_base_fps} FPS is below the floor of {floor}"
    if record.method is not RenderMethod.FRAME_GENERATION:
        if planned < floor:
            return "planned base cap would be below the required floor"
        return None

    if intent.fg_policy is FrameGenerationPolicy.OFF:
        return "the player turned frame generation off"
    provider = providers.get(record.provider_id or "")
    if provider is None or not provider.available:
        detail = provider.reason if provider is not None and provider.reason else "not available"
        return f"provider {record.provider_id} is {detail}"
    if provider.revision != record.provider_revision:
        return "stale: measured with another provider revision"
    if provider.provider_id != record.provider_id or provider.kind is not record.provider_kind:
        return "provider identity or kind does not match the evidence"
    if record.multiplier not in provider.supported_multipliers:
        return f"multiplier {record.multiplier}x is not supported by this provider revision"
    if provider.kind is ProviderKind.EXTERNAL and record.injection is InjectionEligibility.UNKNOWN:
        return "external-injection eligibility (anti-cheat) is unknown"
    if provider.kind is ProviderKind.EXTERNAL and record.injection is InjectionEligibility.INELIGIBLE:
        return "this game is ineligible for external injection"
    # Vsync pacing needs presented output to match the display's refresh. A
    # 60 FPS plan on a 120 Hz panel is not admitted merely because 60 <= 120,
    # and refresh is never changed to make a provider eligible.
    if context.refresh_hz is None:
        return "display refresh is unknown, so presentation pacing cannot be admitted"
    if record.output_fps > context.refresh_hz or (provider.requires_refresh_match and record.output_fps != context.refresh_hz):
        return (
            f"output {record.output_fps} FPS does not match the {context.refresh_hz} Hz "
            "display; refresh is not changed to make a provider eligible"
        )
    if record.requires_vrr is not None and context.vrr is not record.requires_vrr:
        return (
            f"requires VRR {record.requires_vrr.value}, but the display reports "
            f"{context.vrr.value}"
        )
    return None
