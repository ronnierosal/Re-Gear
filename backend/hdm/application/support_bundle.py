"""Bounded, privacy-safe Re-Gear support bundle construction."""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..domain.game_compatibility import GameCompatibilityRecord
from ..domain.hardware_compatibility import HardwareCompatibilityRecord
from ..domain.transition_journal import TransitionJournal


BUNDLE_SCHEMA_VERSION = 2
EVENT_SCHEMA_VERSION = 1
DEFAULT_MAX_EVENTS = 128
DEFAULT_MAX_BYTES = 256 * 1024
MAX_STRING_LENGTH = 240
MAX_COLLECTION_ITEMS = 32

_CODE_RE = re.compile(r"^[a-z0-9_.-]{1,64}$")
_FORBIDDEN_FIELD_NAMES = {
    "address",
    "argv",
    "bdf",
    "cmdline",
    "command",
    "connector",
    "environment",
    "home",
    "hostname",
    "instance_id",
    "ip",
    "path",
    "pci",
    "pid",
    "process_start_time",
    "stable_id",
    "username",
}
_REDACTION_PATTERNS = (
    re.compile(r"(?i)(?:[a-z]:\\users\\|/(?:home|users)/)[^\s/\\]+(?:[/\\][^\s,;]*)?"),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"(?i)\b[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]\b"),
    re.compile(r"(?i)\b[0-9a-f]{4}:[0-9a-f]{4}\b"),
    re.compile(r"(?i)\b(?:card|renderD|controlD)\d+\b"),
    re.compile(r"(?i)\b(?:eDP|HDMI-A|DP)-\d+\b"),
    re.compile(r"(?i)\b[0-9a-f]{20,}\b"),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_code(value: str, fallback: str) -> str:
    normalized = value.strip().lower()
    return normalized if _CODE_RE.fullmatch(normalized) else fallback


def redact_text(value: object, sensitive_values: Iterable[str] = ()) -> str:
    text = str(value)
    for sensitive in sorted(
        {item for item in sensitive_values if item}, key=len, reverse=True
    ):
        escaped = re.escape(sensitive)
        if sensitive.isalnum():
            escaped = rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])"
        text = re.sub(escaped, "[redacted]", text, flags=re.IGNORECASE)
    for pattern in _REDACTION_PATTERNS:
        text = pattern.sub("[redacted]", text)
    if len(text) > MAX_STRING_LENGTH:
        text = f"{text[: MAX_STRING_LENGTH - 14]}…[truncated]"
    return text


def sanitize_value(value: Any, sensitive_values: Iterable[str] = ()) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return round(max(0.0, value), 3)
    if isinstance(value, str):
        return redact_text(value, sensitive_values)
    if isinstance(value, Mapping):
        rows: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_COLLECTION_ITEMS:
                rows["truncated_fields"] = True
                break
            safe_key = _safe_code(str(key), f"redacted_field_{index}")
            if (
                safe_key in _FORBIDDEN_FIELD_NAMES
                or safe_key.endswith("_path")
                or safe_key.endswith("_bdf")
                or safe_key.endswith("_pid")
            ):
                continue
            rows[safe_key] = sanitize_value(item, sensitive_values)
        return rows
    if isinstance(value, (list, tuple)):
        rows = [
            sanitize_value(item, sensitive_values)
            for item in value[:MAX_COLLECTION_ITEMS]
        ]
        if len(value) > MAX_COLLECTION_ITEMS:
            rows.append({"truncated_items": True})
        return rows
    return redact_text(type(value).__name__, sensitive_values)


@dataclass(frozen=True, slots=True)
class SupportEvent:
    timestamp: str
    severity: str
    code: str
    component: str
    stage: str
    correlation_id: str
    details: Mapping[str, Any] = field(default_factory=dict)


class BoundedEventLog:
    def __init__(
        self,
        max_events: int = DEFAULT_MAX_EVENTS,
        clock: Callable[[], datetime] = _utc_now,
        correlation_id: Callable[[], str] | None = None,
    ) -> None:
        if max_events <= 0 or max_events > 1024:
            raise ValueError("max_events must be between 1 and 1024")
        self._events: deque[SupportEvent] = deque(maxlen=max_events)
        self._clock = clock
        self._correlation_id = correlation_id or (lambda: secrets.token_hex(6))
        self._lock = threading.Lock()

    def append(
        self,
        *,
        severity: str,
        code: str,
        component: str,
        stage: str,
        details: Mapping[str, Any] | None = None,
    ) -> SupportEvent:
        event = SupportEvent(
            timestamp=self._clock().astimezone(timezone.utc).isoformat(),
            severity=_safe_code(severity, "unknown"),
            code=_safe_code(code, "event.invalid"),
            component=_safe_code(component, "unknown"),
            stage=_safe_code(stage, "unknown"),
            correlation_id=_safe_code(self._correlation_id(), "invalid"),
            details=dict(details or {}),
        )
        with self._lock:
            self._events.append(event)
        return event

    def snapshot(self) -> tuple[SupportEvent, ...]:
        with self._lock:
            return tuple(self._events)


@dataclass(frozen=True, slots=True)
class SupportBundle:
    payload: Mapping[str, Any]
    json_text: str
    size_bytes: int
    event_count: int


@dataclass(frozen=True, slots=True)
class SupportBundlePreview:
    token: str
    bundle: SupportBundle


@dataclass(frozen=True, slots=True)
class PeripheralSupportStatus:
    controller_complete: bool
    controller_exact: bool
    controller_code: str
    audio_complete: bool
    audio_exact: bool
    audio_code: str

    def __post_init__(self) -> None:
        if not _CODE_RE.fullmatch(self.controller_code) or not _CODE_RE.fullmatch(self.audio_code):
            raise ValueError("peripheral support status code is invalid")


@dataclass(frozen=True, slots=True)
class WakeDiagnosticsSupportStatus:
    """Categorical G1 wake evidence; never PCI identities or raw sysfs values."""

    applicable: bool
    bridge_wakeup: str
    function_wakeup_enabled: int
    function_wakeup_disabled: int
    function_wakeup_unknown: int
    function_runtime_active: int
    function_runtime_suspended: int
    function_runtime_unknown: int
    reason: str

    def __post_init__(self) -> None:
        if self.bridge_wakeup not in {"enabled", "disabled", "unknown"}:
            raise ValueError("wake diagnostic bridge state is invalid")
        counts = (
            self.function_wakeup_enabled,
            self.function_wakeup_disabled,
            self.function_wakeup_unknown,
            self.function_runtime_active,
            self.function_runtime_suspended,
            self.function_runtime_unknown,
        )
        if any(not isinstance(value, int) or value < 0 or value > 64 for value in counts):
            raise ValueError("wake diagnostic count is invalid")
        if not _CODE_RE.fullmatch(self.reason):
            raise ValueError("wake diagnostic reason is invalid")


@dataclass(frozen=True, slots=True)
class SupportBundleContext:
    transition_journals: tuple[TransitionJournal, ...] = field(default_factory=tuple)
    game_compatibility: tuple[GameCompatibilityRecord, ...] = field(default_factory=tuple)
    hardware_compatibility: tuple[HardwareCompatibilityRecord, ...] = field(default_factory=tuple)
    peripheral_status: PeripheralSupportStatus | None = None
    wake_diagnostics: WakeDiagnosticsSupportStatus | None = None

    def __post_init__(self) -> None:
        if len(self.transition_journals) > 4:
            raise ValueError("support context transition journal count exceeds its bound")
        if len(self.game_compatibility) > 8:
            raise ValueError("support context game compatibility count exceeds its bound")
        if len(self.hardware_compatibility) > 8:
            raise ValueError("support context hardware compatibility count exceeds its bound")


class SupportBundlePreviewStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = 300,
        max_previews: int = 3,
        monotonic: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or ttl_seconds > 3600:
            raise ValueError("ttl_seconds must be between 0 and 3600")
        if max_previews <= 0 or max_previews > 10:
            raise ValueError("max_previews must be between 1 and 10")
        self._ttl_seconds = ttl_seconds
        self._max_previews = max_previews
        self._monotonic = monotonic
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(18))
        self._previews: dict[str, tuple[float, SupportBundle]] = {}
        self._lock = threading.Lock()

    def issue(self, bundle: SupportBundle) -> SupportBundlePreview:
        with self._lock:
            self._expire_locked()
            while len(self._previews) >= self._max_previews:
                oldest = min(self._previews, key=lambda key: self._previews[key][0])
                self._previews.pop(oldest)
            token = self._token_factory()
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,96}", token):
                raise ValueError("preview token generator returned an invalid token")
            if token in self._previews:
                raise ValueError("preview token generator returned a duplicate token")
            self._previews[token] = (self._monotonic(), bundle)
            return SupportBundlePreview(token, bundle)

    def consume(self, token: str) -> SupportBundle:
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,96}", token):
            raise ValueError("support bundle preview token is invalid")
        with self._lock:
            self._expire_locked()
            value = self._previews.pop(token, None)
            if value is None:
                raise ValueError("support bundle preview expired or was already used")
            return value[1]

    def _expire_locked(self) -> None:
        cutoff = self._monotonic() - self._ttl_seconds
        expired = [
            token for token, (created, _) in self._previews.items() if created <= cutoff
        ]
        for token in expired:
            self._previews.pop(token, None)


def _profile_checks(
    snapshot: Mapping[str, Any], diagnostics: Mapping[str, Any]
) -> list[dict[str, str]]:
    sleep_guard = snapshot.get("sleep_guard", {})
    disconnect = snapshot.get("disconnect_readiness", {})
    gamescope = snapshot.get("gamescope", {})
    hardware_profiles = diagnostics.get("hardware_profiles", {})
    host_profile = (
        hardware_profiles.get("host", {})
        if isinstance(hardware_profiles, Mapping)
        else {}
    )
    host_exact = (
        host_profile.get("status") == "exact"
        if isinstance(host_profile, Mapping) and host_profile
        else snapshot.get("host_profile") not in {None, "", "unknown"}
    )
    required = sleep_guard.get("required") is True
    return [
        {
            "code": "host.profile_exact",
            "result": "pass" if host_exact else "fail",
        },
        {
            "code": "hardware.support",
            "result": "pass" if snapshot.get("support_tier") == "certified" else "fail",
        },
        {
            "code": "gamescope.verified",
            "result": "pass" if gamescope.get("confidence") == "verified" else "fail",
        },
        {
            "code": "game_state.known",
            "result": "pass" if snapshot.get("game_state") in {"idle", "running"} else "fail",
        },
        {
            "code": "disconnect.scan_complete",
            "result": (
                "pass"
                if disconnect.get("scan_complete") is True
                else "fail" if disconnect.get("applicable") is True else "not_applicable"
            ),
        },
        {
            "code": "sleep_guard.active",
            "result": (
                "pass"
                if required and sleep_guard.get("active") is True
                else "fail" if required else "not_applicable"
            ),
        },
    ]


def _support_snapshot(snapshot: Mapping[str, Any], sensitive: Iterable[str]) -> dict[str, Any]:
    gpus = snapshot.get("gpus", [])
    displays = snapshot.get("displays", [])
    gamescope = snapshot.get("gamescope", {})
    disconnect = snapshot.get("disconnect_readiness", {})
    clients = disconnect.get("clients", [])
    return {
        "schema_version": int(snapshot.get("schema_version", 0)),
        "observed_at": redact_text(snapshot.get("observed_at", ""), sensitive),
        "host_profile": redact_text(snapshot.get("host_profile", "unknown"), sensitive),
        "support_tier": redact_text(snapshot.get("support_tier", "unknown"), sensitive),
        "game_state": redact_text(snapshot.get("game_state", "unknown"), sensitive),
        "gpus": [
            sanitize_value(
                {
                    "role": gpu.get("role", "unknown"),
                    "present": gpu.get("present"),
                    "selected_for_render": gpu.get("selected_for_render"),
                    "confidence": gpu.get("confidence", "unknown"),
                },
                sensitive,
            )
            for gpu in gpus[:16]
        ],
        "displays": [
            sanitize_value(
                {
                    "kind": display.get("kind", "unknown"),
                    "connected": display.get("connected"),
                    "active": display.get("active"),
                    "edid_ready": display.get("edid_ready"),
                    "confidence": display.get("confidence", "unknown"),
                },
                sensitive,
            )
            for display in displays[:16]
        ],
        "gamescope": sanitize_value(
            {
                "running": gamescope.get("running"),
                "confidence": gamescope.get("confidence", "unknown"),
            },
            sensitive,
        ),
        "disconnect_readiness": sanitize_value(
            {
                "applicable": disconnect.get("applicable"),
                "scan_complete": disconnect.get("scan_complete"),
                "ready": disconnect.get("ready"),
                "client_count": len(clients),
                "clients": [
                    {
                        "name": client.get("name", "unknown"),
                        "kind": client.get("kind", "unknown"),
                        "resources": client.get("resources", []),
                        "close_eligible": client.get("close_eligible"),
                        "reason": client.get("reason", ""),
                    }
                    for client in clients[:MAX_COLLECTION_ITEMS]
                ],
                "storage_devices": disconnect.get("storage_devices", 0),
                "storage_in_use": disconnect.get("storage_in_use"),
                "error": disconnect.get("error", ""),
            },
            sensitive,
        ),
        "sleep_guard": sanitize_value(snapshot.get("sleep_guard", {}), sensitive),
        "blockers": sanitize_value(snapshot.get("blockers", []), sensitive),
    }


def _support_context(context: SupportBundleContext) -> dict[str, Any]:
    transition_rows = []
    for journal in context.transition_journals:
        transition_rows.append(
            {
                "schema_version": journal.schema_version,
                "terminal": journal.terminal,
                "entries": [
                    {
                        "sequence": entry.sequence,
                        "kind": entry.kind.value,
                        "occurred_at": entry.occurred_at,
                        "workflow_state": entry.workflow_state.value,
                        "placement": entry.placement.value,
                        "code": entry.code,
                        "details": {key: value for key, value in entry.details},
                    }
                    for entry in journal.entries[-MAX_COLLECTION_ITEMS:]
                ],
            }
        )
    game_rows = [
        {
            "steam_app_id": record.steam_app_id or "unknown",
            "host_profile": record.host_profile_id,
            "egpu_profile": record.egpu_profile_id,
            "egpu_handoff": record.egpu_handoff.value,
            "save_sleep": record.save_sleep.value,
            "promotion_count": len(record.promotions),
        }
        for record in context.game_compatibility
    ]
    hardware_rows = [
        {
            "host_profile": record.host_profile_id,
            "egpu_profile": record.egpu_profile_id,
            "combination_status": record.combination_status.value,
            "capabilities": [
                {
                    "capability": claim.capability.value,
                    "status": claim.status.value,
                }
                for claim in record.claims
            ],
            "promotion_count": len(record.promotions),
        }
        for record in context.hardware_compatibility
    ]
    return {
        "transition_history": transition_rows,
        "game_compatibility": game_rows,
        "hardware_compatibility": hardware_rows,
        "peripheral_status": (
            {
                "controller": {"complete": context.peripheral_status.controller_complete, "exact": context.peripheral_status.controller_exact, "code": context.peripheral_status.controller_code},
                "audio": {"complete": context.peripheral_status.audio_complete, "exact": context.peripheral_status.audio_exact, "code": context.peripheral_status.audio_code},
            }
            if context.peripheral_status is not None else None
        ),
        "wake_diagnostics": (
            {
                "applicable": context.wake_diagnostics.applicable,
                "bridge_wakeup": context.wake_diagnostics.bridge_wakeup,
                "function_wakeup": {
                    "enabled": context.wake_diagnostics.function_wakeup_enabled,
                    "disabled": context.wake_diagnostics.function_wakeup_disabled,
                    "unknown": context.wake_diagnostics.function_wakeup_unknown,
                },
                "function_runtime": {
                    "active": context.wake_diagnostics.function_runtime_active,
                    "suspended": context.wake_diagnostics.function_runtime_suspended,
                    "unknown": context.wake_diagnostics.function_runtime_unknown,
                },
                "reason": context.wake_diagnostics.reason,
            }
            if context.wake_diagnostics is not None else None
        ),
    }


class SupportBundleService:
    def __init__(
        self,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if max_bytes < 1024 or max_bytes > 2 * 1024 * 1024:
            raise ValueError("max_bytes must be between 1024 and 2097152")
        self._max_bytes = max_bytes
        self._clock = clock

    def build(
        self,
        report: Mapping[str, Any],
        events: Iterable[SupportEvent],
        versions: Mapping[str, str],
        sensitive_values: Iterable[str] = (),
        context: SupportBundleContext | None = None,
    ) -> SupportBundle:
        sensitive = tuple(item for item in sensitive_values if item)
        snapshot = report.get("snapshot", {})
        event_rows = [
            sanitize_value(asdict(event), sensitive) for event in events
        ][-DEFAULT_MAX_EVENTS:]
        payload: dict[str, Any] = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "created_at": self._clock().astimezone(timezone.utc).isoformat(),
            "manifest": {
                "kind": "hdm_support_bundle",
                "event_schema_version": EVENT_SCHEMA_VERSION,
                "redacted": True,
                "bounded": True,
                "contents": [
                    "versions",
                    "profile_checks",
                    "diagnostics",
                    "snapshot",
                    "events",
                    "transition_history",
                    "game_compatibility",
                    "hardware_compatibility",
                    "peripheral_status",
                    "wake_diagnostics",
                ],
            },
            "versions": sanitize_value(
                {key: versions.get(key, "unknown") for key in ("hdm", "decky", "steamos", "kernel")},
                sensitive,
            ),
            "profile_checks": _profile_checks(
                snapshot,
                report.get("diagnostics", {})
                if isinstance(report.get("diagnostics", {}), Mapping)
                else {},
            ),
            "diagnostics": sanitize_value(report.get("diagnostics", {}), sensitive),
            "snapshot": _support_snapshot(snapshot, sensitive),
            "events": event_rows,
            **sanitize_value(_support_context(context or SupportBundleContext()), sensitive),
        }

        while True:
            text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
            size = len(text.encode("utf-8"))
            if size <= self._max_bytes:
                return SupportBundle(payload, text, size, len(payload["events"]))
            if not payload["events"]:
                raise ValueError("support bundle exceeds its bounded size limit")
            payload["events"].pop(0)
            payload["manifest"]["events_truncated_for_size"] = True
