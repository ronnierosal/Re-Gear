import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import probe_pinned_filter_owner as fixture


class FakeKernel:
    def __init__(self):
        self.link_fd = None
        self.events = []
        self.present = True
        self.expected = SimpleNamespace(program_id=42)

    def attach(self, fd):
        self.events.append("attach")
        self.link_fd = 9

    def link_identity(self):
        return self.expected

    def program_id(self):
        return 42

    def pin(self, *args):
        self.events.append("pin")

    def close(self):
        self.events.append("close")
        self.link_fd = None

    close_link = close

    def query_program_ids(self, fd):
        if self.link_fd is not None:
            raise AssertionError("query must prove survival without an owned link FD")
        self.events.append("query")
        return (42,) if self.present else ()

    def recover(self, *args):
        self.events.append("recover")
        self.link_fd = 10

    def detach(self, expected):
        self.events.append("detach")

    def recover_detached(self, *args):
        self.events.append("recover_detached")
        self.link_fd = 11


class PinnedFilterOwnerTests(unittest.TestCase):
    def owner(self, kernel):
        with patch.object(fixture, "CgroupDeviceLink", return_value=kernel), \
             patch.object(fixture, "FilterPinDirectory", return_value=Mock(fd=5)):
            return fixture.PinnedFixtureOwner()

    def test_fd_drop_is_observed_before_recovery(self):
        kernel = FakeKernel()
        owner = self.owner(kernel)
        owner.attach(7)
        self.assertEqual(kernel.events, ["attach", "pin", "close", "query", "recover"])
        self.assertTrue(owner.ownership_survived_fd_close)
        with patch.object(fixture.os, "unlink") as unlink:
            owner.close_link()
        self.assertEqual(kernel.events[-4:], ["detach", "close", "recover_detached", "close"])
        unlink.assert_called_once_with(owner.token, dir_fd=5)
        self.assertTrue(owner.pin_removed)

    def test_missing_survival_never_reaches_recovery_grant(self):
        kernel = FakeKernel()
        kernel.present = False
        owner = self.owner(kernel)
        with self.assertRaises(ValueError):
            owner.attach(7)
        self.assertNotIn("recover", kernel.events)
        self.assertFalse(owner.ownership_survived_fd_close)

    def test_wrong_detached_identity_never_unlinks(self):
        kernel = FakeKernel()
        owner = self.owner(kernel)
        owner.attach(7)
        kernel.recover_detached = Mock(side_effect=ValueError("foreign link"))
        with patch.object(fixture.os, "unlink") as unlink:
            with self.assertRaises(ValueError):
                owner.close_link()
            unlink.assert_not_called()
        self.assertTrue(owner.pinned)

    def test_failed_exclusive_pin_does_not_claim_ownership(self):
        kernel = FakeKernel()
        kernel.pin = Mock(side_effect=FileExistsError("occupied"))
        owner = self.owner(kernel)
        with self.assertRaises(FileExistsError):
            owner.attach(7)
        with patch.object(fixture.os, "unlink") as unlink:
            owner.close()
            unlink.assert_not_called()
        self.assertFalse(owner.pinned)
