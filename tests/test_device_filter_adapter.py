from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.device_filter import CgroupDeviceFilter  # noqa: E402
from regear.delivery.device_filter_kernel import LinkIdentity  # noqa: E402
from regear.domain.filter_authorization import CgroupIdentity  # noqa: E402
from regear.ports.device_filter import ArmOutcome, DisarmOutcome  # noqa: E402


PATH = "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service"
DEVICE = 30
INODE = 5561
CGROUP = CgroupIdentity(PATH, DEVICE, INODE)
PROGRAM_ID = 444
IDENTITY = LinkIdentity(6, PROGRAM_ID, 5561)
PROGRAM = b"\x00" * 312


class FakeStat:
    def __init__(self, device=DEVICE, inode=INODE) -> None:
        self.st_dev = device
        self.st_ino = inode


class FakeLink:
    def __init__(
        self, *, load_fails=False, attach_fails=False, detach_fails=False, ids=None
    ) -> None:
        self._load_fails = load_fails
        self._attach_fails = attach_fails
        self._detach_fails = detach_fails
        self._ids = (PROGRAM_ID,) if ids is None else ids
        self.attached_to: int | None = None
        self.queried: list[int] = []
        self.detached = False
        self.closed = False

    def load(self, program):
        if self._load_fails:
            raise OSError("fake.load_failed")

    def program_id(self):
        return PROGRAM_ID

    def attach(self, cgroup_fd):
        if self._attach_fails:
            raise OSError("fake.attach_failed")
        self.attached_to = cgroup_fd

    def link_identity(self):
        return IDENTITY

    def query_program_ids(self, cgroup_fd):
        self.queried.append(cgroup_fd)
        if isinstance(self._ids, Exception):
            raise self._ids
        return self._ids

    def detach(self, expected):
        if self._detach_fails or expected != IDENTITY:
            raise RuntimeError("fake.detach_failed")
        self.detached = True

    def close(self):
        self.closed = True


def build(
    *,
    link=None,
    stat=None,
    open_fails=False,
    link_unavailable=False,
    closed=None,
):
    """Assemble the adapter with a fake kernel link and a fake cgroup."""
    opened: list[str] = []
    closed = [] if closed is None else closed

    def open_cgroup(path):
        opened.append(path)
        if open_fails:
            raise OSError("fake.open_failed")
        return 7

    def factory():
        if link_unavailable:
            raise RuntimeError("fixture requires Linux x86_64")
        return link

    adapter = CgroupDeviceFilter(
        link_factory=factory,
        open_cgroup=open_cgroup,
        stat_fd=lambda descriptor: stat or FakeStat(),
        close_fd=closed.append,
    )
    adapter.opened = opened  # type: ignore[attr-defined]
    adapter.closed = closed  # type: ignore[attr-defined]
    return adapter


class ArmTests(unittest.TestCase):
    def test_arming_loads_attaches_and_reports_the_link_identity(self) -> None:
        link = FakeLink()
        adapter = build(link=link)

        result = adapter.arm(PROGRAM, CGROUP)

        self.assertIs(result.outcome, ArmOutcome.ARMED)
        self.assertEqual(result.filter.program_id, PROGRAM_ID)
        self.assertEqual(result.filter.link_id, IDENTITY.link_id)
        self.assertEqual(result.filter.cgroup_id, IDENTITY.cgroup_id)
        self.assertEqual(link.attached_to, 7)
        self.assertEqual(adapter.opened, [PATH])

    def test_a_cgroup_recreated_under_the_same_path_is_refused(self) -> None:
        """systemd reuses the path on restart and never the inode.

        Attaching anyway would let a cgroup the authorization was never taken
        over inherit it, which is the whole reason the identity carries an
        inode.
        """
        link = FakeLink()
        adapter = build(link=link, stat=FakeStat(inode=INODE + 1))

        result = adapter.arm(PROGRAM, CGROUP)

        self.assertIs(result.outcome, ArmOutcome.REFUSED)
        self.assertEqual(result.code, "device_filter.cgroup_replaced")
        self.assertIsNone(link.attached_to)
        self.assertEqual(adapter.closed, [7])

    def test_a_cgroup_on_another_device_is_refused(self) -> None:
        adapter = build(link=FakeLink(), stat=FakeStat(device=DEVICE + 1))
        self.assertEqual(adapter.arm(PROGRAM, CGROUP).code, "device_filter.cgroup_replaced")

    def test_an_unopenable_cgroup_is_refused_without_loading_anything(self) -> None:
        link = FakeLink()
        adapter = build(link=link, open_fails=True)

        result = adapter.arm(PROGRAM, CGROUP)

        self.assertIs(result.outcome, ArmOutcome.REFUSED)
        self.assertEqual(result.code, "device_filter.cgroup_unavailable")
        self.assertFalse(link.closed)

    def test_a_kernel_that_cannot_supply_a_link_closes_the_cgroup_descriptor(
        self,
    ) -> None:
        adapter = build(link_unavailable=True)

        result = adapter.arm(PROGRAM, CGROUP)

        self.assertIs(result.outcome, ArmOutcome.LOAD_FAILED)
        self.assertEqual(result.code, "device_filter.kernel_unavailable")
        self.assertEqual(adapter.closed, [7])

    def test_a_failed_load_and_a_failed_attach_are_reported_apart(self) -> None:
        for link, outcome, code in (
            (FakeLink(load_fails=True), ArmOutcome.LOAD_FAILED, "device_filter.load_failed"),
            (
                FakeLink(attach_fails=True),
                ArmOutcome.ATTACH_FAILED,
                "device_filter.attach_failed",
            ),
        ):
            with self.subTest(code=code):
                adapter = build(link=link)
                result = adapter.arm(PROGRAM, CGROUP)
                self.assertIs(result.outcome, outcome)
                self.assertEqual(result.code, code)
                # Whatever failed, nothing is left holding descriptors.
                self.assertTrue(link.closed)
                self.assertEqual(adapter.closed, [7])

    def test_arming_twice_is_refused_rather_than_replacing_the_attachment(self) -> None:
        adapter = build(link=FakeLink())
        adapter.arm(PROGRAM, CGROUP)

        result = adapter.arm(PROGRAM, CGROUP)

        self.assertIs(result.outcome, ArmOutcome.REFUSED)
        self.assertEqual(result.code, "device_filter.already_armed")

    def test_something_that_is_not_a_cgroup_identity_is_refused(self) -> None:
        adapter = build(link=FakeLink())
        self.assertEqual(adapter.arm(PROGRAM, PATH).code, "device_filter.cgroup_invalid")


class EnforcementTests(unittest.TestCase):
    def test_enforcement_is_asked_through_the_descriptor_opened_at_arm_time(
        self,
    ) -> None:
        """Not by re-opening the path, which a replaced cgroup would answer."""
        link = FakeLink()
        adapter = build(link=link)
        adapter.arm(PROGRAM, CGROUP)

        self.assertTrue(adapter.enforced(CGROUP, PROGRAM_ID))
        self.assertEqual(link.queried, [7])
        self.assertEqual(adapter.opened, [PATH])

    def test_a_program_that_is_not_attached_is_not_enforced(self) -> None:
        adapter = build(link=FakeLink(ids=(999,)))
        adapter.arm(PROGRAM, CGROUP)
        self.assertFalse(adapter.enforced(CGROUP, PROGRAM_ID))

    def test_nothing_is_enforced_before_arming_or_after_disarming(self) -> None:
        adapter = build(link=FakeLink())
        self.assertFalse(adapter.enforced(CGROUP, PROGRAM_ID))
        adapter.arm(PROGRAM, CGROUP)
        adapter.disarm()
        self.assertFalse(adapter.enforced(CGROUP, PROGRAM_ID))

    def test_this_adapter_only_answers_for_the_program_it_loaded(self) -> None:
        adapter = build(link=FakeLink(ids=(PROGRAM_ID, 999)))
        adapter.arm(PROGRAM, CGROUP)
        self.assertFalse(adapter.enforced(CGROUP, 999))

    def test_a_query_that_fails_reads_as_not_enforced(self) -> None:
        adapter = build(link=FakeLink(ids=OSError("fake.query_failed")))
        adapter.arm(PROGRAM, CGROUP)
        self.assertFalse(adapter.enforced(CGROUP, PROGRAM_ID))


class DisarmTests(unittest.TestCase):
    def test_disarming_detaches_by_identity_and_releases_every_descriptor(
        self,
    ) -> None:
        link = FakeLink()
        adapter = build(link=link)
        adapter.arm(PROGRAM, CGROUP)

        result = adapter.disarm()

        self.assertIs(result.outcome, DisarmOutcome.DISARMED)
        self.assertTrue(link.detached)
        self.assertTrue(link.closed)
        self.assertEqual(adapter.closed, [7])

    def test_disarming_when_nothing_is_armed_says_so(self) -> None:
        self.assertIs(build(link=FakeLink()).disarm().outcome, DisarmOutcome.NOT_ARMED)

    def test_a_link_that_no_longer_matches_is_reported_and_still_released(self) -> None:
        """A detach that cannot verify its target is not one to claim success for.

        The descriptors are released regardless -- an unpinned link goes with
        them -- but the caller is told the detach did not verify.
        """
        link = FakeLink(detach_fails=True)
        adapter = build(link=link)
        adapter.arm(PROGRAM, CGROUP)

        result = adapter.disarm()

        self.assertIs(result.outcome, DisarmOutcome.FAILED)
        self.assertEqual(result.code, "device_filter.detach_failed")
        self.assertTrue(link.closed)
        self.assertEqual(adapter.closed, [7])

    def test_disarming_twice_does_not_detach_twice(self) -> None:
        link = FakeLink()
        adapter = build(link=link)
        adapter.arm(PROGRAM, CGROUP)
        adapter.disarm()

        self.assertIs(adapter.disarm().outcome, DisarmOutcome.NOT_ARMED)
        self.assertEqual(adapter.closed, [7])

    def test_a_disarmed_adapter_can_arm_again(self) -> None:
        adapter = build(link=FakeLink())
        adapter.arm(PROGRAM, CGROUP)
        adapter.disarm()
        self.assertIs(adapter.arm(PROGRAM, CGROUP).outcome, ArmOutcome.ARMED)


if __name__ == "__main__":
    unittest.main()
