from dataclasses import asdict, replace
import json
import unittest

from backend.hdm.delivery.device_filter_protocol import (
    FilterRequest, FilterGrant, encode_request, decode_request,
    encode_grant, decode_grant, grant_matches,
)


class FilterProtocolTests(unittest.TestCase):
    def setUp(self):
        self.request = FilterRequest(1, "operation:one", "gamescope-session.service", "a" * 32, "b" * 64)
        self.grant = FilterGrant(**asdict(self.request), revision=2, status="granted")

    def test_independent_json_and_roundtrips(self):
        raw = (b'{"nonce":"' + b"b" * 64 + b'","schema":1,"operation":"operation:one",'
               b'"unit":"gamescope-session.service","invocation":"' + b"a" * 32 + b'"}')
        self.assertEqual(decode_request(raw), self.request)
        self.assertEqual(json.loads(encode_request(self.request)), asdict(self.request))
        self.assertEqual(decode_grant(encode_grant(self.grant)), self.grant)
        self.assertEqual(decode_request(encode_request(self.request)), self.request)

    def test_identity_matching_requires_every_field(self):
        self.assertTrue(grant_matches(self.request, self.grant))
        for field, value in (("operation", "other"), ("unit", "steam-launcher.service"),
                             ("invocation", "c" * 32), ("nonce", "d" * 64)):
            self.assertFalse(grant_matches(self.request, replace(self.grant, **{field: value})))
        self.assertFalse(grant_matches(asdict(self.request), self.grant))
        self.assertFalse(grant_matches(self.request, asdict(self.grant)))

    def test_extra_missing_and_authority_fields_rejected(self):
        for message, decode in ((asdict(self.request), decode_request), (asdict(self.grant), decode_grant)):
            for key in message:
                malformed = dict(message)
                del malformed[key]
                with self.assertRaises(ValueError):
                    decode(json.dumps(malformed).encode())
            for key in ("path", "devices", "pid", "extra"):
                with self.assertRaises(ValueError):
                    decode(json.dumps(dict(message, **{key: 1})).encode())

    def test_duplicate_escaped_keys_rejected(self):
        raw = encode_request(self.request)
        for extra in (b'"schema":1,', b'"\\u0073chema":1,'):
            with self.assertRaises(ValueError):
                decode_request(b"{" + extra + raw[1:])

    def test_malformed_encoding_size_shapes_and_nonfinite(self):
        for raw in (b"", b" " * 2049, b"\xff", b"[]", b"null", b"1", b"{}{}",
                    b'{"schema":NaN}', b'{"schema":Infinity}', b'{"schema":-Infinity}',
                    bytearray(b"{}"), "{}", b"[" * 1020 + b"]" * 1020):
            for decode in (decode_request, decode_grant):
                with self.subTest(raw=repr(raw)[:30]), self.assertRaises(ValueError):
                    decode(raw)

    def test_field_types_and_ranges(self):
        for field, values in (("schema", (True, 1.0, 2, "1")),
                              ("operation", (None, 1, "", "x" * 129, "bad/path")),
                              ("unit", ([], "other.service")),
                              ("invocation", ("A" * 32, "a" * 31, 1)),
                              ("nonce", ("b" * 63, "B" * 64, False))):
            for value in values:
                for cls, original in ((FilterRequest, asdict(self.request)), (FilterGrant, asdict(self.grant))):
                    with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                        cls(**dict(original, **{field: value}))
        for revision in (True, 0, -1, 1.0, "2", None):
            with self.assertRaises(ValueError):
                replace(self.grant, revision=revision)
        for status in (True, None, "denied", "GRANTED"):
            with self.assertRaises(ValueError):
                replace(self.grant, status=status)

    def test_wrong_encoder_type_and_oversized_integer_rejected(self):
        with self.assertRaises(ValueError):
            encode_request(self.grant)
        with self.assertRaises(ValueError):
            encode_grant(self.request)
        with self.assertRaises(ValueError):
            encode_grant(replace(self.grant, revision=10**2100))


if __name__ == "__main__":
    unittest.main()
