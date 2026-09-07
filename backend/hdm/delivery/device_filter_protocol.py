"""Bounded handshake codec only; parsing never authorizes launch.

Caller must authenticate both Unix peers, bind the waiting process, persist
one-shot consumption, enforce freshness and perform delivery. A matched reply
is syntax/correlation evidence only; this module provides no replay protection.
"""
from dataclasses import asdict, dataclass
import json
import re

MAX_BYTES = 2048
_IDENTITY = {"schema", "operation", "unit", "invocation", "nonce"}


def _identity(schema, operation, unit, invocation, nonce):
    if type(schema) is not int or schema != 1:
        raise ValueError("unsupported protocol schema")
    for value, pattern in ((operation, r"[A-Za-z0-9_.:-]{1,128}"),
                           (invocation, r"[0-9a-f]{32}"), (nonce, r"[0-9a-f]{64}")):
        if type(value) is not str or re.fullmatch(pattern, value) is None:
            raise ValueError("invalid handshake identity")
    if type(unit) is not str or unit not in ("gamescope-session.service", "steam-launcher.service"):
        raise ValueError("unapproved handshake unit")


@dataclass(frozen=True)
class FilterRequest:
    schema: int
    operation: str
    unit: str
    invocation: str
    nonce: str

    def __post_init__(self):
        _identity(self.schema, self.operation, self.unit, self.invocation, self.nonce)


@dataclass(frozen=True)
class FilterGrant:
    schema: int
    operation: str
    unit: str
    invocation: str
    nonce: str
    revision: int
    status: str

    def __post_init__(self):
        _identity(self.schema, self.operation, self.unit, self.invocation, self.nonce)
        if type(self.revision) is not int or self.revision <= 0:
            raise ValueError("invalid grant revision")
        if type(self.status) is not str or self.status != "granted":
            raise ValueError("invalid grant status")


def _encode(value, expected_type):
    if type(value) is not expected_type:
        raise ValueError("wrong handshake message type")
    # Revalidate dataclass fields rather than trusting construction history.
    value = expected_type(**asdict(value))
    result = json.dumps(asdict(value), sort_keys=True, separators=(",", ":"),
                        ensure_ascii=True, allow_nan=False).encode("ascii")
    if len(result) > MAX_BYTES:
        raise ValueError("handshake exceeds bound")
    return result


def encode_request(request):
    return _encode(request, FilterRequest)


def encode_grant(grant):
    return _encode(grant, FilterGrant)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate handshake key")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("nonfinite handshake number")


def _decode(raw, expected_type, keys):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("invalid handshake byte length")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_constant)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("invalid handshake encoding") from error
    if type(value) is not dict or set(value) != keys:
        raise ValueError("invalid handshake fields")
    return expected_type(**value)


def decode_request(raw):
    return _decode(raw, FilterRequest, _IDENTITY)


def decode_grant(raw):
    return _decode(raw, FilterGrant, _IDENTITY | {"revision", "status"})


def grant_matches(request, grant):
    """Correlation check only; even a match grants no authority or freshness."""
    if type(request) is not FilterRequest or type(grant) is not FilterGrant:
        return False
    return all(getattr(request, name) == getattr(grant, name) for name in _IDENTITY)
