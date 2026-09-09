"""Read the two identities a parent-scope filter grant is bound to.

`hdm.domain.filter_authorization` requires a grant to name its owner, so
recovery can tell a process that is still working from one that died, and to
be bound to the current boot, so a grant cannot survive a reboot. Neither had
a producer: `authorize_parent_scope` had no caller anywhere, which is why the
whole authorization path was unreachable from a real system.

A pid alone is not an owner. Pids are reused, so a record naming only a pid can
be matched by an unrelated process that happens to inherit the number later.
The start time pins the instance, and it comes from the same `/proc/<pid>/stat`
line as the pid so the two cannot describe different processes.

The boot id is hashed rather than stored. The grant only ever needs to answer
"is this the same boot", and the raw id is a stable machine identifier that has
no business travelling in a record or a log.

Reads; grants nothing. An identity is an observation, and producing one
authorizes no attachment by itself.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from ...domain.filter_authorization import OwnerIdentity


BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
PROC_ROOT = Path("/proc")

#: The kernel writes a lowercase UUID here. Anything else is not the file this
#: expects, and hashing it anyway would produce a plausible-looking grant bound
#: to nothing.
BOOT_ID_RE = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}")

#: `starttime` is field 22 of `/proc/<pid>/stat`. Fields 1 and 2 are the pid and
#: the comm, and comm is parenthesised and may itself contain spaces and
#: parentheses, so everything is counted from after the final `)`: field 3 is
#: index 0 there, which puts field 22 at index 19.
START_TIME_INDEX = 19


def read_boot_hash(path: Path = BOOT_ID) -> str:
    """Return the current boot id hashed, or "" when it cannot be read.

    An empty string is a refusal, not a value: `authorize_parent_scope` rejects
    anything that is not 64 hex characters, so an unreadable boot id produces a
    refused grant rather than one bound to nothing.
    """
    try:
        value = path.read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        return ""
    if not BOOT_ID_RE.fullmatch(value):
        return ""
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def observe_owner_identity(
    pid: int | None = None, *, proc_root: Path = PROC_ROOT
) -> OwnerIdentity | None:
    """Return the identity of `pid`, or None when it cannot be established.

    None whenever anything is off: the process is gone, its stat line cannot be
    read or parsed, or the pid on that line is not the one asked about. A caller
    treats that as a refusal to arm, which is the conservative reading -- an
    owner that cannot be identified cannot later be told apart from a dead one.
    """
    if pid is None:
        pid = os.getpid()
    if type(pid) is not int or pid <= 0:
        return None
    try:
        line = (proc_root / str(pid) / "stat").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None

    opening = line.find("(")
    closing = line.rfind(")")
    if opening < 0 or closing < opening:
        return None
    try:
        observed_pid = int(line[:opening].strip())
    except ValueError:
        return None
    if observed_pid != pid:
        # The line describes a different process than the one asked about, so
        # nothing on it can be attributed to this pid.
        return None

    fields = line[closing + 1 :].split()
    if len(fields) <= START_TIME_INDEX:
        return None
    try:
        start_time = int(fields[START_TIME_INDEX])
    except ValueError:
        return None
    try:
        return OwnerIdentity(pid, start_time)
    except ValueError:
        # A start time of zero is not an instance this can pin.
        return None
