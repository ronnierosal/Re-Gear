from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.delivery.filter_ownership_store import (  # noqa: E402
    MAX_BYTES,
    RECORD_FILENAME,
    FileFilterOwnershipStore,
    decode,
    encode,
)
from hdm.domain.filter_authorization import (  # noqa: E402
    CgroupIdentity,
    OwnerIdentity,
    authorize_parent_scope,
)
from hdm.domain.filter_ownership import (  # noqa: E402
    AttachedFilter,
    FilterOwnership,
    OwnershipPhase,
    begin_release,
    claim,
    record_attached,
)


UID = 1000
MANAGER = f"/sys/fs/cgroup/user.slice/user-{UID}.slice/user@{UID}.service"
BOOT = "c" * 64
CGROUP = CgroupIdentity(MANAGER, 27, 4242)
OWNER = OwnerIdentity(910, 55_500)
ATTACHED = AttachedFilter(17, 31, 99_000)


def claimed() -> FilterOwnership:
    authorization = authorize_parent_scope(
        cgroup=CGROUP,
        uid=UID,
        session_uid=UID,
        owner=OWNER,
        boot_hash=BOOT,
        attachment_binding="egpu-attachment-1",
        generation="gen-4",
        sample_id="sample-9",
        deadline=900.5,
    )
    assert authorization.granted, authorization.code
    return claim(authorization, now_ns=1_700_000_000_000_000_000)


def armed() -> FilterOwnership:
    return record_attached(claimed(), ATTACHED)


class EncodingTests(unittest.TestCase):
    def test_every_phase_survives_a_round_trip_unchanged(self) -> None:
        for record in (claimed(), armed(), begin_release(armed())):
            with self.subTest(phase=record.phase):
                self.assertEqual(decode(encode(record)), record)

    def test_encoding_is_deterministic(self) -> None:
        record = armed()
        self.assertEqual(encode(record), encode(record))

    def test_the_record_carries_no_host_or_user_data_beyond_the_scope(self) -> None:
        value = json.loads(encode(armed()))
        self.assertEqual(
            set(value),
            {
                "schema_version",
                "phase",
                "uid",
                "boot_hash",
                "cgroup",
                "owner",
                "attachment_binding",
                "generation",
                "sample_id",
                "deadline",
                "claimed_at_ns",
                "attached",
            },
        )
        # The boot id is already hashed before it reaches a grant, and the only
        # path recorded is the manager cgroup the grant was taken over.
        self.assertEqual(value["boot_hash"], BOOT)
        self.assertEqual(value["cgroup"]["path"], MANAGER)

    def test_only_a_record_may_be_encoded(self) -> None:
        with self.assertRaises(ValueError):
            encode({"phase": "armed"})  # type: ignore[arg-type]


class DecodingRefusalTests(unittest.TestCase):
    """Anything this module did not write raises, and never reads as absent."""

    def mangled(self, **changes) -> bytes:
        value = json.loads(encode(armed()))
        for key, replacement in changes.items():
            if replacement is ...:
                del value[key]
            else:
                value[key] = replacement
        return json.dumps(value).encode("utf-8")

    def test_non_bytes_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            decode("{}")  # type: ignore[arg-type]

    def test_an_oversized_record_is_refused_before_parsing(self) -> None:
        with self.assertRaises(ValueError):
            decode(b"{" + b" " * MAX_BYTES)

    def test_unreadable_bytes_are_refused(self) -> None:
        for data in (b"", b"{", b"\xff\xfe", b"[]", b"null"):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    decode(data)

    def test_an_unexpected_field_set_is_refused(self) -> None:
        for changes in ({"extra": 1}, {"phase": ...}, {"attached": ...}):
            with self.subTest(changes=tuple(changes)):
                with self.assertRaises(ValueError):
                    decode(self.mangled(**changes))

    def test_an_unsupported_schema_version_is_refused(self) -> None:
        for value in (0, 2, "1", True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    decode(self.mangled(schema_version=value))

    def test_an_unknown_phase_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            decode(self.mangled(phase="granted"))

    def test_a_nonfinite_deadline_is_refused_at_parse_time(self) -> None:
        for literal in ("Infinity", "-Infinity", "NaN"):
            with self.subTest(literal=literal):
                raw = encode(armed()).replace(b'"deadline":900.5', b'"deadline":' + literal.encode())
                with self.assertRaises(ValueError):
                    decode(raw)

    def test_a_boolean_is_not_an_integer_field(self) -> None:
        # `bool` subclasses `int`, so a permissive check would accept `true` as
        # a pid and rebuild an owner identity nobody ever had.
        with self.assertRaises(ValueError):
            decode(self.mangled(owner={"pid": True, "start_time": 5}))

    def test_an_incomplete_nested_object_is_refused(self) -> None:
        for changes in (
            {"cgroup": {"path": MANAGER, "device": 1}},
            {"owner": {"pid": 9}},
            {"attached": {"program_id": 1, "link_id": 2}},
        ):
            with self.subTest(changes=tuple(changes)):
                with self.assertRaises(ValueError):
                    decode(self.mangled(**changes))

    def test_domain_invariants_still_apply_to_a_decoded_record(self) -> None:
        for changes in (
            {"boot_hash": ""},
            {"generation": ""},
            {"deadline": 0},
            {"uid": 0},
            {"owner": {"pid": 0, "start_time": 5}},
            {"cgroup": {"path": MANAGER, "device": 27, "inode": 0}},
            {"phase": OwnershipPhase.CLAIMED.value},
        ):
            with self.subTest(changes=tuple(changes)):
                with self.assertRaises(ValueError):
                    decode(self.mangled(**changes))


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = FileFilterOwnershipStore(self.root)

    def test_a_relative_root_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            FileFilterOwnershipStore(Path("relative/regear"))

    def test_nothing_stored_loads_as_none(self) -> None:
        self.assertIsNone(self.store.load())

    def test_a_saved_record_loads_back_unchanged(self) -> None:
        record = armed()
        self.store.save(record)
        self.assertEqual(self.store.load(), record)

    def test_a_save_replaces_the_previous_record(self) -> None:
        self.store.save(claimed())
        self.store.save(armed())
        self.assertEqual(self.store.load(), armed())
        # One record, never an append log: a reader must not have to choose
        # between two versions of the truth.
        self.assertEqual(
            [path.name for path in sorted(self.root.iterdir())], [RECORD_FILENAME]
        )

    def test_a_create_lands_when_nothing_is_stored(self) -> None:
        record = claimed()
        self.store.create(record)
        self.assertEqual(self.store.load(), record)
        # No temporary is left behind to be mistaken for a record.
        self.assertEqual(
            [path.name for path in sorted(self.root.iterdir())], [RECORD_FILENAME]
        )

    def test_a_create_refuses_to_replace_an_existing_record(self) -> None:
        # This is the serialization guard: two owners that both reconciled the
        # same empty store cannot both come away believing they hold the scope.
        first = claimed()
        self.store.create(first)
        with self.assertRaises(FileExistsError):
            self.store.create(armed())
        self.assertEqual(self.store.load(), first)
        self.assertEqual(
            [path.name for path in sorted(self.root.iterdir())], [RECORD_FILENAME]
        )

    def test_a_create_refuses_to_replace_an_unreadable_record(self) -> None:
        # A record that cannot be decoded is still a record. Overwriting it
        # would discard evidence of an attempt nobody can account for.
        (self.root / RECORD_FILENAME).write_bytes(b"{truncated")
        with self.assertRaises(FileExistsError):
            self.store.create(claimed())

    def test_a_create_after_a_clear_lands_again(self) -> None:
        self.store.create(claimed())
        self.store.clear()
        self.store.create(armed())
        self.assertEqual(self.store.load(), armed())

    def test_only_a_record_may_be_created(self) -> None:
        with self.assertRaises(ValueError):
            self.store.create({"phase": "claimed"})  # type: ignore[arg-type]

    def test_an_unreadable_record_raises_rather_than_reading_as_absent(self) -> None:
        (self.root / RECORD_FILENAME).write_bytes(b"{truncated")
        with self.assertRaises(ValueError):
            self.store.load()

    def test_clear_removes_the_record_and_tolerates_its_absence(self) -> None:
        self.store.save(armed())
        self.store.clear()
        self.assertIsNone(self.store.load())
        self.store.clear()
        self.assertIsNone(self.store.load())

    def test_only_a_record_may_be_stored(self) -> None:
        with self.assertRaises(ValueError):
            self.store.save({"phase": "armed"})  # type: ignore[arg-type]

    def test_a_missing_root_refuses_rather_than_creating_one(self) -> None:
        store = FileFilterOwnershipStore(self.root / "absent")
        with self.assertRaises(ValueError):
            store.save(armed())

    def test_a_failed_save_leaves_no_temporary_file_behind(self) -> None:
        self.store.save(claimed())
        with patch(
            "hdm.delivery.filter_ownership_store.os.replace",
            side_effect=OSError("no space"),
        ):
            with self.assertRaises(OSError):
                self.store.save(armed())
        # The previous record survives intact and no partial file is left to be
        # mistaken for one.
        self.assertEqual(self.store.load(), claimed())
        self.assertEqual(
            [path.name for path in sorted(self.root.iterdir())], [RECORD_FILENAME]
        )

    @unittest.skipUnless(os.name == "posix", "directory fsync is POSIX only")
    def test_the_directory_entry_is_synced_on_save_and_clear(self) -> None:
        # A record complete on disk whose directory entry is not durable is the
        # same as having no record, which is the silent failure being fixed.
        with patch("hdm.delivery.filter_ownership_store.os.fsync") as fsync:
            self.store.save(armed())
            saves = fsync.call_count
            self.store.clear()
        self.assertGreaterEqual(saves, 2)
        self.assertGreater(fsync.call_count, saves)


if __name__ == "__main__":
    unittest.main()
