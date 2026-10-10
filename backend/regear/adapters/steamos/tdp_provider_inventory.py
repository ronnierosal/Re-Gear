"""Pure interpreter for explicitly supplied synthetic TDP provider fixtures.

No live provider, filesystem, process, subscription, or persistence boundary is
reachable from this module.  A successful interpretation records observations
only; it never creates a production ``TdpReading`` or certifies power bounds.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from ...ports.tdp_provider_evidence import (
    TdpProviderEvidenceResult,
    TdpProviderGpuCandidate,
    TdpProviderHostIdentity,
    TdpProviderObservedRange,
)


FIXTURE_SCHEMA_VERSION = 1
POWER_STATION_SIGNATURE = "steamos-manager.power_station.v1"
CONFIGURED_LIMIT_KIND = "configured_power_limit"
WATTS_UNIT = "watts"
_ROLES = frozenset(("igpu", "dgpu", "egpu"))
_MAX_TOKEN_LENGTH = 256
_MAX_FIXTURE_VALUE = 0xFFFFFFFF
_WIN_MINI_IDENTITY = (
    "gpd",
    "g1617-01",
    "g1617-01",
    "amd ryzen 7 7840u w/ radeon 780m graphics",
)


class _InvalidFixture(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def _mapping(value: object, keys: frozenset[str], code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _InvalidFixture(code)
    return value


def _token(value: object, code: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or len(value) > _MAX_TOKEN_LENGTH:
        raise _InvalidFixture(code)
    token = " ".join(value.split())
    if not token and not allow_empty:
        raise _InvalidFixture(code)
    return token


def _protocol_token(value: object, code: str) -> str:
    """Return an exact wire token; protocol vocabulary is never normalized."""
    if type(value) is not str or not value or len(value) > _MAX_TOKEN_LENGTH:
        raise _InvalidFixture(code)
    return value


def _identity(value: object) -> TdpProviderHostIdentity:
    row = _mapping(
        value,
        frozenset(("sys_vendor", "product_name", "board_name", "processor")),
        "tdp.fixture_identity_invalid",
    )
    return TdpProviderHostIdentity(*(
        _token(row[name], "tdp.fixture_identity_invalid")
        for name in ("sys_vendor", "product_name", "board_name", "processor")
    ))


def _fixture_integer(value: object) -> int:
    # Explicitly reject floats (including NaN/Infinity) and bools.  The finite
    # check documents that non-finite numeric fixture evidence is never coerced.
    if type(value) is not int:
        if type(value) is float and not math.isfinite(value):
            raise _InvalidFixture("tdp.fixture_value_nonfinite")
        raise _InvalidFixture("tdp.fixture_value_invalid")
    if not 0 < value <= _MAX_FIXTURE_VALUE:
        raise _InvalidFixture("tdp.fixture_value_out_of_range")
    return value


def _result(code: str, fixture_id: str = "unidentified", **values: object) -> TdpProviderEvidenceResult:
    return TdpProviderEvidenceResult(code=code, fixture_id=fixture_id, **values)


def interpret_tdp_provider_fixture(fixture: object) -> TdpProviderEvidenceResult:
    """Validate one in-memory fixture without conferring TDP capability.

    The schema is intentionally exact so that a provider change cannot be
    mistaken for compatible evidence.  All results retain synthetic provenance
    and ``can_control`` remains false, including the fully observed case.
    """

    fixture_id = "unidentified"
    try:
        root = _mapping(
            fixture,
            frozenset((
                "schema_version", "provenance", "host_before", "host_after",
                "provider", "gpu_ownership",
            )),
            "tdp.fixture_malformed",
        )
        if type(root["schema_version"]) is not int or root["schema_version"] != FIXTURE_SCHEMA_VERSION:
            raise _InvalidFixture("tdp.fixture_signature_invalid")

        provenance = _mapping(
            root["provenance"], frozenset(("kind", "fixture_id")),
            "tdp.fixture_provenance_invalid",
        )
        if provenance["kind"] != "synthetic_fixture":
            raise _InvalidFixture("tdp.fixture_provenance_invalid")
        fixture_id = _token(provenance["fixture_id"], "tdp.fixture_provenance_invalid")

        before = _identity(root["host_before"])
        after = _identity(root["host_after"])
        if before != after:
            return _result("tdp.fixture_identity_changed", fixture_id, host=before)
        normalized_host = tuple(
            value.casefold()
            for value in (
                before.sys_vendor, before.product_name, before.board_name,
                before.processor,
            )
        )
        if normalized_host != _WIN_MINI_IDENTITY:
            return _result("tdp.fixture_host_unverified", fixture_id, host=before)

        provider = _mapping(
            root["provider"],
            frozenset(("name", "signature", "value_kind", "unit", "current", "minimum", "maximum")),
            "tdp.fixture_provider_invalid",
        )
        name = _protocol_token(provider["name"], "tdp.fixture_provider_invalid")
        signature = _protocol_token(provider["signature"], "tdp.fixture_signature_invalid")
        value_kind = _protocol_token(provider["value_kind"], "tdp.fixture_signature_invalid")
        unit = _protocol_token(provider["unit"], "tdp.fixture_unit_invalid")
        common = dict(
            host=before, provider_name=name, provider_signature=signature,
            value_kind=value_kind, unit=unit,
        )
        if name != "power_station" or signature != POWER_STATION_SIGNATURE or value_kind != CONFIGURED_LIMIT_KIND:
            return _result("tdp.fixture_signature_invalid", fixture_id, **common)
        if unit != WATTS_UNIT:
            return _result("tdp.fixture_unit_invalid", fixture_id, **common)

        observed = TdpProviderObservedRange(*(
            _fixture_integer(provider[field]) for field in ("current", "minimum", "maximum")
        ))
        common["observed_range"] = observed
        if not observed.minimum <= observed.current <= observed.maximum:
            return _result("tdp.fixture_range_inconsistent", fixture_id, **common)

        ownership = _mapping(
            root["gpu_ownership"],
            frozenset(("resolved", "provider_gpu_stable_id", "candidates")),
            "tdp.fixture_ownership_invalid",
        )
        if type(ownership["resolved"]) is not bool:
            return _result("tdp.fixture_ownership_invalid", fixture_id, **common)
        if ownership["resolved"] is not True:
            return _result("tdp.fixture_ownership_unresolved", fixture_id, **common)
        provider_gpu_id = _token(
            ownership["provider_gpu_stable_id"], "tdp.fixture_ownership_unresolved",
        )
        candidates_value = ownership["candidates"]
        if (
            not isinstance(candidates_value, Sequence)
            or isinstance(candidates_value, (str, bytes, bytearray))
            or not 1 <= len(candidates_value) <= 8
        ):
            return _result("tdp.fixture_ownership_invalid", fixture_id, **common)
        candidates = []
        for value in candidates_value:
            row = _mapping(
                value, frozenset(("stable_id", "role")),
                "tdp.fixture_ownership_invalid",
            )
            stable_id = _token(row["stable_id"], "tdp.fixture_ownership_invalid")
            role = _token(row["role"], "tdp.fixture_ownership_invalid").casefold()
            if role not in _ROLES:
                return _result("tdp.fixture_ownership_invalid", fixture_id, **common)
            candidates.append(TdpProviderGpuCandidate(stable_id, role))
        matches = tuple(candidate for candidate in candidates if candidate.stable_id == provider_gpu_id)
        if len(matches) != 1 or len({candidate.stable_id for candidate in candidates}) != len(candidates):
            return _result("tdp.fixture_ownership_ambiguous", fixture_id, **common)
        if matches[0].role != "igpu":
            return _result("tdp.fixture_provider_gpu_unverified", fixture_id, **common)

        return _result(
            "tdp.fixture_observed_unverified", fixture_id,
            provider_gpu=matches[0], **common,
        )
    except _InvalidFixture as error:
        return _result(error.code, fixture_id)
    except (KeyError, TypeError, ValueError, OverflowError):
        return _result("tdp.fixture_malformed", fixture_id)
