from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.owner_identity import (  # noqa: E402
    observe_owner_identity,
    read_boot_hash,
)
from regear.domain.filter_authorization import (  # noqa: E402
    HEX64,
    AuthorizationState,
    CgroupIdentity,
    OwnerIdentity,
    authorize_parent_scope,
)


BOOT_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
START_TIME = 99001

#: Everything after the comm, in order, ending at `starttime`.
TAIL = "S 1 1844 1844 0 -1 4194304 5 6 7 8 9 10 11 12 20 0 4 0 " + str(START_TIME)
#: Guard against the tail drifting out of shape: `starttime` must stay at the
#: index the parser reads, or every identity below would be silently wrong.
assert len(TAIL.split()) == 20, "starttime must remain field 22 of the stat line"
assert TAIL.split()[19].isdigit()

ANY_OWNER = OwnerIdentity(1844, START_TIME)


def stat_line(pid: int = 1844, comm: str = "(gamescope)", tail: str = TAIL) -> str:
    return f"{pid} {comm} {tail} 0 0 0\n"


class ProcFs:
    """A throwaway /proc containing exactly the stat lines a test asks for."""

    def __init__(self, test) -> None:
        directory = tempfile.TemporaryDirectory()
        test.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def write(self, pid: int, line: str) -> Path:
        entry = self.root / str(pid)
        entry.mkdir(parents=True, exist_ok=True)
        (entry / "stat").write_text(line, encoding="utf-8")
        return self.root


class OwnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.proc = ProcFs(self)

    def test_the_owner_is_the_pid_and_the_instance_it_names(self) -> None:
        """A pid alone is not identity: pids are reused, start times pin one."""
        root = self.proc.write(1844, stat_line())

        owner = observe_owner_identity(1844, proc_root=root)

        self.assertEqual((owner.pid, owner.start_time), (1844, START_TIME))

    def test_a_comm_containing_spaces_and_parentheses_is_read_correctly(self) -> None:
        """The field after comm is found from the last `)`, not the first."""
        root = self.proc.write(1844, stat_line(comm="(my (weird) proc)"))

        owner = observe_owner_identity(1844, proc_root=root)

        self.assertEqual(owner.start_time, START_TIME)

    def test_a_line_describing_another_process_is_refused(self) -> None:
        """Nothing on that line can be attributed to the pid asked about."""
        root = self.proc.write(1844, stat_line(pid=1845))

        self.assertIsNone(observe_owner_identity(1844, proc_root=root))

    def test_anything_unreadable_or_unparseable_is_no_identity(self) -> None:
        cases = {
            "absent": None,
            "no parens": "1844 gamescope S 1 2 3",
            "truncated": "1844 (gamescope) S 1 2 3",
            "non numeric start": stat_line(tail=TAIL.replace(str(START_TIME), "soon")),
            "zero start": stat_line(tail=TAIL.replace(str(START_TIME), "0")),
            "non numeric pid": "x (gamescope) " + TAIL,
        }
        for label, line in cases.items():
            with self.subTest(case=label):
                proc = ProcFs(self)
                root = proc.root if line is None else proc.write(1844, line)
                self.assertIsNone(observe_owner_identity(1844, proc_root=root))

    def test_a_pid_that_cannot_name_a_process_is_refused(self) -> None:
        for pid in (0, -1, "1844", True):
            with self.subTest(pid=pid):
                self.assertIsNone(observe_owner_identity(pid, proc_root=self.proc.root))


class BootHashTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def _write(self, value: str) -> Path:
        path = self.root / "boot_id"
        path.write_text(value, encoding="ascii")
        return path

    def test_the_boot_id_is_hashed_rather_than_carried(self) -> None:
        """The grant only ever asks "same boot"; the raw id is an identifier."""
        digest = read_boot_hash(self._write(BOOT_ID + "\n"))

        self.assertTrue(HEX64.fullmatch(digest))
        self.assertNotIn(BOOT_ID, digest)
        self.assertEqual(digest, read_boot_hash(self._write(BOOT_ID)))

    def test_different_boots_hash_differently(self) -> None:
        first = read_boot_hash(self._write(BOOT_ID))
        second = read_boot_hash(self._write("00000000-0000-4000-8000-000000000001"))
        self.assertNotEqual(first, second)

    def test_anything_that_is_not_a_boot_id_produces_a_refusal_not_a_value(
        self,
    ) -> None:
        """An empty string is refused by authorize_parent_scope, which is the point.

        Hashing arbitrary text would produce a plausible 64-character grant
        bound to nothing.
        """
        for value in ("", "not-a-uuid", BOOT_ID.upper(), BOOT_ID + "extra", "  "):
            with self.subTest(value=value):
                self.assertEqual(read_boot_hash(self._write(value)), "")
        self.assertEqual(read_boot_hash(self.root / "absent"), "")


class AuthorizationTests(unittest.TestCase):
    def test_observed_identities_satisfy_the_parent_scope_contract(self) -> None:
        """The point of this adapter: authorize_parent_scope had no producer."""
        proc = ProcFs(self)
        root = proc.write(1844, stat_line())
        directory = Path(root)
        (directory / "boot_id").write_text(BOOT_ID, encoding="ascii")

        authorization = authorize_parent_scope(
            cgroup=CgroupIdentity(
                "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service", 30, 5561
            ),
            uid=1000,
            session_uid=1000,
            owner=observe_owner_identity(1844, proc_root=root),
            boot_hash=read_boot_hash(directory / "boot_id"),
            attachment_binding="egpu-stable-id",
            generation="generation",
            sample_id="sample",
            deadline=1000.0,
        )

        self.assertIs(authorization.state, AuthorizationState.AUTHORIZED)
        self.assertTrue(authorization.granted)

    def test_an_unreadable_boot_refuses_the_grant_rather_than_binding_it_to_nothing(
        self,
    ) -> None:
        authorization = authorize_parent_scope(
            cgroup=CgroupIdentity(
                "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service", 30, 5561
            ),
            uid=1000,
            session_uid=1000,
            owner=ANY_OWNER,
            boot_hash="",
            attachment_binding="egpu-stable-id",
            generation="generation",
            sample_id="sample",
            deadline=1000.0,
        )

        self.assertFalse(authorization.granted)
        self.assertEqual(authorization.code, "filter_authorization.boot_hash_invalid")


if __name__ == "__main__":
    unittest.main()
