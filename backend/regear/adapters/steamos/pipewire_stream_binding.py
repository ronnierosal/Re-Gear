"""Private read-only PipeWire candidate continuity, not presenter authority.

Source-informed independent implementation (no upstream code copied): PipeWire
1cd56b0615bb8bd112d9a2865a41cfdf638692f6, native protocol credentials at
https://github.com/PipeWire/pipewire/blob/1cd56b0615bb8bd112d9a2865a41cfdf638692f6/src/modules/module-protocol-native.c#L657-L663
and src/pipewire/impl-client.c lines 183-185. The same revision's
src/modules/module-adapter.c lines 199-202 permits supplied client.id for
lingering adapters. Consequently a Node -> Client credential match is only a
candidate: it does not authenticate node ownership, rendering or frame delivery.
Sample freshness/coherence and trusted acquisition remain caller obligations.
"""
from dataclasses import dataclass
import json


MAX_DUMP_BYTES = 256 * 1024
MAX_OBJECTS = 2048
_CODES = frozenset({"credential_linked_candidate", "sample_stale", "binding_input_invalid",
                    "dump_invalid", "candidate_missing", "candidate_ambiguous", "candidate_changed"})


@dataclass(frozen=True, slots=True)
class StreamCandidate:
    code: str
    node_id: int | None = None
    node_serial: int | None = None
    client_id: int | None = None
    client_serial: int | None = None
    core_cookie: int | None = None

    def to_payload(self):
        """Categorical public projection; private identities never cross this seam."""
        return {
            "code": self.code if type(self.code) is str and self.code in _CODES else "binding_input_invalid",
            "stream_ownership_verified": False,
            "presenter_supported": False,
            "game_renderer_verified": False,
            "frame_delivery_verified": False,
        }


def _number(value, upper, *, minimum=0):
    if type(value) is int:
        return value if minimum <= value < upper else None
    if (type(value) is str and 0 < len(value) <= 20
            and value.isascii() and value.isdecimal()):
        parsed = int(value)
        if str(parsed) == value and minimum <= parsed < upper:
            return parsed
    return None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("non_json_number")


def _parse(raw, pid, uid):
    if type(raw) is not bytes or len(raw) > MAX_DUMP_BYTES:
        return StreamCandidate("dump_invalid")
    try:
        objects = json.loads(raw, object_pairs_hook=_object, parse_constant=_invalid_constant)
        if type(objects) is not list or len(objects) > MAX_OBJECTS:
            return StreamCandidate("dump_invalid")
        inventory = {}
        serials = set()
        cores = []
        # Validate the whole dump before returning any absence or ambiguity.
        for item in objects:
            if type(item) is not dict:
                return StreamCandidate("dump_invalid")
            identity = item.get("id")
            if type(identity) is not int or not 0 <= identity < 2**32 or identity in inventory:
                return StreamCandidate("dump_invalid")
            kind = item.get("type")
            info = item.get("info", {})
            if type(info) is not dict:
                return StreamCandidate("dump_invalid")
            props = info.get("props", {})
            if type(props) is not dict:
                return StreamCandidate("dump_invalid")
            serial = None
            if "object.serial" in props:
                serial = _number(props["object.serial"], 2**64)
                if serial is None or serial in serials:
                    return StreamCandidate("dump_invalid")
                serials.add(serial)
            inventory[identity] = (kind, props, serial)
            if kind == "PipeWire:Interface:Core":
                cookie = _number(info.get("cookie"), 2**32)
                if cookie is None:
                    return StreamCandidate("dump_invalid")
                cores.append(cookie)
        if not cores:
            return StreamCandidate("candidate_missing")
        if len(cores) != 1:
            return StreamCandidate("candidate_ambiguous")
        candidates = []
        incomplete = False
        for identity, (kind, props, serial) in inventory.items():
            if kind != "PipeWire:Interface:Node" or props.get("media.class") != "Video/Source":
                continue
            client_id = _number(props.get("client.id"), 2**32)
            client = inventory.get(client_id) if client_id is not None else None
            if serial is None or client is None or client[0] != "PipeWire:Interface:Client":
                incomplete = True
                continue
            _, client_props, client_serial = client
            client_pid = _number(client_props.get("pipewire.sec.pid"), 2**31, minimum=1)
            client_uid = _number(client_props.get("pipewire.sec.uid"), 2**32 - 1)
            if client_serial is None or client_pid is None or client_uid is None:
                incomplete = True
                continue
            if (client_pid, client_uid) == (pid, uid):
                candidates.append(StreamCandidate("credential_linked_candidate", identity, serial,
                                                   client_id, client_serial, cores[0]))
        if incomplete or len(candidates) > 1:
            return StreamCandidate("candidate_ambiguous")
        return candidates[0] if candidates else StreamCandidate("candidate_missing")
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return StreamCandidate("dump_invalid")


def bind_stream_candidate(before: bytes, after: bytes, *, expected_pid: int,
                          expected_uid: int, before_sample_id: str,
                          after_sample_id: str) -> StreamCandidate:
    """Return one stable credential-linked candidate, never verified ownership.

    Both separately acquired dumps need a unique core, node and client identity.
    Generic client.id joins may be supplied by a different client. Even a positive
    result is unsuitable as an authority to capture, present or mutate anything.
    """
    if (type(expected_pid) is not int or not 0 < expected_pid < 2**31
            or type(expected_uid) is not int or not 0 <= expected_uid < 2**32 - 1):
        return StreamCandidate("binding_input_invalid")
    if (type(before_sample_id) is not str or type(after_sample_id) is not str
            or not before_sample_id.strip() or not after_sample_id.strip()
            or before_sample_id == after_sample_id):
        return StreamCandidate("sample_stale")
    first, second = _parse(before, expected_pid, expected_uid), _parse(after, expected_pid, expected_uid)
    if "dump_invalid" in (first.code, second.code):
        return StreamCandidate("dump_invalid")
    if "candidate_ambiguous" in (first.code, second.code):
        return StreamCandidate("candidate_ambiguous")
    if "candidate_missing" in (first.code, second.code):
        return StreamCandidate("candidate_missing")
    if first != second:
        return StreamCandidate("candidate_changed")
    return second
