from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.filter_authorization import (  # noqa: E402
    AuthorizationState,
    CgroupIdentity,
    OwnerIdentity,
    ParentScopeAuthorization,
    authorization_is_current,
    authorize_parent_scope,
    owner_is_live,
)


UID = 1000
MANAGER = f"/sys/fs/cgroup/user.slice/user-{UID}.slice/user@{UID}.service"
LEAF = f"{MANAGER}/session.slice/gamescope-session.service"
BOOT = "a" * 64
BINDING = "egpu-stable-id"
GENERATION = "peripheral-generation"
SAMPLE = "peripheral-sample"

CGROUP = CgroupIdentity(MANAGER, 30, 5561)
OWNER = OwnerIdentity(1844, 99001)


def grant(**overrides) -> ParentScopeAuthorization:
    arguments = dict(
        cgroup=CGROUP,
        uid=UID,
        session_uid=UID,
        owner=OWNER,
        boot_hash=BOOT,
        attachment_binding=BINDING,
        generation=GENERATION,
        sample_id=SAMPLE,
        deadline=1000.0,
    )
    arguments.update(overrides)
    return authorize_parent_scope(**arguments)


class ScopeTests(unittest.TestCase):
    def test_the_user_manager_cgroup_is_authorized(self) -> None:
        authorization = grant()
        self.assertIs(authorization.state, AuthorizationState.AUTHORIZED)
        self.assertTrue(authorization.granted)

    def test_a_leaf_service_is_refused(self) -> None:
        """This contract does not grant leaf scopes, even narrower ones."""
        authorization = grant(cgroup=CgroupIdentity(LEAF, 30, 7001))
        self.assertIs(authorization.state, AuthorizationState.REFUSED)
        self.assertEqual(
            authorization.code, "filter_authorization.not_a_user_manager_cgroup"
        )

    def test_an_arbitrary_cgroup_is_refused(self) -> None:
        authorization = grant(
            cgroup=CgroupIdentity("/sys/fs/cgroup/system.slice", 30, 12)
        )
        self.assertIs(authorization.state, AuthorizationState.REFUSED)

    def test_a_path_outside_the_cgroup_tree_is_refused(self) -> None:
        authorization = grant(cgroup=CgroupIdentity("/tmp/evil", 30, 12))
        self.assertIs(authorization.state, AuthorizationState.REFUSED)

    def test_root_user_manager_is_not_matched(self) -> None:
        path = "/sys/fs/cgroup/user.slice/user-0.slice/user@0.service"
        authorization = grant(cgroup=CgroupIdentity(path, 30, 12), uid=0, session_uid=0)
        self.assertIs(authorization.state, AuthorizationState.REFUSED)


class IdentityTests(unittest.TestCase):
    def test_a_mismatched_uid_in_the_path_is_refused(self) -> None:
        path = "/sys/fs/cgroup/user.slice/user-1000.slice/user@1001.service"
        authorization = grant(cgroup=CgroupIdentity(path, 30, 12))
        self.assertEqual(
            authorization.code, "filter_authorization.cgroup_path_inconsistent"
        )

    def test_a_path_for_another_user_is_refused(self) -> None:
        path = "/sys/fs/cgroup/user.slice/user-1001.slice/user@1001.service"
        authorization = grant(cgroup=CgroupIdentity(path, 30, 12))
        self.assertEqual(authorization.code, "filter_authorization.uid_mismatch")

    def test_a_uid_that_is_not_the_session_user_is_refused(self) -> None:
        """The path agreeing with itself proves nothing about whose session
        it is; the session uid is observed independently."""
        authorization = grant(session_uid=1001)
        self.assertEqual(
            authorization.code, "filter_authorization.not_the_session_user"
        )

    def test_cgroup_needs_a_positive_inode(self) -> None:
        with self.assertRaises(ValueError):
            CgroupIdentity(MANAGER, 30, 0)

    def test_owner_pid_reuse_is_detectable(self) -> None:
        with self.assertRaises(ValueError):
            OwnerIdentity(0, 1)
        with self.assertRaises(ValueError):
            OwnerIdentity(1, 0)


class EvidenceTests(unittest.TestCase):
    def test_an_invalid_boot_hash_is_rejected(self) -> None:
        self.assertIs(grant(boot_hash="short").state, AuthorizationState.INVALID)

    def test_incomplete_observation_evidence_is_rejected(self) -> None:
        authorization = grant(sample_id="")
        self.assertIs(authorization.state, AuthorizationState.INVALID)
        self.assertEqual(
            authorization.code, "filter_authorization.observation_incomplete"
        )

    def test_a_grant_without_a_deadline_is_rejected(self) -> None:
        self.assertIs(grant(deadline=0.0).state, AuthorizationState.INVALID)

    def test_a_grant_carries_its_authorising_observation(self) -> None:
        authorization = grant()
        self.assertEqual(authorization.attachment_binding, BINDING)
        self.assertEqual(authorization.generation, GENERATION)
        self.assertEqual(authorization.sample_id, SAMPLE)


class CurrencyTests(unittest.TestCase):
    def test_an_unchanged_scope_is_current(self) -> None:
        self.assertTrue(
            authorization_is_current(
                grant(), boot_hash=BOOT, cgroup=CGROUP, now=1.0
            )
        )

    def test_a_recreated_cgroup_is_not_current(self) -> None:
        """systemd reuses the path on restart but not the inode."""
        recreated = CgroupIdentity(MANAGER, 30, 9999)
        self.assertFalse(
            authorization_is_current(
                grant(), boot_hash=BOOT, cgroup=recreated, now=1.0
            )
        )

    def test_a_different_boot_is_not_current(self) -> None:
        self.assertFalse(
            authorization_is_current(
                grant(), boot_hash="b" * 64, cgroup=CGROUP, now=1.0
            )
        )

    def test_an_expired_grant_is_not_current(self) -> None:
        self.assertFalse(
            authorization_is_current(
                grant(deadline=10.0), boot_hash=BOOT, cgroup=CGROUP, now=10.0
            )
        )

    def test_a_refused_grant_is_never_current(self) -> None:
        refused = grant(cgroup=CgroupIdentity(LEAF, 30, 7001))
        self.assertFalse(
            authorization_is_current(
                refused, boot_hash=BOOT, cgroup=CGROUP, now=1.0
            )
        )


class OwnerLivenessTests(unittest.TestCase):
    """An unpinned link vanishing with its owner is not durable recovery, so
    recovery must be able to tell a live owner from a stale record."""

    def test_the_recorded_owner_is_live(self) -> None:
        self.assertTrue(owner_is_live(grant(), observed_start_time=99001))

    def test_a_dead_owner_is_not_live(self) -> None:
        self.assertFalse(owner_is_live(grant(), observed_start_time=None))

    def test_a_reused_pid_is_not_the_owner(self) -> None:
        """A different start time means the pid was reused by a stranger."""
        self.assertFalse(owner_is_live(grant(), observed_start_time=123456))

    def test_a_refused_grant_has_no_live_owner(self) -> None:
        refused = grant(session_uid=1001)
        self.assertFalse(owner_is_live(refused, observed_start_time=99001))


class InvariantTests(unittest.TestCase):
    def test_authorized_state_requires_a_target_and_owner(self) -> None:
        with self.assertRaises(ValueError):
            ParentScopeAuthorization(AuthorizationState.AUTHORIZED, "code")

    def test_a_refusal_cannot_carry_a_target(self) -> None:
        with self.assertRaises(ValueError):
            ParentScopeAuthorization(AuthorizationState.REFUSED, "code", CGROUP)

    def test_authorized_state_requires_binding_evidence(self) -> None:
        with self.assertRaises(ValueError):
            ParentScopeAuthorization(
                AuthorizationState.AUTHORIZED,
                "code",
                CGROUP,
                OWNER,
                UID,
                BOOT,
                "",
                GENERATION,
                SAMPLE,
                1000.0,
            )

    def test_this_contract_shares_no_type_with_the_launch_model(self) -> None:
        """The integration document forbids reusing LaunchBinding here."""
        from hdm.delivery import device_filter_lifecycle

        self.assertIsNot(ParentScopeAuthorization, device_filter_lifecycle.LaunchBinding)
        self.assertNotIn(
            "LaunchBinding",
            (ROOT / "backend/hdm/domain/filter_authorization.py").read_text(
                encoding="utf-8"
            ).split("MUST NOT", 1)[1],
        )


if __name__ == "__main__":
    unittest.main()
