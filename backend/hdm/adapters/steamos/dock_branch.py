"""Read-only evidence about the dock's USB branch and its Thunderbolt tunnel.

Everything the teardown decision needs, and nothing it does not. This module
observes: it removes nothing, writes to no sysfs file, and deauthorizes
nothing. The act lives behind its own boundary so that reading the state of a
player's dock can never be the thing that changes it.

Two readings, and both carry their own completeness, because the decision that
consumes them refuses on an unfinished look rather than on an empty result. The
distinction is load-bearing here in a way it is not elsewhere: "no filesystem
is mounted on the dock" and "the search for mounted filesystems did not finish"
lead to opposite actions, and getting them confused costs somebody their files.

Mounts are read from `/proc/self/mountinfo` rather than from `mount` output or
`/etc/mtab`, because it is the kernel's own view, it needs no subprocess, and
it carries the major:minor of each mounted device -- which is what lets a mount
be tied to a block device on this branch rather than matched by name.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


PCI_PATTERN = re.compile(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]")
#: A USB device directory: "1-1", "1-1.2", "2-3.4.1".
USB_DEVICE_PATTERN = re.compile(r"\d+-\d+(?:\.\d+)*")
#: Interface classes worth naming to a player, from the USB class codes.
INTERFACE_CLASS_NAMES = {
    "01": "audio",
    "03": "input",
    "07": "printer",
    "08": "storage",
    "02": "network",
    "0a": "network",
    "e0": "wireless",
}
#: Bounds. A hostile or broken tree must not make an observation expensive.
MAX_USB_DEVICES = 128
MAX_DEPTH = 8


def _is_partition_of(leaf: str, disk: str) -> bool:
    """Whether `leaf` names a partition of the block device `disk`.

    The kernel spells this two ways and which one it uses is decided by the
    disk name itself. A name ending in a letter takes bare digits: "sda1" is a
    partition of "sda". A name already ending in a digit takes a "p" first:
    "nvme0n1p3" and "mmcblk0p1" -- and that separator is not optional, because
    without it "nvme0n12" would read as a partition of "nvme0n1" when it is
    namespace 12 of a different disk entirely.

    A bare prefix test gets both wrong. It matches "sdaa1" against "sda" and
    "nvme0n12" against "nvme0n1", each of which refuses a teardown over a drive
    that is not on the dock. That fails safe, but refusing for a reason a
    player cannot act on is its own kind of broken.
    """
    if not leaf.startswith(disk) or leaf == disk or not disk:
        return False
    suffix = leaf[len(disk):]
    if disk[-1].isdigit():
        if not suffix.startswith("p"):
            return False
        suffix = suffix[1:]
    return suffix.isdigit()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


@dataclass(frozen=True, slots=True)
class DockUsbDevice:
    """One thing plugged into the dock, as far as sysfs describes it."""

    sysfs_id: str
    #: From the device's own descriptors. Empty when it does not publish one.
    product: str
    manufacturer: str
    #: Interface classes it exposes, e.g. ("input",) or ("storage",).
    kinds: tuple[str, ...]

    @property
    def label(self) -> str:
        """A name for a player, never empty, never a raw sysfs path."""
        named = " ".join(part for part in (self.manufacturer, self.product) if part)
        return named or f"USB device {self.sysfs_id}"


@dataclass(frozen=True, slots=True)
class DockUsbReading:
    controller_bdf: str
    #: False when the controller is no longer enumerated at all.
    present: bool
    #: Whether walking the USB tree finished.
    complete: bool
    devices: tuple[DockUsbDevice, ...]


@dataclass(frozen=True, slots=True)
class DockStorageReading:
    #: Mount points backed by block devices on this branch.
    mounts: tuple[str, ...]
    #: Whether both the block-device walk and the mount read finished. False
    #: means an empty `mounts` proves nothing.
    complete: bool


@dataclass(frozen=True, slots=True)
class TunnelReading:
    sysfs_id: str
    authorized: bool | None
    deauthorizable: bool
    complete: bool


class DockBranchDiscovery:
    """Observe the dock's USB branch and its tunnel. Changes nothing."""

    def __init__(
        self,
        pci_root: Path = Path("/sys/bus/pci/devices"),
        thunderbolt_root: Path = Path("/sys/bus/thunderbolt/devices"),
        block_root: Path = Path("/sys/block"),
        mountinfo: Path = Path("/proc/self/mountinfo"),
    ) -> None:
        self._pci_root = pci_root
        self._thunderbolt_root = thunderbolt_root
        self._block_root = block_root
        self._mountinfo = mountinfo

    # -- the USB branch ---------------------------------------------------

    def observe_usb(self, controller_bdf: str) -> DockUsbReading:
        """What is plugged into the dock's USB controller right now."""
        if not PCI_PATTERN.fullmatch(controller_bdf):
            return DockUsbReading(controller_bdf, False, False, ())
        controller = self._pci_root / controller_bdf
        try:
            if not controller.is_dir():
                # Not enumerated. This half of the teardown is already done,
                # and that is a finished reading rather than a failed one.
                return DockUsbReading(controller_bdf, False, True, ())
        except OSError:
            return DockUsbReading(controller_bdf, False, False, ())

        devices: list[DockUsbDevice] = []
        complete = True
        try:
            roots = [
                entry
                for entry in sorted(controller.iterdir(), key=lambda item: item.name)
                if entry.name.startswith("usb") and entry.is_dir()
            ]
        except OSError:
            return DockUsbReading(controller_bdf, True, False, ())

        for root in roots:
            found, ok = self._walk_usb(root, depth=0, budget=MAX_USB_DEVICES - len(devices))
            devices.extend(found)
            complete = complete and ok
        return DockUsbReading(
            controller_bdf, True, complete, tuple(devices[:MAX_USB_DEVICES])
        )

    def _walk_usb(
        self, directory: Path, *, depth: int, budget: int
    ) -> tuple[list[DockUsbDevice], bool]:
        if depth > MAX_DEPTH or budget <= 0:
            # Truncated rather than exhaustive, and said so: a partial list is
            # not evidence that nothing else is attached.
            return [], False
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError:
            return [], False
        found: list[DockUsbDevice] = []
        complete = True
        for entry in entries:
            if not USB_DEVICE_PATTERN.fullmatch(entry.name):
                continue
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                complete = False
                continue
            found.append(self._describe_usb(entry))
            nested, ok = self._walk_usb(
                entry, depth=depth + 1, budget=budget - len(found)
            )
            found.extend(nested)
            complete = complete and ok
            if len(found) >= budget:
                return found[:budget], False
        return found, complete

    def _describe_usb(self, directory: Path) -> DockUsbDevice:
        kinds: list[str] = []
        try:
            for entry in sorted(directory.iterdir(), key=lambda item: item.name):
                # Interfaces are named "1-1:1.0" and carry the class code.
                if ":" not in entry.name:
                    continue
                code = _read_text(entry / "bInterfaceClass").lower()
                name = INTERFACE_CLASS_NAMES.get(code)
                if name and name not in kinds:
                    kinds.append(name)
        except OSError:
            pass
        return DockUsbDevice(
            directory.name,
            _read_text(directory / "product"),
            _read_text(directory / "manufacturer"),
            tuple(kinds),
        )

    # -- storage on that branch -------------------------------------------

    def observe_storage(self, controller_bdf: str) -> DockStorageReading:
        """Mount points backed by block devices behind this controller.

        Both halves must finish for the result to mean anything: the walk that
        finds this branch's block devices, and the read that maps them to
        mounts. Either failing reports incomplete, and the decision that
        consumes this refuses rather than reading an empty list as safety.
        """
        if not PCI_PATTERN.fullmatch(controller_bdf):
            return DockStorageReading((), False)
        try:
            if not (self._pci_root / controller_bdf).is_dir():
                # No controller, so nothing of this branch is mounted. A
                # finished reading of an absent thing.
                return DockStorageReading((), True)
        except OSError:
            return DockStorageReading((), False)

        devices, devices_complete = self._branch_block_devices(controller_bdf)
        mounts, mounts_complete = self._mounts_for(devices)
        return DockStorageReading(mounts, devices_complete and mounts_complete)

    def _branch_block_devices(self, controller_bdf: str) -> tuple[set[str], bool]:
        """Block device names whose sysfs path runs through this controller."""
        try:
            entries = sorted(self._block_root.iterdir(), key=lambda item: item.name)
        except OSError:
            return set(), False
        names: set[str] = set()
        complete = True
        for entry in entries:
            try:
                resolved = entry.resolve(strict=True)
            except OSError:
                # A device that vanished mid-walk cannot be mounted from this
                # branch a moment later, but it also was not examined.
                complete = False
                continue
            # Compared as path components rather than as a substring: a
            # controller address is a whole segment, and matching it inside a
            # longer name would attribute another branch's disk to this one.
            if controller_bdf in resolved.parts:
                names.add(entry.name)
        return names, complete

    def _mounts_for(self, devices: set[str]) -> tuple[tuple[str, ...], bool]:
        """Mount points whose source device is one of, or part of, `devices`."""
        if not devices:
            return (), True
        try:
            raw = self._mountinfo.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return (), False
        mounts: list[str] = []
        for line in raw.splitlines():
            fields = line.split(" ")
            if len(fields) < 5:
                continue
            mount_point = fields[4]
            separator = fields.index("-") if "-" in fields else -1
            source = fields[separator + 2] if separator >= 0 and len(fields) > separator + 2 else ""
            leaf = source.rsplit("/", 1)[-1]
            if not leaf:
                continue
            # sysfs names the disk; mountinfo names the partition mounted from
            # it. Matching on a bare prefix would also match "sdaa1" against
            # "sda", so the remainder has to look like a partition suffix.
            if leaf in devices or any(
                _is_partition_of(leaf, name) for name in devices
            ):
                mounts.append(mount_point)
        return tuple(sorted(set(mounts))), True

    # -- the tunnel -------------------------------------------------------

    def observe_tunnel(self, device_name: str) -> TunnelReading:
        """The dock's Thunderbolt router, by the name it publishes.

        `authorized` of None means the file could not be read, which is not the
        same fact as "not authorized" and must never be collapsed into it: one
        says the tunnel is down, the other says nothing at all.
        """
        try:
            entries = sorted(
                self._thunderbolt_root.iterdir(), key=lambda item: item.name
            )
        except OSError:
            return TunnelReading("", None, False, False)
        wanted = device_name.casefold()
        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                return TunnelReading("", None, False, False)
            if _read_text(entry / "device_name").casefold() != wanted:
                continue
            authorized_file = entry / "authorized"
            raw = _read_text(authorized_file)
            authorized = None if raw not in ("0", "1") else raw == "1"
            return TunnelReading(
                entry.name,
                authorized,
                self._writable(authorized_file),
                True,
            )
        # The walk finished and found no such router. That is a real answer:
        # the dock is not attached by this name.
        return TunnelReading("", None, False, True)

    @staticmethod
    def _writable(path: Path) -> bool:
        try:
            return path.is_file() and os.access(path, os.W_OK)
        except OSError:
            return False
