"""Bounded DRM fdinfo observations, without resource-release conclusions.

The caller supplies the exact device identity for each observation: client IDs
are device-scoped. Empty counters mean unavailable, never idle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re


@dataclass(frozen=True)
class DrmFdinfo:
    complete: bool
    error: str = ''
    driver: str | None = None
    client_id: int | None = None
    engines_ns: dict[str, int] = field(default_factory=dict)
    resident_bytes: dict[str, int] = field(default_factory=dict)
    total_bytes: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class EngineComparison:
    status: str
    reason: str = ''
    deltas_ns: dict[str, int] = field(default_factory=dict)


def parse_drm_fdinfo(text: str) -> DrmFdinfo:
    """Parse at most 16 KiB/256 lines. Invalid known fields fail the record."""
    if not isinstance(text, str) or len(text) > 16384:
        return DrmFdinfo(False, 'input_limit')
    try:
        if len(text.encode('utf-8')) > 16384:
            return DrmFdinfo(False, 'input_limit')
    except UnicodeError:
        return DrmFdinfo(False, 'invalid_encoding')
    lines = text.splitlines()
    if len(lines) > 256:
        return DrmFdinfo(False, 'line_limit')
    driver = None
    client = None
    engines, resident, totals, aliases = {}, {}, {}, {}
    seen = set()
    for line in lines:
        raw_key, separator, value = line.partition(':')
        key, value = raw_key.strip(), value.strip()
        recognized = key in ('drm-driver', 'drm-client-id') or key.startswith(
            ('drm-engine-', 'drm-resident-', 'drm-total-', 'drm-memory-'))
        if not recognized:
            continue
        if raw_key != key:
            return DrmFdinfo(False, 'invalid_key_whitespace')
        # Capacity and utilization cycles are not time or memory statistics.
        if key.startswith(('drm-engine-capacity-', 'drm-total-cycles-')):
            continue
        if not separator or key in seen:
            return DrmFdinfo(False, 'duplicate_or_malformed_field')
        seen.add(key)
        if key == 'drm-driver':
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', value):
                return DrmFdinfo(False, 'invalid_driver')
            driver = value
        elif key == 'drm-client-id':
            if not re.fullmatch(r'[0-9]{1,20}', value):
                return DrmFdinfo(False, 'invalid_client_id')
            client = int(value)
        else:
            prefix = next(p for p in ('drm-engine-', 'drm-resident-',
                                     'drm-total-', 'drm-memory-') if key.startswith(p))
            region = key[len(prefix):]
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', region):
                return DrmFdinfo(False, 'invalid_stat_name')
            if prefix == 'drm-engine-':
                match = re.fullmatch(r'([0-9]{1,20})\s+ns', value)
                if not match:
                    return DrmFdinfo(False, 'invalid_engine_stat')
                engines[region] = int(match[1])
            else:
                match = re.fullmatch(r'([0-9]{1,20})(?:\s+(KiB|MiB))?', value)
                if not match:
                    return DrmFdinfo(False, 'invalid_memory_stat')
                amount = int(match[1]) * {None: 1, 'KiB': 1024, 'MiB': 1048576}[match[2]]
                target = {'drm-resident-': resident, 'drm-total-': totals,
                          'drm-memory-': aliases}[prefix]
                target[region] = amount
    if driver is None:
        return DrmFdinfo(False, 'missing_driver')
    for region, amount in aliases.items():
        if region in resident and resident[region] != amount:
            return DrmFdinfo(False, 'conflicting_resident_alias')
        resident.setdefault(region, amount)
    return DrmFdinfo(True, driver=driver, client_id=client, engines_ns=engines,
                     resident_bytes=resident, total_bytes=totals)


def compare_engine_samples(before: DrmFdinfo, after: DrmFdinfo, *,
                           before_device: str, after_device: str) -> EngineComparison:
    """Counter activity only; unchanged observations do not prove lack of use."""
    if not before.complete or not after.complete:
        return EngineComparison('unknown', 'incomplete_sample')
    if (not before_device or before_device != after_device or
            before.driver != after.driver or before.client_id is None or
            before.client_id != after.client_id):
        return EngineComparison('unknown', 'identity_mismatch')
    if not before.engines_ns or before.engines_ns.keys() != after.engines_ns.keys():
        return EngineComparison('unknown', 'engine_stats_unavailable_or_changed')
    deltas = {key: after.engines_ns[key] - value
              for key, value in before.engines_ns.items()}
    if any(value < 0 for value in deltas.values()):
        return EngineComparison('unknown', 'counter_decreased')
    return EngineComparison('observed_increase' if any(deltas.values())
                            else 'observed_no_increase', deltas_ns=deltas)
