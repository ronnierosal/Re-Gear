"""Read-only inventory tests: metadata never certifies a working presenter."""
import json
import stat
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests import test_igpu_tv_evidence as evidence_fixtures
from regear.adapters.steamos.igpu_tv_feasibility import (
    ARTIFACTS, MAX_DUMP_BYTES, MAX_OBJECTS, FeasibilityInventory,
    IgpuTvFeasibilityCollector, classify_stream_metadata, dependency_metadata,
)
from regear.domain.gamescope_session import GamescopeSessionObservation
from regear.domain.models import Confidence
from regear.ports.transition import VersionedObservation


def node(identity=1, pid=123):
    return {"id": identity, "type": "PipeWire:Interface:Node", "info": {"props": {
        "media.class": "Video/Source", "application.process.id": pid,
        "node.name": "private-hostname-home-path-stream-name"}}}


def encoded(*objects):
    return json.dumps(list(objects)).encode()


class StreamMetadataTests(unittest.TestCase):
    def test_one_self_reported_pid_is_only_unverified_candidate(self):
        for pid in (123, "123"):
            self.assertEqual(classify_stream_metadata(encoded(node(pid=pid)), 123),
                             "candidate_observed_unverified")

    def test_missing_and_ambiguous_candidates(self):
        for raw, expected in ((b"[]", "candidate_missing"),
            (encoded(node(pid=456)), "candidate_missing"),
            (encoded(node(1), node(2)), "candidate_ambiguous")):
            self.assertEqual(classify_stream_metadata(raw, 123), expected)
        for pid in (None, True, 0, -1, 2**31, "", "-1", "１２３", "1.23", [], {}):
            self.assertEqual(classify_stream_metadata(encoded(node(pid=pid)), 123), "candidate_ambiguous")
        missing = node()
        del missing["info"]["props"]["application.process.id"]
        self.assertEqual(classify_stream_metadata(encoded(node(2), missing), 123), "candidate_ambiguous")

    def test_malformed_json_shapes_and_duplicate_keys(self):
        for raw in (b"{", b"{}", b"null", b"[null]", b"[1]", b'[{"id":1,"id":2}]',
            b'[{"id":1,"type":"PipeWire:Interface:Node","info":{"props":{"media.class":"Video/Source","media.class":"Audio/Sink"}}}]',
            encoded({"id": 1, "type": "PipeWire:Interface:Node", "info": None}),
            b"\xff", b"[" * 2000):
            with self.subTest(raw=raw[:80]):
                self.assertEqual(classify_stream_metadata(raw, 123), "dump_invalid")

    def test_invalid_metadata_wins_over_unattributed_source_in_any_order(self):
        unknown = node(1, None)
        for objects in ((unknown, {"id": 1}), ({"id": 1}, unknown),
                        (unknown, None), (None, unknown)):
            self.assertEqual(classify_stream_metadata(encoded(*objects), 123), "dump_invalid")
        for objects in ((unknown, node(2)), (node(2), unknown)):
            self.assertEqual(classify_stream_metadata(encoded(*objects), 123), "candidate_ambiguous")

    def test_object_identity_must_be_unique_bounded_integer(self):
        for identity in (None, True, -1, 2**32, "1"):
            self.assertEqual(classify_stream_metadata(encoded(node(identity)), 123), "dump_invalid")
        self.assertEqual(classify_stream_metadata(encoded(node(), node()), 123), "dump_invalid")
        # Duplicate global IDs are invalid even on unrelated object types.
        self.assertEqual(classify_stream_metadata(encoded(node(), {"id": 1, "type": "Other"}), 123), "dump_invalid")

    def test_byte_object_and_input_bounds(self):
        for raw in ("[]", bytearray(b"[]"), b" " * (MAX_DUMP_BYTES + 1),
                    encoded(*({"id": n} for n in range(MAX_OBJECTS + 1)))):
            self.assertEqual(classify_stream_metadata(raw, 123), "dump_invalid")
        self.assertEqual(classify_stream_metadata(encoded(*({"id": n} for n in range(MAX_OBJECTS))), 123), "candidate_missing")
        for pid in (True, 0, -1, 2**31, "123"):
            self.assertEqual(classify_stream_metadata(b"[]", pid), "dump_invalid")

    def test_other_node_classes_do_not_claim_video_ownership(self):
        audio = node()
        audio["info"]["props"]["media.class"] = "Audio/Sink"
        self.assertEqual(classify_stream_metadata(encoded(audio), 123), "candidate_missing")

    def test_public_payload_redacts_all_untrusted_strings_and_never_claims_support(self):
        private = "private-hostname-/home/user-pid123-device-identity"
        inventory = FeasibilityInventory(((private, private), ("gamescope", private)), private)
        payload = inventory.to_payload()
        self.assertNotIn(private, json.dumps(payload))
        self.assertEqual(set(payload["dependencies"]), {label for label, _ in ARTIFACTS})
        for value in ([], {}, None):
            payload = FeasibilityInventory((("gamescope", value),), value).to_payload()
            self.assertEqual(payload["stream_code"], "observation_unavailable")
            self.assertEqual(payload["dependencies"]["gamescope"], "metadata_unavailable")
        for code in ("candidate_observed_unverified", "candidate_ambiguous", "candidate_missing", "dump_invalid"):
            payload = FeasibilityInventory((), code).to_payload()
            for key in ("presenter_supported", "stream_ownership_verified", "game_renderer_verified",
                        "frame_delivery_verified", "drm_lease_verified"):
                self.assertIs(payload[key], False)


class MetadataTests(unittest.TestCase):
    def probe(self, *, file_mode=stat.S_IFREG | 0o755, uid=0, parent_mode=stat.S_IFDIR | 0o755,
              parent_uid=0, error=None):
        files = {str(Path(name)) for _, name in ARTIFACTS}
        calls = []
        def lstat(path):
            calls.append(str(path))
            if error:
                raise error
            is_file = str(path) in files
            return SimpleNamespace(st_mode=file_mode if is_file else parent_mode,
                                   st_uid=uid if is_file else parent_uid)
        with patch.object(Path, "lstat", lstat):
            result = dependency_metadata()
        self.assertTrue(set(calls).issubset(files | {str(p) for name in files for p in Path(name).parents}))
        return dict(result)

    def test_fixed_root_owned_regular_metadata(self):
        self.assertEqual(set(self.probe().values()), {"present_at_expected_path"})

    def test_symlinks_writable_or_nonroot_paths_never_trusted(self):
        for changes in ({"file_mode": stat.S_IFLNK | 0o777}, {"file_mode": stat.S_IFREG | 0o777},
            {"uid": 1000}, {"parent_mode": stat.S_IFLNK | 0o755},
            {"parent_mode": stat.S_IFDIR | 0o777}, {"parent_uid": 1000}):
            self.assertEqual(set(self.probe(**changes).values()), {"untrusted_metadata"})

    def test_missing_and_unavailable_are_distinct(self):
        self.assertEqual(set(self.probe(error=FileNotFoundError()).values()), {"missing_at_expected_path"})
        self.assertEqual(set(self.probe(error=PermissionError()).values()), {"metadata_unavailable"})


class Scripted:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self):
        return self.values.pop(0)


class Dump:
    def __init__(self):
        self.calls = []
        self.result = SimpleNamespace(ok=True, output=encoded(node()))

    def dump(self, user):
        self.calls.append(user)
        return self.result


class CollectorTests(unittest.TestCase):
    def setUp(self):
        fixture = evidence_fixtures.IgpuTvEvidenceTests()
        fixture.setUp()
        self.first = VersionedObservation("generation-1", fixture.snapshot, "sample-1")
        self.second = replace(self.first, observation_id="sample-2")
        self.session = GamescopeSessionObservation(True, "session.verified", "a" * 64)
        self.dump = Dump()

    def collector(self, first=None, second=None, sessions=None, metadata=None):
        return IgpuTvFeasibilityCollector(observations=Scripted(
            first if first is not None else self.first, second if second is not None else self.second),
            gamescope_sessions=Scripted(*(sessions or (self.session, self.session))),
            session_user="authenticated-session-user", pipewire=self.dump,
            metadata=metadata or (lambda: (("gamescope", "present_at_expected_path"),)))

    def test_valid_bracket_calls_only_dump_and_still_reports_unverified(self):
        result = self.collector().collect()
        self.assertEqual(result.stream_code, "candidate_observed_unverified")
        self.assertEqual(self.dump.calls, ["authenticated-session-user"])
        self.assertNotIn("private-hostname", json.dumps(result.to_payload()))
        self.assertIs(result.to_payload()["presenter_supported"], False)

    def test_unknown_initial_session_or_snapshot_does_not_dump(self):
        unknown = GamescopeSessionObservation(False, "session.unknown")
        self.assertEqual(self.collector(sessions=(unknown,)).collect().stream_code, "session_unverified")
        for changes in ({"pid": None}, {"pid": True}, {"running": None}, {"confidence": Confidence.UNKNOWN}):
            first = replace(self.first, snapshot=replace(self.first.snapshot,
                gamescope=replace(self.first.snapshot.gamescope, **changes)))
            self.assertEqual(self.collector(first=first).collect().stream_code, "session_unverified")
        self.assertEqual(self.dump.calls, [])

    def test_stale_bracket_and_changed_session_pid_or_topology_refuse(self):
        self.assertEqual(self.collector(second=self.first).collect().stream_code, "sample_stale")
        other = GamescopeSessionObservation(True, "session.verified", "b" * 64)
        self.assertEqual(self.collector(sessions=(self.session, other)).collect().stream_code, "session_or_topology_changed")
        snapshot = self.second.snapshot
        for changed in (replace(snapshot, gamescope=replace(snapshot.gamescope, pid=456)),
            replace(snapshot, gamescope=replace(snapshot.gamescope, render_gpu_stable_id="changed-renderer")),
            replace(snapshot, displays=(replace(snapshot.displays[0], connected=False),)),
            replace(snapshot, gpus=snapshot.gpus[:1])):
            self.assertEqual(self.collector(second=replace(self.second, snapshot=changed)).collect().stream_code,
                             "session_or_topology_changed")

    def test_failed_or_invalid_dump_never_returns_candidate(self):
        self.dump.result = SimpleNamespace(ok=False, output=b"private-error")
        self.assertEqual(self.collector().collect().stream_code, "dump_unavailable")
        self.dump.result = SimpleNamespace(ok=True, output=b"{")
        self.assertEqual(self.collector().collect().stream_code, "dump_invalid")

    def test_collection_exception_is_redacted_and_closes_gate(self):
        def failure():
            raise RuntimeError("private-path-and-identity")
        result = self.collector(metadata=failure).collect()
        self.assertEqual(result.stream_code, "observation_unavailable")
        self.assertNotIn("private", json.dumps(result.to_payload()))
        self.assertEqual(self.dump.calls, [])

    def candidate_collector(self, *, samples=None, sessions=None):
        return IgpuTvFeasibilityCollector(
            observations=Scripted(*(samples or (self.first, self.second,
                replace(self.first, observation_id="sample-3")))),
            gamescope_sessions=Scripted(*(sessions or (self.session, self.session))),
            session_user=SimpleNamespace(uid=1000), pipewire=self.dump)

    def test_two_dump_candidate_collection_keeps_all_authority_flags_false(self):
        from tests.test_pipewire_stream_binding import inventory
        self.dump.result = SimpleNamespace(ok=True, output=json.dumps(inventory()).encode())
        result = self.candidate_collector().collect_stream_candidate()
        self.assertEqual(result.code, "credential_linked_candidate")
        self.assertEqual(len(self.dump.calls), 2)
        self.assertTrue(all(value is False for key, value in result.to_payload().items() if key != "code"))

    def test_failed_first_dump_or_changed_midpoint_does_not_collect_again(self):
        self.dump.result = SimpleNamespace(ok=False, output=b"private")
        self.assertEqual(self.candidate_collector().collect_stream_candidate().code, "dump_invalid")
        self.assertEqual(len(self.dump.calls), 1)
        self.dump.calls.clear()
        self.dump.result = SimpleNamespace(ok=True, output=b"[]")
        changed = replace(self.second, snapshot=replace(self.second.snapshot,
            gamescope=replace(self.second.snapshot.gamescope, pid=456)))
        self.assertEqual(self.candidate_collector(samples=(self.first, changed)).collect_stream_candidate().code,
                         "candidate_changed")
        self.assertEqual(len(self.dump.calls), 1)

    def test_stale_or_replaced_session_never_returns_candidate(self):
        result = self.candidate_collector(samples=(self.first, self.second, self.first)).collect_stream_candidate()
        self.assertEqual(result.code, "sample_stale")
        replaced = GamescopeSessionObservation(True, "session.verified", "b" * 64)
        result = self.candidate_collector(sessions=(self.session, replaced)).collect_stream_candidate()
        self.assertEqual(result.code, "candidate_changed")

    def test_server_restart_between_actual_dump_calls_rejects_candidate(self):
        from tests.test_pipewire_stream_binding import inventory
        one, two = inventory(), inventory()
        two[0]["info"]["cookie"] += 1
        replies = iter((one, two))
        self.dump.dump = lambda user: SimpleNamespace(ok=True, output=json.dumps(next(replies)).encode())
        self.assertEqual(self.candidate_collector().collect_stream_candidate().code, "candidate_changed")


if __name__ == "__main__":
    unittest.main()
