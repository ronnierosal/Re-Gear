"""Decide whether the rest of the dock may be taken down after the GPU.

A live disconnect today removes two PCI functions: the GPU and its audio. That
is enough to stop the eGPU rendering, and it is *not* enough to make the cable
safe to pull. The dock's own Thunderbolt USB controller sits on a sibling port
of the same switch, the bridges above it are still enumerated, and the tunnel
itself is still up. Unplugging then is a surprise removal of everything this
step never touched.

So this is the second half: bring the USB branch down, deauthorize the tunnel,
and verify both, so that what a player is told about the cable is a claim about
a dock that is actually detached rather than about a GPU that happens to be.

It is a far more dangerous operation than removing the GPU was, and for one
reason above all others: **the USB branch is where a player's files are.** A
mounted USB drive on the dock, removed with dirty pages outstanding, is data
loss with no recovery and no warning. The GPU branch had nothing comparable at
stake -- a lost frame is a lost frame.

Hence the rules, each of which refuses on its own:

- **storage in use is an absolute refusal**, never a warning to click through.
  A filesystem on this branch means the answer is no until the player unmounts
  it themselves. Re-Gear does not unmount anything to make a disconnect look
  possible, for the same reason it never force-closes a process to make one
  look safe;
- **and "unmounted" is not "unused".** A drive can be written to with no mount
  in sight: swap on it, a device-mapper or md layer stacked over it, or a
  filesystem mounted inside a container with its own mount namespace. Each of
  those refuses exactly as a mount does, because each of them means the device
  is being written to;
- **an unfinished scan is not an empty branch.** "Found no mounts" is evidence
  only when the looking finished. This codebase has had to remove that exact
  fail-open more than once, and here it would cost someone their save files
  rather than a prompt;
- **the GPU goes first.** Deauthorizing the tunnel while the GPU is still bound
  *is* the surprise removal invariant 10 forbids -- the same operation, reached
  from software instead of from the cable. Teardown is the last step or it is
  nothing;
- **an approval names what it approved.** A bare yes cannot say what was
  agreed to. Every substantive fact above is re-read on each decision, so a
  stale yes can never outvote them -- but the facts can still change into a
  *different* permitted teardown: another dock on the same cable, or the same
  dock with different things hanging off it. An answer given about one reading
  is not an answer about that one, so it is asked again;
- **the tunnel must be identified and deauthorizable before anything starts.**
  Taking the USB branch down and then discovering the tunnel cannot be brought
  down leaves the player with no dock USB, no clearance, and a recovery to
  perform. Refusing early costs them nothing.

Input, audio and network devices on the branch are **reported, not refused**.
They will disconnect and the player must be told so, but on a handheld the
built-in controller survives, so this is information they can act on rather
than a reason to override their decision.

Pure. It removes nothing, writes to no sysfs file and authorizes nothing.
Producing a permitted decision authorises one bounded teardown and nothing
else. It is **not** a finding that any cable may be pulled: that claim needs
this teardown to have actually run and been verified, and it needs the owner's
decision on issue #147, which is about whether invariant 10 covers one
operation or two.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class UsbBranchEvidence:
    """One reading of the dock's USB controller and what hangs off it.

    Every field carries its own completeness, because the failure this guards
    against is a reading that did not finish being taken for a reading that
    found nothing.
    """

    #: The dock's USB host controller, e.g. "0000:09:00.0".
    controller_bdf: str
    #: Whether that controller is still enumerated. False means this half of
    #: the teardown is already done.
    present: bool
    #: Whether the enumeration of the branch finished.
    scan_complete: bool
    #: Mount points backed by block devices on this branch. Any entry refuses.
    mounted_storage: tuple[str, ...] = ()
    #: Claims on those devices that are not mounts -- swap, stacked devices --
    #: described for a player. Any entry refuses exactly as a mount does.
    storage_in_use: tuple[str, ...] = ()
    #: Whether the search for both finished. False refuses on its own.
    storage_scan_complete: bool = False
    #: Input devices that will disconnect. Reported, never a refusal.
    input_devices: tuple[str, ...] = ()
    #: Audio, network and anything else that will disconnect with the branch.
    other_devices: tuple[str, ...] = ()


class TunnelCapability(StrEnum):
    """Whether the Thunderbolt domain supports de-authorizing a router at all.

    The kernel answers this on the domain, not on the router. It is a
    different question from whether this process may write the router's
    `authorized` file, and a different question again from whether the router
    is currently authorized -- and answering all three with one flag is how an
    unsupported dock and an under-privileged look became the same refusal.
    """

    SUPPORTED = "supported"
    NOT_SUPPORTED = "not_supported"
    UNKNOWN = "unknown"


class WritePermission(StrEnum):
    """Whether this process could write the router's `authorized` file.

    `UNKNOWN` covers the file being absent or unreadable. Absence is
    deliberately not read as `NOT_SUPPORTED`: support is the domain's answer,
    and inferring it from a missing file is the guess this type exists to
    stop.
    """

    WRITABLE = "writable"
    DENIED = "denied"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TunnelEvidence:
    """One reading of the Thunderbolt link the whole dock hangs from."""

    #: The thunderbolt sysfs id, e.g. "0-1". Empty when none was identified.
    sysfs_id: str
    #: Whether the link is authorized. None means it could not be read, which
    #: is not the same as "not authorized" and must not be treated as done.
    authorized: bool | None
    #: Whether the domain supports de-authorization. Asked before permission:
    #: whether the dock can do this at all outranks whether we may ask it to.
    capability: TunnelCapability
    #: Whether this process could write the router's `authorized` file.
    #: Checked before anything is torn down, so a failure costs nothing rather
    #: than half a dock.
    write_permission: WritePermission
    #: Whether the thunderbolt reading finished.
    scan_complete: bool


@dataclass(frozen=True, slots=True)
class TeardownApproval:
    """An operator's answer to one specific teardown, not to teardown as such.

    It names the dock the answer was given about and the disconnections the
    operator was actually shown. A later reading describing a different
    controller, a different tunnel, or a different set of things that will drop
    is a different question, and gets asked again rather than inheriting a yes.

    Deliberately not a token or a timestamp: the point is not that the answer
    is recent, it is that the answer is *about this*.
    """

    #: The USB controller named in the reading the operator was shown.
    controller_bdf: str
    #: The Thunderbolt router that same reading identified.
    tunnel_sysfs_id: str
    #: Exactly what the operator was told would disconnect.
    disconnecting: tuple[str, ...] = field(default_factory=tuple)

    def covers(
        self,
        usb: "UsbBranchEvidence",
        tunnel: "TunnelEvidence",
        disconnecting: tuple[str, ...],
    ) -> bool:
        """Whether this answer was given about the reading now in hand."""
        return (
            self.controller_bdf == usb.controller_bdf
            and self.tunnel_sysfs_id == tunnel.sysfs_id
            and tuple(self.disconnecting) == tuple(disconnecting)
        )


class DockTeardownState(StrEnum):
    #: The USB branch is gone and the tunnel is down. Nothing left to do.
    ALREADY_DOWN = "already_down"
    #: Every fact holds and the step is approved.
    PERMITTED = "permitted"
    #: A substantive fact refuses, and the code says which.
    REFUSED = "refused"
    #: The facts allow it but the step was not approved.
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True, slots=True)
class DockTeardownDecision:
    state: DockTeardownState
    code: str
    #: Mount points that must be unmounted first, when that is the blocker.
    #: Named so a player can act rather than hunt.
    blocking_mounts: tuple[str, ...] = field(default_factory=tuple)
    #: Non-mount claims that must end first: swap, stacked devices. Named for
    #: the same reason, and separate because the player clears them differently.
    blocking_uses: tuple[str, ...] = field(default_factory=tuple)
    #: What will disconnect if this proceeds. Not blockers; consequences.
    disconnecting: tuple[str, ...] = field(default_factory=tuple)

    @property
    def permitted(self) -> bool:
        return self.state is DockTeardownState.PERMITTED


def decide_dock_teardown(
    *,
    usb: UsbBranchEvidence,
    tunnel: TunnelEvidence,
    gpu_functions_present: tuple[str, ...],
    gpu_scan_complete: bool,
    approval: TeardownApproval | None = None,
) -> DockTeardownDecision:
    """Whether the USB branch and the tunnel may be brought down now.

    ``gpu_functions_present`` is the eGPU's own PCI functions that are still
    enumerated. It must be empty over a finished scan: teardown is what happens
    *after* a verified removal, and running it before one is the operation
    invariant 10 forbids rather than a faster route to the same place.

    Approval is checked last on purpose. A caller that has not approved still
    learns which substantive fact would have blocked it, which is what an
    operator working through a sequence needs.

    ``approval`` must have been given about *this* reading. Every substantive
    fact is re-read here, so a stale answer can never outvote one; what binding
    adds is that an answer cannot silently transfer to a different dock, or to
    the same dock with a different set of things about to be disconnected.
    """

    consequences = tuple(usb.input_devices) + tuple(usb.other_devices)

    # Completeness first, and for the GPU before anything else: a teardown that
    # cannot prove the GPU is gone cannot prove it is not a surprise removal.
    if not gpu_scan_complete:
        return DockTeardownDecision(
            DockTeardownState.REFUSED,
            "dock_teardown.gpu_scan_incomplete",
            disconnecting=consequences,
        )
    if gpu_functions_present:
        return DockTeardownDecision(
            DockTeardownState.REFUSED,
            "dock_teardown.gpu_still_attached",
            disconnecting=consequences,
        )

    if not tunnel.scan_complete:
        return DockTeardownDecision(
            DockTeardownState.REFUSED,
            "dock_teardown.tunnel_scan_incomplete",
            disconnecting=consequences,
        )
    if not tunnel.sysfs_id:
        return DockTeardownDecision(
            DockTeardownState.REFUSED,
            "dock_teardown.tunnel_unidentified",
            disconnecting=consequences,
        )

    if not usb.scan_complete:
        return DockTeardownDecision(
            DockTeardownState.REFUSED,
            "dock_teardown.usb_scan_incomplete",
            disconnecting=consequences,
        )

    if not usb.present and tunnel.authorized is False:
        return DockTeardownDecision(
            DockTeardownState.ALREADY_DOWN,
            "dock_teardown.already_down",
        )

    # The tunnel's own state has to be readable. Unknown is not down, and
    # acting as though it were would report a dock as detached on the strength
    # of a file that could not be read.
    if tunnel.authorized is None:
        return DockTeardownDecision(
            DockTeardownState.REFUSED,
            "dock_teardown.tunnel_state_unknown",
            disconnecting=consequences,
        )
    if tunnel.authorized:
        # All four are checked before anything comes down. Discovering any of
        # them afterwards leaves a player with no dock USB, no clearance, and
        # a recovery to perform; discovering it now costs them nothing.
        #
        # They used to be one refusal, which told an operator that the tunnel
        # could not be brought down without saying whether the dock cannot do
        # it, or we were not allowed to look. Those have different remedies
        # and one of them is not the operator's fault.
        if tunnel.capability is TunnelCapability.UNKNOWN:
            return DockTeardownDecision(
                DockTeardownState.REFUSED,
                "dock_teardown.tunnel_capability_unknown",
                disconnecting=consequences,
            )
        if tunnel.capability is TunnelCapability.NOT_SUPPORTED:
            return DockTeardownDecision(
                DockTeardownState.REFUSED,
                "dock_teardown.tunnel_capability_unsupported",
                disconnecting=consequences,
            )
        if tunnel.write_permission is WritePermission.UNKNOWN:
            return DockTeardownDecision(
                DockTeardownState.REFUSED,
                "dock_teardown.tunnel_write_permission_unknown",
                disconnecting=consequences,
            )
        if tunnel.write_permission is WritePermission.DENIED:
            return DockTeardownDecision(
                DockTeardownState.REFUSED,
                "dock_teardown.tunnel_write_permission_denied",
                disconnecting=consequences,
            )

    # Storage last among the refusals, because it is the one a player can
    # clear themselves and the one worth naming precisely.
    if usb.present:
        if not usb.storage_scan_complete:
            return DockTeardownDecision(
                DockTeardownState.REFUSED,
                "dock_teardown.storage_scan_incomplete",
                disconnecting=consequences,
            )
        if usb.mounted_storage:
            return DockTeardownDecision(
                DockTeardownState.REFUSED,
                "dock_teardown.mounted_storage",
                blocking_mounts=tuple(usb.mounted_storage),
                blocking_uses=tuple(usb.storage_in_use),
                disconnecting=consequences,
            )
        if usb.storage_in_use:
            # No mount, and in use all the same. Reported under its own code
            # because "unmount it" is not the instruction that clears swap or
            # a stacked device.
            return DockTeardownDecision(
                DockTeardownState.REFUSED,
                "dock_teardown.storage_in_use",
                blocking_uses=tuple(usb.storage_in_use),
                disconnecting=consequences,
            )

    if approval is None:
        return DockTeardownDecision(
            DockTeardownState.APPROVAL_REQUIRED,
            "dock_teardown.approval_required",
            disconnecting=consequences,
        )
    if not approval.covers(usb, tunnel, consequences):
        # The facts still permit a teardown -- just not the one that was agreed
        # to. Reported apart from a missing approval so that "you never
        # answered" and "you answered about something else" are not the same
        # event to anything downstream.
        return DockTeardownDecision(
            DockTeardownState.APPROVAL_REQUIRED,
            "dock_teardown.approval_superseded",
            disconnecting=consequences,
        )

    return DockTeardownDecision(
        DockTeardownState.PERMITTED,
        "dock_teardown.permitted",
        disconnecting=consequences,
    )
