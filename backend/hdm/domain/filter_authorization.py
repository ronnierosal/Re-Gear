"""Pure authorization contract for attaching a device filter at user scope.

`docs/FILTER_PRIMITIVES_INTEGRATION.md` states the constraint this module
exists to satisfy: the legacy `LaunchBinding` binds to two leaf services and
MUST NOT be treated as authorization for a user-manager ancestor attachment.
Parent-scope authorization needs a separately reviewed contract. This is that
contract, and it deliberately shares no type with the launch model.

Why the broader scope is needed at all: on the tested profile the eGPU's
holders sit in four different cgroups across `app.slice` and `session.slice`,
whose lowest common ancestor is `user@<uid>.service`. A program attached to a
leaf service applies to that cgroup and its descendants, so a leaf attachment
can never evaluate `wireplumber.service` or `pipewire.service`, which are
siblings. Coverage is the reason for the scope; it is not, on its own, a reason
to grant it.

What an authorization here establishes:

- the target is exactly the user manager of one explicitly identified uid, not
  an arbitrary cgroup path and not a leaf service;
- the cgroup is identified by device and inode as well as path, so a cgroup
  torn down and recreated under the same name does not inherit the grant;
- the grant is bound to the exact attachment and observation that justified it,
  and to the current boot;
- the grant expires, so a stalled owner cannot hold a broad scope indefinitely;
- the grant names its owner, because recovery has to be able to tell an owner
  that is still working from one that died.

That last point is the one the integration document is explicit about: an
unpinned link disappearing when its owner exits is not durable recovery. This
module supplies the identity a journal needs to distinguish those cases; it
does not itself journal, attach, or detach anything.

Pure: no I/O, no device or process action. Producing an authorization grants
nothing by itself.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum


#: The only cgroup shape this contract will authorize. Anything else, including
#: a leaf service under it, is refused rather than normalized.
USER_MANAGER_PATH = re.compile(
    r"/sys/fs/cgroup/user\.slice/user-(?P<uid>[1-9][0-9]{0,9})\.slice"
    r"/user@(?P<manager_uid>[1-9][0-9]{0,9})\.service"
)

HEX64 = re.compile(r"[0-9a-f]{64}")


def is_finite_time(value: object) -> bool:
    """Return whether `value` is a usable monotonic time.

    NaN and the infinities are floats that survive a `> 0` test but defeat
    every comparison afterwards: `now >= inf` and `now >= nan` are both
    always false, so either one as a deadline never expires, and a NaN clock
    reading defeats an otherwise valid finite deadline. Mirrors the finite
    requirement `hdm.delivery.device_filter_lifecycle` already applies.
    """
    return type(value) in (int, float) and math.isfinite(value)


class AuthorizationState(StrEnum):
    AUTHORIZED = "authorized"
    REFUSED = "refused"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class CgroupIdentity:
    """A cgroup identified by more than its path.

    systemd recreates a unit's cgroup on restart, which reuses the path but not
    the inode. Carrying both means a grant cannot survive the scope it was
    granted over being replaced underneath it.
    """

    path: str
    device: int
    inode: int

    def __post_init__(self) -> None:
        if type(self.device) is not int or self.device < 0:
            raise ValueError("cgroup device is invalid")
        if type(self.inode) is not int or self.inode <= 0:
            raise ValueError("cgroup inode is invalid")


@dataclass(frozen=True, slots=True)
class OwnerIdentity:
    """The process holding a grant, identified so death is detectable.

    A pid alone is not identity: pids are reused. The start time pins the
    instance, which is what lets recovery tell a live owner from a stale record.
    """

    pid: int
    start_time: int

    def __post_init__(self) -> None:
        if type(self.pid) is not int or self.pid <= 0:
            raise ValueError("owner pid is invalid")
        if type(self.start_time) is not int or self.start_time <= 0:
            raise ValueError("owner start time is invalid")


@dataclass(frozen=True, slots=True)
class ParentScopeAuthorization:
    """A bounded grant to attach a device filter at one user-manager cgroup."""

    state: AuthorizationState
    code: str
    cgroup: CgroupIdentity | None = None
    owner: OwnerIdentity | None = None
    uid: int = 0
    boot_hash: str = ""
    attachment_binding: str = ""
    generation: str = ""
    sample_id: str = ""
    deadline: float = 0.0

    def __post_init__(self) -> None:
        if self.state is AuthorizationState.AUTHORIZED:
            if self.cgroup is None or self.owner is None:
                raise ValueError("an authorized grant needs a cgroup and an owner")
            if not all(
                (
                    self.boot_hash,
                    self.attachment_binding,
                    self.generation,
                    self.sample_id,
                )
            ):
                raise ValueError("an authorized grant needs its binding evidence")
            if not is_finite_time(self.deadline) or self.deadline <= 0:
                # Repeated here because a grant can be reconstructed from a
                # store without passing back through the factory.
                raise ValueError("an authorized grant needs a finite deadline")
        elif self.cgroup is not None or self.owner is not None:
            raise ValueError("only an authorized grant exposes a target or owner")

    @property
    def granted(self) -> bool:
        return self.state is AuthorizationState.AUTHORIZED


def _refusal(code: str) -> ParentScopeAuthorization:
    return ParentScopeAuthorization(AuthorizationState.REFUSED, code)


def authorize_parent_scope(
    *,
    cgroup: CgroupIdentity,
    uid: int,
    session_uid: int,
    owner: OwnerIdentity,
    boot_hash: str,
    attachment_binding: str,
    generation: str,
    sample_id: str,
    deadline: float,
) -> ParentScopeAuthorization:
    """Authorize one user-manager cgroup as a filter attachment target.

    `session_uid` is the uid the Gamescope session was independently observed
    to run as. Requiring it to match the uid in the path is what stops a caller
    naming some other user's manager cgroup: the path alone is attacker-shaped
    input, and agreeing with itself proves nothing.
    """
    if type(cgroup) is not CgroupIdentity or type(owner) is not OwnerIdentity:
        return ParentScopeAuthorization(
            AuthorizationState.INVALID, "filter_authorization.input_invalid"
        )
    if any(type(value) is not int for value in (uid, session_uid)):
        return ParentScopeAuthorization(
            AuthorizationState.INVALID, "filter_authorization.input_invalid"
        )
    if not is_finite_time(deadline) or deadline <= 0:
        return ParentScopeAuthorization(
            AuthorizationState.INVALID, "filter_authorization.deadline_invalid"
        )
    if not HEX64.fullmatch(boot_hash):
        return ParentScopeAuthorization(
            AuthorizationState.INVALID, "filter_authorization.boot_hash_invalid"
        )
    if not all((attachment_binding, generation, sample_id)):
        return ParentScopeAuthorization(
            AuthorizationState.INVALID, "filter_authorization.observation_incomplete"
        )

    match = USER_MANAGER_PATH.fullmatch(cgroup.path)
    if match is None:
        # A leaf service path lands here too, deliberately: this contract does
        # not authorize leaf scopes, and silently accepting one would let a
        # caller obtain a narrower grant from the broader-scope path.
        return _refusal("filter_authorization.not_a_user_manager_cgroup")
    if int(match.group("uid")) != int(match.group("manager_uid")):
        return _refusal("filter_authorization.cgroup_path_inconsistent")
    if int(match.group("uid")) != uid:
        return _refusal("filter_authorization.uid_mismatch")
    if uid != session_uid:
        return _refusal("filter_authorization.not_the_session_user")

    return ParentScopeAuthorization(
        AuthorizationState.AUTHORIZED,
        "filter_authorization.authorized",
        cgroup,
        owner,
        uid,
        boot_hash,
        attachment_binding,
        generation,
        sample_id,
        deadline,
    )


def authorization_is_current(
    authorization: ParentScopeAuthorization,
    *,
    boot_hash: str,
    cgroup: CgroupIdentity,
    now: float,
) -> bool:
    """Return whether a grant still describes the scope it was granted over.

    Checked immediately before attaching, and again before any action taken on
    the strength of the attachment. A recreated cgroup, a different boot, or an
    expired deadline all mean the grant no longer describes reality.
    """
    if not authorization.granted or authorization.cgroup is None:
        return False
    if not is_finite_time(now) or now < 0:
        # An unusable clock reading cannot establish that a grant is still
        # current, and must not be allowed to pass the expiry comparison by
        # making it false.
        return False
    if not is_finite_time(authorization.deadline):
        return False
    if authorization.boot_hash != boot_hash:
        return False
    if now >= authorization.deadline:
        return False
    return (
        authorization.cgroup.path == cgroup.path
        and authorization.cgroup.device == cgroup.device
        and authorization.cgroup.inode == cgroup.inode
    )


def owner_is_live(
    authorization: ParentScopeAuthorization,
    *,
    observed_start_time: int | None,
) -> bool:
    """Return whether the recorded owner is still the running process.

    `observed_start_time` is the start time read for the recorded pid now, or
    None when no such process exists. A pid that has been reused reports a
    different start time, which reads as dead rather than live — the safe
    direction, since treating a stranger's process as the owner would leave a
    broad grant attributed to something that never asked for it.
    """
    if not authorization.granted or authorization.owner is None:
        return False
    if observed_start_time is None:
        return False
    return observed_start_time == authorization.owner.start_time
