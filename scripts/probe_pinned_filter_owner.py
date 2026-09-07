"""Persistent-ownership variant for the disposable dummy-device fixture only.

Uses one exclusive random pin in the authenticated root directory. No player
service integration. Dropping all owner FDs is tested, not killing the process.
The empty root pin directory may remain after fixture cleanup.
"""
import hashlib
import os
import uuid

from hdm.delivery.device_filter_kernel import CgroupDeviceLink
from hdm.delivery.device_filter_pin_directory import FilterPinDirectory


class PinnedFixtureOwner:
    def __init__(self):
        self.kernel = CgroupDeviceLink()
        self.directory = FilterPinDirectory(create=True)
        self.token = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        self.expected = None
        self.pinned = False
        self.saved_program = None
        self.ownership_survived_fd_close = False
        self.pin_removed = False

    @property
    def link_fd(self):
        return self.kernel.link_fd

    def load(self, program):
        return self.kernel.load(program)

    def program_id(self):
        return self.saved_program if self.saved_program is not None else self.kernel.program_id()

    def query_program_ids(self, fd):
        return self.kernel.query_program_ids(fd)

    def attach(self, cgroup_fd):
        self.kernel.attach(cgroup_fd)
        self.expected = self.kernel.link_identity()
        self.saved_program = self.kernel.program_id()
        if self.expected.program_id != self.saved_program:
            raise ValueError("fixture program identity mismatch")
        self.kernel.pin(self.directory.fd, self.token, self.expected)
        self.pinned = True
        # Drop every program/link FD owned by this controller. Query does not
        # obtain a new link reference; the bpffs pin must keep it attached.
        self.kernel.close()
        self.ownership_survived_fd_close = self.saved_program in self.kernel.query_program_ids(cgroup_fd)
        if not self.ownership_survived_fd_close:
            raise ValueError("pin did not preserve attachment")
        self.kernel.recover(self.directory.fd, self.token, self.expected)

    def close_link(self):
        if not self.pinned:
            self.kernel.close_link()
            return
        if self.kernel.link_fd is None:
            try:
                self.kernel.recover(self.directory.fd, self.token, self.expected)
            except (ValueError, RuntimeError):
                self.kernel.recover_detached(self.directory.fd, self.token, self.expected)
        try:
            self.kernel.detach(self.expected)
        except (ValueError, RuntimeError):
            # A previously detached link cannot be active authority. Confirm
            # the exact inert identity using a fresh acquired descriptor.
            self.kernel.close()
            self.kernel.recover_detached(self.directory.fd, self.token, self.expected)
        self.kernel.close()
        self.kernel.recover_detached(self.directory.fd, self.token, self.expected)
        os.unlink(self.token, dir_fd=self.directory.fd)
        self.pinned = False
        self.pin_removed = True
        self.kernel.close()

    def close(self):
        try:
            self.close_link()
        finally:
            try:
                self.kernel.close()
            finally:
                self.directory.close()
