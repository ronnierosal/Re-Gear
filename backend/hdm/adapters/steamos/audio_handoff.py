"""Guarded PipeWire audio handoff for the exact Ally X + GPD G1 profile.

The adapter resolves ephemeral PipeWire object IDs from fresh properties on
every operation.  It never accepts a sink ID or name from Decky delivery.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Callable

from ...delivery.audio_state import NODE_NAME_RE, PortableAudioStateStore
from ...domain.control_plane import PlacementState
from .commands import PipeWireCommandRunner
from ..steamos.gamescope_user import GamescopeUserContext


PCI_BDF_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$")
MAX_DUMP_BYTES = PipeWireCommandRunner.MAX_OUTPUT_BYTES
VERIFY_ATTEMPTS = 5
VERIFY_INTERVAL_SECONDS = 0.1
AUDIO_READY_ATTEMPTS = 6
AUDIO_READY_INTERVAL_SECONDS = 0.25


@dataclass(frozen=True, slots=True)
class AudioSwitchReceipt:
    changed: bool
    previous_sink_name: str = ""
    created_portable_state: bool = False


@dataclass(frozen=True, slots=True)
class AudioHandoffResult:
    succeeded: bool
    code: str
    receipt: AudioSwitchReceipt | None = None


@dataclass(frozen=True, slots=True)
class AudioReadinessObservation:
    """Read-only evidence needed before a G1 audio handoff is attempted."""

    ready: bool
    code: str
    g1_sink_name: str = ""
    g1_sink_object_id: int = -1
    rollback_sink_name: str = ""
    default_sink_name: str = ""


@dataclass(frozen=True, slots=True)
class _Sink:
    object_id: int
    name: str
    device_bdf: str


@dataclass(frozen=True, slots=True)
class _PipeWireState:
    sinks: tuple[_Sink, ...]
    default_sink_name: str


class G1AudioReadiness:
    """Observe exact selectable and rollback sinks without changing PipeWire."""

    def __init__(
        self,
        *,
        commands: PipeWireCommandRunner,
        state: PortableAudioStateStore,
        resolve_g1_audio_bdf: Callable[[], str],
    ) -> None:
        self._commands = commands
        self._state = state
        self._resolve_g1_audio_bdf = resolve_g1_audio_bdf

    def observe(self, user: GamescopeUserContext) -> AudioReadinessObservation:
        return self._observe(user, before_display=False)

    def observe_before_display(self, user: GamescopeUserContext) -> AudioReadinessObservation:
        """Require rollback audio; an absent HDMI sink may await display activation."""
        return self._observe(user, before_display=True)

    def _observe(self, user: GamescopeUserContext, *, before_display: bool) -> AudioReadinessObservation:
        audio_bdf = _resolve_audio_bdf(self._resolve_g1_audio_bdf)
        if not audio_bdf:
            return AudioReadinessObservation(False, "audio.g1_identity_unverified")
        observed = _observe_pipewire(self._commands, user)
        if observed is None:
            return AudioReadinessObservation(False, "audio.observation_unavailable")
        external = tuple(
            item for item in observed.sinks if item.device_bdf == audio_bdf
        )
        if len(external) != 1 and not (before_display and not external):
            return AudioReadinessObservation(
                False,
                "audio.external_sink_ambiguous",
                default_sink_name=observed.default_sink_name,
            )
        wanted_name = self._state.load() or observed.default_sink_name
        rollback = tuple(item for item in observed.sinks if item.name == wanted_name)
        if len(rollback) != 1 or rollback[0].device_bdf == audio_bdf:
            return AudioReadinessObservation(
                False,
                "audio.rollback_sink_unavailable",
                g1_sink_name=external[0].name if external else "",
                g1_sink_object_id=external[0].object_id if external else -1,
                default_sink_name=observed.default_sink_name,
            )
        return AudioReadinessObservation(
            True,
            "audio.ready" if external else "audio.awaiting_display_activation",
            g1_sink_name=external[0].name if external else "",
            g1_sink_object_id=external[0].object_id if external else -1,
            rollback_sink_name=rollback[0].name,
            default_sink_name=observed.default_sink_name,
        )


class G1AudioHandoff:
    """Select and verify G1 HDMI audio, or restore the captured portable sink."""

    def __init__(
        self,
        *,
        commands: PipeWireCommandRunner,
        state: PortableAudioStateStore,
        resolve_g1_audio_bdf: Callable[[], str],
        wait: Callable[[float], None] = time.sleep,
        report_result: Callable[[PlacementState, AudioHandoffResult], None] | None = None,
        readiness_attempts: int = AUDIO_READY_ATTEMPTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(readiness_attempts) is not int or not 2 <= readiness_attempts <= 40:
            raise ValueError("audio readiness attempts must be between 2 and 40")
        self._readiness_attempts = readiness_attempts
        self._clock = clock
        self._commands = commands
        self._state = state
        self._resolve_g1_audio_bdf = resolve_g1_audio_bdf
        self._wait = wait
        self._report_result = report_result

    def prepare_docked(self, user: GamescopeUserContext) -> AudioHandoffResult:
        """Persist verified source audio before any display restart is queued."""
        ready = G1AudioReadiness(
            commands=self._commands, state=self._state,
            resolve_g1_audio_bdf=self._resolve_g1_audio_bdf,
        ).observe_before_display(user)
        if not ready.ready:
            return AudioHandoffResult(False, ready.code)
        try:
            self._state.save(ready.rollback_sink_name)
            if self._state.load() != ready.rollback_sink_name:
                return AudioHandoffResult(False, "audio.rollback_state_failed")
        except (OSError, ValueError):
            return AudioHandoffResult(False, "audio.rollback_state_failed")
        return AudioHandoffResult(True, "audio.rollback_prepared")

    def remember_portable(self, user: GamescopeUserContext) -> AudioHandoffResult:
        """Capture the current portable default before an eGPU attach occurs."""
        observed = self._observe(user)
        if observed is None:
            return AudioHandoffResult(False, "audio.observation_unavailable")
        current = tuple(
            item for item in observed.sinks if item.name == observed.default_sink_name
        )
        if len(current) != 1:
            return AudioHandoffResult(False, "audio.portable_sink_ambiguous")
        audio_bdf = self._resolve_bdf()
        if audio_bdf and current[0].device_bdf == audio_bdf:
            return AudioHandoffResult(False, "audio.portable_sink_is_egpu")
        try:
            self._state.save(current[0].name)
        except (OSError, ValueError):
            return AudioHandoffResult(False, "audio.rollback_state_failed")
        return AudioHandoffResult(True, "audio.portable_sink_recorded")

    def switch(
        self, target: PlacementState, user: GamescopeUserContext
    ) -> AudioHandoffResult:
        result = self._switch(target, user)
        if self._report_result is not None:
            try:
                self._report_result(target, result)
            except Exception:
                # Logging cannot change the outcome of an audio operation.
                pass
        return result

    def _switch(
        self, target: PlacementState, user: GamescopeUserContext
    ) -> AudioHandoffResult:
        if target is PlacementState.PORTABLE:
            before = self._observe(user)
            if before is None:
                return AudioHandoffResult(False, "audio.observation_unavailable")
            wanted_name = self._state.load()
            portable = tuple(
                item
                for item in before.sinks
                if item.name == wanted_name
            )
            if len(portable) != 1:
                return AudioHandoffResult(False, "audio.portable_sink_unavailable")
            audio_bdf = self._resolve_bdf()
            if audio_bdf and portable[0].device_bdf == audio_bdf:
                return AudioHandoffResult(False, "audio.portable_sink_is_egpu")
            return self._select(user, before, portable[0])

        if target not in {PlacementState.DOCKED_EGPU, PlacementState.DOCKED_IGPU}:
            return AudioHandoffResult(False, "audio.target_unsupported")
        audio_bdf = self._resolve_bdf()
        if not audio_bdf:
            return AudioHandoffResult(False, "audio.g1_identity_unverified")
        before, external, observed_any = self._wait_for_external_sink(user, audio_bdf)
        if before is None:
            return AudioHandoffResult(
                False,
                "audio.external_sink_ambiguous"
                if observed_any
                else "audio.observation_unavailable",
            )
        saved_name = self._state.load()
        if saved_name:
            saved = tuple(item for item in before.sinks if item.name == saved_name)
            if len(saved) != 1 or saved[0].device_bdf == audio_bdf:
                return AudioHandoffResult(False, "audio.rollback_sink_unavailable")
        if before.default_sink_name == external[0].name:
            if not saved_name:
                return AudioHandoffResult(False, "audio.rollback_sink_unavailable")
            return AudioHandoffResult(
                True, "audio.already_selected", AudioSwitchReceipt(False)
            )
        previous = tuple(
            item for item in before.sinks if item.name == before.default_sink_name
        )
        if len(previous) != 1 or previous[0].device_bdf == audio_bdf:
            return AudioHandoffResult(False, "audio.rollback_sink_unavailable")
        created = not bool(saved_name)
        try:
            if created:
                self._state.save(previous[0].name)
        except (OSError, ValueError):
            return AudioHandoffResult(False, "audio.rollback_state_failed")
        return self._select(
            user,
            before,
            external[0],
            previous_sink=previous[0].name,
            created_portable_state=created,
        )

    def _wait_for_external_sink(
        self, user: GamescopeUserContext, audio_bdf: str
    ) -> tuple[_PipeWireState | None, tuple[_Sink, ...], bool]:
        """Require two matching exact observations before changing audio."""
        prior: tuple[str, int] | None = None
        observed_any = False
        deadline = self._clock() + 10.0
        for attempt in range(self._readiness_attempts):
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            observed = self._observe(user, timeout_seconds=remaining)
            if self._clock() >= deadline:
                break
            observed_any = observed_any or observed is not None
            external = (
                tuple(item for item in observed.sinks if item.device_bdf == audio_bdf)
                if observed is not None
                else ()
            )
            current = (
                (external[0].name, external[0].object_id)
                if len(external) == 1
                else None
            )
            if current is not None and current == prior:
                return observed, external, True
            prior = current
            if attempt + 1 < self._readiness_attempts:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    break
                self._wait(min(AUDIO_READY_INTERVAL_SECONDS, remaining))
        return None, (), observed_any

    def rollback(
        self, receipt: AudioSwitchReceipt | None, user: GamescopeUserContext
    ) -> bool:
        if receipt is None or not receipt.changed or not receipt.previous_sink_name:
            return True
        observed = self._observe(user)
        if observed is None:
            return False
        matches = tuple(
            item for item in observed.sinks if item.name == receipt.previous_sink_name
        )
        if (
            len(matches) != 1
            or not self._commands.set_default(user, matches[0].object_id).ok
        ):
            return False
        if not self._verify_default(user, receipt.previous_sink_name):
            return False
        if receipt.created_portable_state:
            self._state.clear()
        return True

    def _select(
        self,
        user: GamescopeUserContext,
        before: _PipeWireState,
        target: _Sink,
        *,
        previous_sink: str = "",
        created_portable_state: bool = False,
    ) -> AudioHandoffResult:
        if before.default_sink_name == target.name:
            return AudioHandoffResult(
                True, "audio.already_selected", AudioSwitchReceipt(False)
            )
        if not self._commands.set_default(user, target.object_id).ok:
            return AudioHandoffResult(False, "audio.set_default_failed")
        if not self._verify_default(user, target.name):
            return AudioHandoffResult(False, "audio.verification_failed")
        return AudioHandoffResult(
            True,
            "audio.default_verified",
            AudioSwitchReceipt(
                True,
                previous_sink or before.default_sink_name,
                created_portable_state,
            ),
        )

    def _verify_default(self, user: GamescopeUserContext, expected: str) -> bool:
        for attempt in range(VERIFY_ATTEMPTS):
            observed = self._observe(user)
            if observed is not None and observed.default_sink_name == expected:
                return True
            if attempt + 1 < VERIFY_ATTEMPTS:
                self._wait(VERIFY_INTERVAL_SECONDS)
        return False

    def _resolve_bdf(self) -> str:
        return _resolve_audio_bdf(self._resolve_g1_audio_bdf)

    def _observe(self, user: GamescopeUserContext, *, timeout_seconds: float | None = None) -> _PipeWireState | None:
        return _observe_pipewire(self._commands, user, timeout_seconds=timeout_seconds)


def _resolve_audio_bdf(resolve: Callable[[], str]) -> str:
    try:
        value = resolve().lower()
    except Exception:
        return ""
    return value if PCI_BDF_RE.fullmatch(value) else ""


def _observe_pipewire(
    commands: PipeWireCommandRunner, user: GamescopeUserContext,
    *, timeout_seconds: float | None = None,
) -> _PipeWireState | None:
    result = commands.dump(user) if timeout_seconds is None else commands.dump(user, timeout_seconds=timeout_seconds)
    if not result.ok or not result.output or len(result.output) > MAX_DUMP_BYTES:
        return None
    try:
        values = json.loads(result.output)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(values, list):
        return None
    devices: dict[int, str] = {}
    default_sink_name = ""
    raw_nodes: list[tuple[int, str, int]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        object_id = value.get("id")
        info = value.get("info")
        props = info.get("props", {}) if isinstance(info, dict) else {}
        if value.get("type") == "PipeWire:Interface:Device" and isinstance(
            object_id, int
        ):
            bus_path = props.get("device.bus-path", "")
            if isinstance(bus_path, str) and bus_path.startswith("pci-"):
                candidate = bus_path.removeprefix("pci-").lower()
                if PCI_BDF_RE.fullmatch(candidate):
                    devices[object_id] = candidate
        elif value.get("type") == "PipeWire:Interface:Node" and isinstance(
            object_id, int
        ):
            name = props.get("node.name", "")
            device_id = props.get("device.id")
            if (
                props.get("media.class") == "Audio/Sink"
                and props.get("alsa.loopback") is True
                and isinstance(name, str)
                and NODE_NAME_RE.fullmatch(name)
                and isinstance(device_id, int)
            ):
                raw_nodes.append((object_id, name, device_id))
        elif value.get("type") == "PipeWire:Interface:Metadata":
            metadata = value.get("metadata", ())
            if not isinstance(metadata, list):
                continue
            for entry in metadata:
                if (
                    not isinstance(entry, dict)
                    or entry.get("key") != "default.audio.sink"
                ):
                    continue
                configured = entry.get("value")
                name = (
                    configured.get("name", "")
                    if isinstance(configured, dict)
                    else ""
                )
                if isinstance(name, str) and NODE_NAME_RE.fullmatch(name):
                    if default_sink_name and default_sink_name != name:
                        return None
                    default_sink_name = name
    sinks = tuple(
        _Sink(object_id, name, devices[device_id])
        for object_id, name, device_id in raw_nodes
        if device_id in devices
    )
    if not default_sink_name:
        return None
    if len(tuple(item for item in sinks if item.name == default_sink_name)) != 1:
        return None
    return _PipeWireState(sinks, default_sink_name)
