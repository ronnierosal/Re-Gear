"""Bounded read-only controller and audio inventory from sysfs.

This module observes only. It does not open input devices, invoke PipeWire,
change the default output, manipulate Steam Input, or retain raw paths/names.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ...domain.peripheral_handoff import (
    AudioOutput,
    AudioPeripheralState,
    ControllerPeripheralState,
    PeripheralIdentityHints,
    PeripheralMappingEvidence,
    PeripheralObservation,
)


EVENT_PATTERN = re.compile(r"event[0-9]+$")
CARD_PATTERN = re.compile(r"card[0-9]+$")
BTN_GAMEPAD = 0x130


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _opaque_binding(prefix: str, path: Path) -> str:
    try:
        value = str(path.resolve(strict=True))
    except OSError:
        value = str(path)
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:32]}"


def _bitmap_has(value: str, bit: int) -> bool:
    try:
        return bool(int("".join(value.split()), 16) & (1 << bit))
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class PeripheralInventory:
    controller_complete: bool
    controller_bindings: tuple[str, ...] = field(default_factory=tuple)
    controller_error: str = ""
    audio_complete: bool = False
    audio_bindings: tuple[str, ...] = field(default_factory=tuple)
    audio_error: str = ""


class SteamOsPeripheralInventory:
    def __init__(
        self,
        *,
        input_root: Path = Path("/sys/class/input"),
        sound_root: Path = Path("/sys/class/sound"),
    ) -> None:
        self._input_root = input_root
        self._sound_root = sound_root

    def scan(self) -> PeripheralInventory:
        controller_complete, controllers, controller_error = self._controllers()
        audio_complete, audio, audio_error = self._audio()
        return PeripheralInventory(
            controller_complete,
            controllers,
            controller_error,
            audio_complete,
            audio,
            audio_error,
        )

    def _controllers(self) -> tuple[bool, tuple[str, ...], str]:
        try:
            entries = tuple(self._input_root.iterdir())
        except OSError:
            return False, (), "controller.input_root_unreadable"
        bindings: list[str] = []
        for event in sorted(entries, key=lambda item: item.name):
            if not EVENT_PATTERN.fullmatch(event.name):
                continue
            key = _read_text(event / "device" / "capabilities" / "key")
            if key is None:
                return False, (), "controller.capabilities_unreadable"
            if _bitmap_has(key, BTN_GAMEPAD):
                bindings.append(_opaque_binding("controller", event / "device"))
        return True, tuple(sorted(set(bindings))), ""

    def _audio(self) -> tuple[bool, tuple[str, ...], str]:
        try:
            entries = tuple(self._sound_root.iterdir())
        except OSError:
            return False, (), "audio.sound_root_unreadable"
        bindings = [
            _opaque_binding("audio", entry / "device")
            for entry in sorted(entries, key=lambda item: item.name)
            if CARD_PATTERN.fullmatch(entry.name)
        ]
        return True, tuple(sorted(set(bindings))), ""


class SteamOsPeripheralObservationAdapter:
    """Map inventory through explicit private hints; unknown mappings fail closed."""

    def __init__(
        self,
        inventory: SteamOsPeripheralInventory | None = None,
        mapping: PeripheralMappingEvidence | None = None,
        *,
        generation_factory=None,
        sample_factory=None,
    ) -> None:
        self._inventory = inventory or SteamOsPeripheralInventory()
        self._mapping = mapping
        self._generation_factory = generation_factory
        self._sample_factory = sample_factory
        self._sample_counter = 0

    def observe(self) -> PeripheralObservation:
        inventory = self._inventory.scan()
        hints, mapping_error = self._hints_for(inventory)
        controller = self._controller(inventory, hints, mapping_error)
        audio = self._audio(inventory, hints, mapping_error)
        generation = (
            self._generation_factory()
            if self._generation_factory is not None
            else self._generation(inventory, controller, audio)
        )
        self._sample_counter += 1
        sample = (
            self._sample_factory()
            if self._sample_factory is not None
            else hashlib.sha256(
                f"{generation}|sample:{self._sample_counter}".encode("ascii")
            ).hexdigest()
        )
        return PeripheralObservation(
            schema_version=1,
            generation=generation,
            sample_id=sample,
            controller=controller,
            audio=audio,
        )

    @staticmethod
    def inventory_generation(inventory: PeripheralInventory) -> str:
        """Return the opaque semantic inventory identity for mapping evidence."""
        material = {
            "controller_complete": inventory.controller_complete,
            "controller_bindings": inventory.controller_bindings,
            "controller_error": inventory.controller_error,
            "audio_complete": inventory.audio_complete,
            "audio_bindings": inventory.audio_bindings,
            "audio_error": inventory.audio_error,
        }
        return hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _hints_for(
        self, inventory: PeripheralInventory
    ) -> tuple[PeripheralIdentityHints, str]:
        mapping = self._mapping
        if mapping is None:
            return PeripheralIdentityHints(), ""
        if mapping.inventory_generation != self.inventory_generation(inventory):
            return PeripheralIdentityHints(), "peripheral.mapping_stale"
        return mapping.hints, ""

    @staticmethod
    def _generation(
        inventory: PeripheralInventory,
        controller: ControllerPeripheralState,
        audio: AudioPeripheralState,
    ) -> str:
        semantic = {
            "inventory": {
                "controller_complete": inventory.controller_complete,
                "controller_bindings": inventory.controller_bindings,
                "controller_error": inventory.controller_error,
                "audio_complete": inventory.audio_complete,
                "audio_bindings": inventory.audio_bindings,
                "audio_error": inventory.audio_error,
            },
            "controller": {
                "complete": controller.complete,
                "exact": controller.exact,
                "failure": controller.failure_code,
                "builtin": controller.builtin_binding,
                "builtin_available": controller.builtin_available,
                "external": controller.external_binding,
                "external_connected": controller.external_connected,
            },
            "audio": {
                "complete": audio.complete,
                "exact": audio.exact,
                "failure": audio.failure_code,
                "current": audio.current_output.value,
                "current_binding": audio.current_output_binding,
                "external": audio.external_output_binding,
                "external_available": audio.external_output_available,
                "portable": audio.portable_output_binding,
                "portable_available": audio.portable_output_available,
            },
        }
        return hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _controller(
        self,
        inventory: PeripheralInventory,
        hints: PeripheralIdentityHints,
        mapping_error: str,
    ) -> ControllerPeripheralState:
        if not inventory.controller_complete:
            return ControllerPeripheralState(
                False, False, inventory.controller_error, "", None, False, False, "", None, False
            )
        known = {value for value in (hints.builtin_controller_binding, hints.external_controller_binding) if value}
        if mapping_error or not hints.builtin_controller_binding or set(inventory.controller_bindings) != known:
            return ControllerPeripheralState(
                True, False, mapping_error or "controller.identity_unmapped", "", None, False, False, "", None, False
            )
        return ControllerPeripheralState(
            True,
            True,
            "",
            hints.builtin_controller_binding,
            True,
            False,
            False,
            hints.external_controller_binding,
            bool(hints.external_controller_binding),
            False,
        )

    def _audio(
        self,
        inventory: PeripheralInventory,
        hints: PeripheralIdentityHints,
        mapping_error: str,
    ) -> AudioPeripheralState:
        if not inventory.audio_complete:
            return AudioPeripheralState(
                False, False, inventory.audio_error, AudioOutput.UNKNOWN, "", False, "", None, False, "", None, False, False
            )
        known = {
            value
            for value in (
                hints.current_audio_binding,
                hints.external_audio_binding,
                hints.portable_audio_binding,
            )
            if value
        }
        if mapping_error or not known or not set(inventory.audio_bindings).issuperset(known):
            return AudioPeripheralState(
                True, False, mapping_error or "audio.identity_unmapped", AudioOutput.UNKNOWN, "", False, "", None, False, "", None, False, False
            )
        return AudioPeripheralState(
            True,
            False,
            "audio.default_output_unobserved",
            AudioOutput.UNKNOWN,
            hints.current_audio_binding,
            False,
            hints.external_audio_binding,
            bool(hints.external_audio_binding),
            False,
            hints.portable_audio_binding,
            bool(hints.portable_audio_binding),
            False,
            False,
        )


def peripheral_status_to_public_payload(
    observed: PeripheralObservation,
) -> dict[str, object]:
    """Expose only categorical readiness; bindings and generations stay private."""
    return {
        "schema_version": 1,
        "controller": {
            "complete": observed.controller.complete,
            "exact": observed.controller.exact,
            "builtin_available": observed.controller.builtin_available,
            "external_connected": observed.controller.external_connected,
            "code": observed.controller.failure_code or "controller.observed",
        },
        "audio": {
            "complete": observed.audio.complete,
            "exact": observed.audio.exact,
            "external_available": observed.audio.external_output_available,
            "portable_available": observed.audio.portable_output_available,
            "code": observed.audio.failure_code or "audio.observed",
        },
    }
