"""Adversarial offline credential-link tests; no PipeWire connection is opened."""
import copy
import json
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.adapters.steamos.pipewire_stream_binding import (
    MAX_DUMP_BYTES, MAX_OBJECTS, StreamCandidate, bind_stream_candidate,
)


def inventory():
    return [
        {"id": 0, "type": "PipeWire:Interface:Core", "info": {"cookie": 987}},
        {"id": 10, "type": "PipeWire:Interface:Client", "info": {"props": {
            "object.serial": 100, "pipewire.sec.pid": 123, "pipewire.sec.uid": 1000}}},
        {"id": 20, "type": "PipeWire:Interface:Node", "info": {"props": {
            "object.serial": 200, "client.id": 10, "media.class": "Video/Source",
            "application.process.id": "spoofable-do-not-trust"}}},
    ]


def encoded(objects):
    return json.dumps(objects).encode()


def bind(before=None, after=None, **kwargs):
    args = dict(expected_pid=123, expected_uid=1000, before_sample_id="sample-1", after_sample_id="sample-2")
    args.update(kwargs)
    return bind_stream_candidate(encoded(inventory()) if before is None else before,
                                 encoded(inventory()) if after is None else after, **args)


class PipeWireStreamBindingTests(unittest.TestCase):
    def assert_absent(self, result):
        self.assertNotEqual(result.code, "credential_linked_candidate")
        for field in ("node_id", "node_serial", "client_id", "client_serial", "core_cookie"):
            self.assertIsNone(getattr(result, field))

    def test_stable_unique_join_retains_private_birth_identities_only(self):
        result = bind()
        self.assertEqual(result, StreamCandidate("credential_linked_candidate", 20, 200, 10, 100, 987))
        self.assertEqual(set(result.to_payload()), {"code", "stream_ownership_verified", "presenter_supported",
                                                   "game_renderer_verified", "frame_delivery_verified"})
        self.assertTrue(all(value is False for key, value in result.to_payload().items() if key != "code"))

    def test_numeric_strings_are_supported_without_float_bool_or_unicode_coercion(self):
        objects = inventory()
        for item in objects[1:]:
            props = item["info"]["props"]
            for key in ("object.serial", "pipewire.sec.pid", "pipewire.sec.uid", "client.id"):
                if key in props:
                    props[key] = str(props[key])
        self.assertEqual(bind(encoded(objects), encoded(objects)).code, "credential_linked_candidate")
        for field in ("pipewire.sec.pid", "pipewire.sec.uid"):
            for invalid in (True, 1.0, " 123", "+123", "00123", "１２３", -1, None, {}, []):
                changed = inventory()
                changed[1]["info"]["props"][field] = invalid
                self.assert_absent(bind(encoded(changed), encoded(changed)))

    def test_application_pid_spoof_without_protocol_credentials_cannot_pass(self):
        objects = inventory()
        props = objects[1]["info"]["props"]
        props.pop("pipewire.sec.pid")
        props["application.process.id"] = 123
        objects[2]["info"]["props"]["application.process.id"] = 123
        self.assert_absent(bind(encoded(objects), encoded(objects)))
        objects = inventory()
        objects[1]["info"]["props"]["pipewire.sec.pid"] = 456
        objects[2]["info"]["props"]["application.process.id"] = 123
        self.assertEqual(bind(encoded(objects), encoded(objects)).code, "candidate_missing")

    def test_forged_node_client_join_never_becomes_authoritative(self):
        objects = inventory()
        objects[2]["info"]["props"].update({"client.id": 10, "object.linger": True,
                                           "application.process.id": 999})
        result = bind(encoded(objects), encoded(objects))
        self.assertEqual(result.code, "credential_linked_candidate")
        self.assertIs(result.to_payload()["stream_ownership_verified"], False)
        self.assertIs(result.to_payload()["presenter_supported"], False)

    def test_credentials_must_match_both_expected_pid_and_uid(self):
        for key, value in (("pipewire.sec.uid", 2000), ("pipewire.sec.pid", 999)):
            objects = inventory()
            objects[1]["info"]["props"][key] = value
            self.assertEqual(bind(encoded(objects), encoded(objects)).code, "candidate_missing")
        for args in ({"expected_pid": True}, {"expected_uid": True}, {"expected_pid": "123"},
                     {"expected_pid": 0}, {"expected_pid": 2**31}, {"expected_uid": -1},
                     {"expected_uid": 2**32 - 1}):
            self.assertEqual(bind(**args).code, "binding_input_invalid")
        objects = inventory()
        objects[1]["info"]["props"]["pipewire.sec.uid"] = 0
        self.assertEqual(bind(encoded(objects), encoded(objects), expected_uid=0).code,
                         "credential_linked_candidate")

    def test_samples_are_distinct_nonempty_and_strings(self):
        for args in ({"before_sample_id": "sample-2"}, {"before_sample_id": ""},
                     {"after_sample_id": " "}, {"before_sample_id": None}, {"after_sample_id": 2}):
            self.assertEqual(bind(**args).code, "sample_stale")

    def test_core_restart_and_node_or_client_reuse_invalidates_binding(self):
        variants = []
        changed = inventory()
        changed[0]["info"]["cookie"] += 1
        variants.append(changed)
        for index in (1, 2):
            changed = inventory()
            changed[index]["info"]["props"]["object.serial"] += 1
            variants.append(changed)
        changed = inventory()
        changed[2]["id"] = 21
        variants.append(changed)
        changed = inventory()
        changed[1]["id"] = 11
        changed[2]["info"]["props"]["client.id"] = 11
        variants.append(changed)
        for changed in variants:
            result = bind(after=encoded(changed))
            self.assertEqual(result.code, "candidate_changed")
            self.assert_absent(result)

    def test_missing_core_client_serial_or_node_join_refuses(self):
        variants = [inventory()[1:], [inventory()[0], inventory()[2]]]
        for index, key in ((1, "object.serial"), (2, "object.serial"), (2, "client.id")):
            changed = inventory()
            changed[index]["info"]["props"].pop(key)
            variants.append(changed)
        for objects in variants:
            self.assert_absent(bind(encoded(objects), encoded(objects)))

    def test_multiple_candidates_and_cores_are_ambiguous(self):
        objects = inventory()
        other = copy.deepcopy(objects[2])
        other["id"] = 21
        other["info"]["props"]["object.serial"] = 201
        objects.append(other)
        self.assertEqual(bind(encoded(objects), encoded(objects)).code, "candidate_ambiguous")
        objects = inventory()
        objects.append({"id": 1, "type": "PipeWire:Interface:Core", "info": {"cookie": 987}})
        self.assertEqual(bind(encoded(objects), encoded(objects)).code, "candidate_ambiguous")

    def test_duplicate_keys_ids_serials_and_late_malformed_data_win(self):
        duplicate_key = b'[{"id":0,"id":1}]'
        variants = [duplicate_key]
        for extra in (None, {"id": 20}, {"id": 99, "info": {"props": {"object.serial": 200}}}):
            variants.extend((encoded([*inventory(), extra]), encoded([extra, *inventory()])))
        for raw in variants:
            self.assertEqual(bind(after=raw).code, "dump_invalid")
        incomplete = inventory()
        incomplete[2]["info"]["props"].pop("client.id")
        self.assertEqual(bind(encoded(incomplete), b"{").code, "dump_invalid")
        self.assertEqual(bind(b"{", encoded(incomplete)).code, "dump_invalid")

    def test_invalid_shapes_utf8_and_non_json_numbers_fail_closed(self):
        for raw in (b"{", b"null", b"{}", b"[true]", b"\xff", b"[" * 2000,
                    b'[{"id":0,"info":{"cookie":NaN}}]',
                    encoded([{"id": 0, "info": []}])):
            self.assertEqual(bind(after=raw).code, "dump_invalid")
        for identity in (True, -1, 2**32, "20"):
            objects = inventory()
            objects[2]["id"] = identity
            self.assertEqual(bind(after=encoded(objects)).code, "dump_invalid")

    def test_cookie_serial_and_credential_overflow_never_pass(self):
        for invalid in (True, -1, 2**32, "9" * 100):
            objects = inventory()
            objects[0]["info"]["cookie"] = invalid
            self.assertEqual(bind(after=encoded(objects)).code, "dump_invalid")
        for invalid in (True, -1, 2**64, "9" * 100):
            objects = inventory()
            objects[2]["info"]["props"]["object.serial"] = invalid
            self.assertEqual(bind(after=encoded(objects)).code, "dump_invalid")
        for field, invalid in (("pipewire.sec.pid", 2**31), ("pipewire.sec.uid", 2**32 - 1),
                               ("client.id", 2**32)):
            objects = inventory()
            objects[2 if field == "client.id" else 1]["info"]["props"][field] = invalid
            self.assert_absent(bind(after=encoded(objects)))

    def test_dump_byte_and_object_limits(self):
        for raw in ("[]", bytearray(b"[]"), b" " * (MAX_DUMP_BYTES + 1),
                    encoded([{"id": n} for n in range(MAX_OBJECTS + 1)])):
            self.assertEqual(bind(after=raw).code, "dump_invalid")
        self.assertEqual(bind(after=encoded([{"id": n} for n in range(MAX_OBJECTS)])).code,
                         "candidate_missing")

    def test_public_projection_never_leaks_ids_or_arbitrary_codes(self):
        for code in ("private-host-user-id", [], {}):
            result = StreamCandidate(code, 123456789, 987654321, 55, 66, 77)
            payload = result.to_payload()
            self.assertEqual(payload["code"], "binding_input_invalid")
            self.assertNotIn("123456789", json.dumps(payload))
            self.assertNotIn("private-host", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
