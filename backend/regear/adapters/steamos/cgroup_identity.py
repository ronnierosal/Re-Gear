"""Read the identity of a session user's manager cgroup.

`regear.domain.filter_authorization` will only authorize a filter attachment to
the user manager of one explicitly identified uid, and it identifies that
cgroup by device and inode as well as by path, so a cgroup torn down and
recreated under the same name cannot inherit a grant. Nothing produced that
identity from a real system: `authorize_parent_scope` had no caller at all.

This reads it, and reads nothing else. The path is composed from the uid rather
than accepted from a caller, because a cgroup path is attacker-shaped input and
the domain refuses anything that is not this exact shape anyway.

The directory is opened without following symlinks and the identity is taken
from the open descriptor, so the answer describes the directory that was
actually opened rather than whatever the path resolved to a moment later. That
still leaves a gap between observing and attaching, which is closed on the
other side: `CgroupDeviceFilter.arm` compares the inode it opens against the
identity that authorized it and refuses a mismatch.

Reads; grants nothing. An identity is an observation, and producing one
authorizes no attachment by itself.
"""

from __future__ import annotations

import os
import stat
from typing import Callable

from ...domain.filter_authorization import CgroupIdentity


#: The only shape `filter_authorization` will authorize. Composed here rather
#: than accepted, so this adapter cannot be pointed at another user's manager.
USER_MANAGER = "/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service"


def user_manager_path(uid: int) -> str:
    """Return the user-manager cgroup path for `uid`."""
    if type(uid) is not int or uid <= 0:
        raise ValueError("session uid is invalid")
    return USER_MANAGER.format(uid=uid)


def observe_user_manager_cgroup(
    uid: int,
    *,
    open_directory: Callable[[str], int] | None = None,
    stat_fd: Callable[[int], os.stat_result] = os.fstat,
    close_fd: Callable[[int], None] = os.close,
) -> CgroupIdentity | None:
    """Return the identity of `uid`'s manager cgroup, or None if it is absent.

    None means the cgroup could not be read: it is missing, it is not a
    directory, or opening it failed. Callers treat that as a refusal to arm
    rather than as an empty scope -- `FilterArmCoordinator` maps a missing
    observation to a stale authorization, which is the conservative reading.
    """
    try:
        path = user_manager_path(uid)
    except ValueError:
        return None
    opener = open_directory or _open_directory
    try:
        descriptor = opener(path)
    except OSError:
        return None
    try:
        status = stat_fd(descriptor)
    except OSError:
        return None
    finally:
        close_fd(descriptor)
    if not stat.S_ISDIR(status.st_mode):
        return None
    try:
        return CgroupIdentity(path, status.st_dev, status.st_ino)
    except ValueError:
        # An inode of zero is not a cgroup this contract can identify.
        return None


def _open_directory(path: str) -> int:
    return os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
