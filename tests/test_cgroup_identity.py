from __future__ import annotations

import stat
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.cgroup_identity import (  # noqa: E402
    observe_user_manager_cgroup,
    user_manager_path,
)
from regear.domain.filter_authorization import (  # noqa: E402
    AuthorizationState,
    OwnerIdentity,
    authorize_parent_scope,
)


UID = 1000
PATH = "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service"


class FakeStat:
    def __init__(self, *, device=30, inode=5561, mode=stat.S_IFDIR | 0o755) -> None:
        self.st_dev = device
        self.st_ino = inode
        self.st_mode = mode


def observe(uid=UID, *, opens=True, status=None, closed=None):
    closed = [] if closed is None else closed

    def open_directory(path):
        if not opens:
            raise OSError("fake.open_failed")
        return 9

    return observe_user_manager_cgroup(
        uid,
        open_directory=open_directory,
        stat_fd=lambda descriptor: status or FakeStat(),
        close_fd=closed.append,
    )


class PathTests(unittest.TestCase):
    def test_the_path_is_composed_from_the_uid_not_accepted_from_a_caller(self) -> None:
        self.assertEqual(user_manager_path(UID), PATH)

    def test_a_uid_that_cannot_name_a_manager_is_refused(self) -> None:
        for uid in (0, -1, "1000", True):
            with self.subTest(uid=uid):
                with self.assertRaises(ValueError):
                    user_manager_path(uid)


class ObservationTests(unittest.TestCase):
    def test_the_identity_carries_the_device_and_inode_of_what_was_opened(self) -> None:
        identity = observe()

        self.assertEqual(identity.path, PATH)
        self.assertEqual((identity.device, identity.inode), (30, 5561))

    def test_the_descriptor_is_released_whether_the_read_succeeds_or_not(self) -> None:
        closed: list[int] = []
        observe(closed=closed)
        self.assertEqual(closed, [9])

        closed.clear()

        def failing_stat(descriptor):
            raise OSError("fake.stat_failed")

        self.assertIsNone(
            observe_user_manager_cgroup(
                UID,
                open_directory=lambda path: 9,
                stat_fd=failing_stat,
                close_fd=closed.append,
            )
        )
        self.assertEqual(closed, [9])

    def test_a_cgroup_that_cannot_be_read_is_absent_rather_than_empty(self) -> None:
        """Callers map a missing observation to a refusal to arm.

        `FilterArmCoordinator` treats None as a stale authorization, which is
        the conservative reading: not knowing the scope is not the same as
        knowing it is fine.
        """
        self.assertIsNone(observe(opens=False))

    def test_something_that_is_not_a_directory_is_not_a_cgroup(self) -> None:
        self.assertIsNone(observe(status=FakeStat(mode=stat.S_IFREG | 0o644)))

    def test_an_unusable_inode_is_reported_as_absent(self) -> None:
        self.assertIsNone(observe(status=FakeStat(inode=0)))

    def test_an_invalid_uid_is_absent_rather_than_raising(self) -> None:
        self.assertIsNone(observe(0))


class AuthorizationTests(unittest.TestCase):
    def test_an_observed_identity_satisfies_the_parent_scope_contract(self) -> None:
        """The point of the adapter: `authorize_parent_scope` had no caller.

        An identity read from a real system has to be the shape the domain will
        accept, or the authorization path stays unreachable.
        """
        authorization = authorize_parent_scope(
            cgroup=observe(),
            uid=UID,
            session_uid=UID,
            owner=OwnerIdentity(1844, 99001),
            boot_hash="a" * 64,
            attachment_binding="egpu-stable-id",
            generation="generation",
            sample_id="sample",
            deadline=1000.0,
        )

        self.assertIs(authorization.state, AuthorizationState.AUTHORIZED)
        self.assertTrue(authorization.granted)
        self.assertEqual(authorization.cgroup.path, PATH)

    def test_another_user_manager_is_refused_against_the_observed_session_user(
        self,
    ) -> None:
        authorization = authorize_parent_scope(
            cgroup=observe(1001),
            uid=1001,
            session_uid=UID,
            owner=OwnerIdentity(1844, 99001),
            boot_hash="a" * 64,
            attachment_binding="egpu-stable-id",
            generation="generation",
            sample_id="sample",
            deadline=1000.0,
        )

        self.assertFalse(authorization.granted)
        self.assertEqual(authorization.code, "filter_authorization.not_the_session_user")


if __name__ == "__main__":
    unittest.main()
