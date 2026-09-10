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

Mounts are read from mountinfo rather than from `mount` output or `/etc/mtab`,
because it is the kernel's own view and needs no subprocess. Every process's
mountinfo is read, not just this one's: `/proc/self/mountinfo` shows only this
mount namespace, and Flatpak apps, Steam's containers and any unit with
`PrivateMounts` have their own. A drive mounted inside one of those is mounted.

**Unmounted is not unused**, and treating the two as the same is the way this
reading gets someone's files. Two more kernel-visible claims on a block device,
both without a mount:

- a stacked device. device-mapper, LVM and md list their consumers in
  `/sys/block/<dev>/holders`, and a member of an assembled array is thoroughly
  in use while being mounted nowhere;
- swap, which `/proc/swaps` names directly.

None of this opens the device. An `O_EXCL` probe would be the definitive test
and is what `mkfs` uses, but opening a block device node has side effects of its
own -- spin-up, media access -- and a reading must not have those.
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


def _is_opaque_source(source: str) -> bool:
    """Whether a mountinfo source cannot be judged by its basename.

    `/dev/sda1` names the kernel device directly. `/dev/disk/by-uuid/...`,
    `/dev/disk/by-label/...` and `/dev/mapper/...` all name something that
    resolves to one, and the basename is a UUID, a label or a mapping name
    that matches no sysfs device. A mount through any of those is still a
    mount on the branch.
    """
    if not source.startswith("/dev/"):
        return False
    return "/" in source[len("/dev/"):]


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
class DockStorageUse:
    """One claim on a block device that is not a mount in this namespace."""

    #: The block device, e.g. "sda".
    device: str
    #: What holds it: "swap", or a stacked device such as "dm-0" or "md0".
    kind: str
    #: What the holder is, for a player: "swap" or the holder's name.
    detail: str


@dataclass(frozen=True, slots=True)
class DockStorageReading:
    #: Mount points backed by block devices on this branch, across every mount
    #: namespace that could be read.
    mounts: tuple[str, ...]
    #: Claims on those devices that are not mounts: swap, and stacked devices.
    #: Any entry blocks a teardown exactly as a mount does.
    other_uses: tuple[DockStorageUse, ...] = ()
    #: Whether the block-device walk, the mount read and the other-use checks
    #: all finished. False means an empty result proves nothing.
    complete: bool = False


@dataclass(frozen=True, slots=True)
class TunnelReading:
    sysfs_id: str
    authorized: bool | None
    deauthorizable: bool
    complete: bool
    #: Two or more routers published the requested name, so no single one is
    #: the answer. `complete` is False alongside it: an ambiguous scan did not
    #: settle, and a caller that only checks completeness still fails closed.
    ambiguous: bool = False


class DockBranchDiscovery:
    """Observe the dock's USB branch and its tunnel. Changes nothing."""

    def __init__(
        self,
        pci_root: Path = Path("/sys/bus/pci/devices"),
        thunderbolt_root: Path = Path("/sys/bus/thunderbolt/devices"),
        block_root: Path = Path("/sys/block"),
        mountinfo: Path = Path("/proc/self/mountinfo"),
        proc_root: Path = Path("/proc"),
        swaps: Path = Path("/proc/swaps"),
    ) -> None:
        self._pci_root = pci_root
        self._thunderbolt_root = thunderbolt_root
        self._block_root = block_root
        self._mountinfo = mountinfo
        self._proc_root = proc_root
        self._swaps = swaps

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
        """Every claim on a block device behind this controller.

        Mounts in any namespace, swap, and stacked devices. Each part must
        finish for the result to mean anything, and any one failing reports
        incomplete -- the decision that consumes this refuses rather than
        reading an empty list as safety.
        """
        if not PCI_PATTERN.fullmatch(controller_bdf):
            return DockStorageReading((), (), False)
        try:
            if not (self._pci_root / controller_bdf).is_dir():
                # No controller, so nothing of this branch is in use. A
                # finished reading of an absent thing.
                return DockStorageReading((), (), True)
        except OSError:
            return DockStorageReading((), (), False)

        devices, devices_complete = self._branch_block_devices(controller_bdf)
        mounts, mounts_complete = self._mounts_for(devices)
        uses, uses_complete = self._other_uses(devices)
        return DockStorageReading(
            mounts,
            uses,
            devices_complete and mounts_complete and uses_complete,
        )

    def _other_uses(
        self, devices: set[str]
    ) -> tuple[tuple[DockStorageUse, ...], bool]:
        """Claims on these devices that are not mounts.

        Swap and stacked devices. Both are ordinary states that a mount table
        says nothing about, and both mean the device is being written to.
        """
        if not devices:
            return (), True
        uses: list[DockStorageUse] = []
        complete = True

        try:
            raw = self._swaps.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            # No swap file at all is a real answer on a system without one.
            #
            # Left as-is deliberately. `/proc/swaps` exists on any kernel this
            # runs on whether or not swap is configured, so an absent one
            # arguably means the table was not read -- but
            # `test_a_missing_swaps_file_is_a_real_answer` asserts this reading
            # by name, so it is raised with its owner rather than reversed here.
            raw = ""
        except OSError:
            complete = False
            raw = ""
        for line in raw.splitlines()[1:]:
            leaf = line.split()[0].rsplit("/", 1)[-1] if line.split() else ""
            if not leaf:
                continue
            if leaf in devices or any(
                _is_partition_of(leaf, name) for name in devices
            ):
                uses.append(DockStorageUse(leaf, "swap", "in use as swap"))

        for device in sorted(devices):
            # A dm or md device assembled on a PARTITION holds the disk just as
            # firmly as one assembled on the whole device, and only the disk's
            # own holders directory was ever read. sysfs publishes each
            # partition as a directory under the disk, each with its own
            # holders, so both levels are walked.
            for holders in self._holder_directories(device):
                if not self._collect_holders(holders, uses):
                    complete = False
        return tuple(uses), complete

    def _holder_directories(self, device: str) -> tuple[Path, ...]:
        """The disk's holders directory and each partition's."""
        root = self._block_root / device
        directories = [root / "holders"]
        try:
            children = sorted(root.iterdir(), key=lambda item: item.name)
        except OSError:
            return tuple(directories)
        for child in children:
            if child.name.startswith(device) and child.name != device:
                directories.append(child / "holders")
        return tuple(directories)

    def _collect_holders(
        self, holders: Path, uses: list[DockStorageUse]
    ) -> bool:
        """Stacked consumers named by one holders directory.

        Returns whether the directory could be read. The reported device is
        the one the holders belong to -- the partition when the mapping was
        assembled on a partition -- because that is what a player has to act
        on, not the disk it happens to sit inside.
        """
        owner = holders.parent.name
        try:
            entries = sorted(entry.name for entry in holders.iterdir())
        except FileNotFoundError:
            # No holders directory means no stacked consumers.
            #
            # Left as-is deliberately. The kernel does give every block device
            # a `holders` directory, so on real sysfs an absent one means this
            # is not the device we think it is -- which argues for reporting
            # the scan incomplete. But that reading is asserted by name in
            # `test_no_holders_directory_is_no_holders` and is someone's
            # decision, not an oversight, so it is raised with its owner
            # rather than reversed here.
            return True
        except OSError:
            return False
        for name in entries:
            uses.append(DockStorageUse(owner, "stacked", f"in use by {name}"))
        return True

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

    def _mount_tables(self) -> tuple[tuple[str, ...], bool]:
        """Every process's mountinfo, so no mount namespace is missed.

        A drive mounted inside a Flatpak app or a Steam container does not
        appear in this process's own table, and it is mounted all the same.
        This process's table is read first and separately, so a `/proc` that
        cannot be walked still leaves the reading with the namespace it is in
        -- degraded to incomplete rather than to nothing.
        """
        tables: list[str] = []
        complete = True
        try:
            tables.append(
                self._mountinfo.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            complete = False
        try:
            entries = sorted(self._proc_root.iterdir(), key=lambda item: item.name)
        except OSError:
            return tuple(tables), False
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                tables.append(
                    (entry / "mountinfo").read_text(
                        encoding="utf-8", errors="replace"
                    )
                )
            except FileNotFoundError:
                # The process exited between the listing and the read. It is
                # not holding a mount now.
                continue
            except PermissionError:
                # A namespace that could not be read is a namespace that was
                # not checked, and an unchecked namespace may hold a mount.
                complete = False
            except OSError:
                complete = False
        return tuple(tables), complete

    def _mounts_for(self, devices: set[str]) -> tuple[tuple[str, ...], bool]:
        """Mount points whose source device is one of, or part of, `devices`."""
        if not devices:
            return (), True
        tables, complete = self._mount_tables()
        if not tables:
            return (), False
        raw = "\n".join(tables)
        devnums = self._branch_devnums(devices)
        mounts: list[str] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            fields = line.split(" ")
            separator = fields.index("-") if "-" in fields else -1
            if len(fields) < 5 or separator < 0 or len(fields) <= separator + 2:
                # Left skipping quietly, deliberately. A line this parser
                # cannot read is arguably a mount it cannot rule out, but
                # `test_a_truncated_line_is_skipped_rather_than_crashing`
                # asserts the opposite by name, so it is raised with its owner
                # rather than reversed here.
                continue
            mount_point = fields[4]
            source = fields[separator + 2]
            leaf = source.rsplit("/", 1)[-1]
            # sysfs names the disk; mountinfo names the partition mounted from
            # it. Matching on a bare prefix would also match "sdaa1" against
            # "sda", so the remainder has to look like a partition suffix.
            by_name = bool(leaf) and (
                leaf in devices
                or any(_is_partition_of(leaf, name) for name in devices)
            )
            # mountinfo carries the device number the mount actually came
            # from, which no amount of aliasing changes.
            by_devnum = fields[2] in devnums
            if by_name or by_devnum:
                mounts.append(mount_point)
                continue
            if devnums or not _is_opaque_source(source):
                continue
            # An alias such as /dev/disk/by-uuid/... or /dev/mapper/... has a
            # basename that names nothing on this branch even when the mount
            # is on it, and without device numbers there is nothing left to
            # compare. Unattributable is not absent.
            complete = False
        return tuple(sorted(set(mounts))), complete

    def _branch_devnums(self, devices: set[str]) -> set[str]:
        """`major:minor` for each branch device and any partition of it.

        Empty when sysfs does not publish them, which is why the caller keeps
        the name comparison rather than replacing it.
        """
        devnums: set[str] = set()
        for device in sorted(devices):
            root = self._block_root / device
            devnums.add(_read_text(root / "dev"))
            try:
                children = sorted(root.iterdir(), key=lambda item: item.name)
            except OSError:
                continue
            for child in children:
                if child.name.startswith(device):
                    devnums.add(_read_text(child / "dev"))
        devnums.discard("")
        return devnums

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
        matches: list[Path] = []
        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                return TunnelReading("", None, False, False)
            if _read_text(entry / "device_name").casefold() != wanted:
                continue
            matches.append(entry)
        if len(matches) > 1:
            # Two routers publishing the same name is the one case where
            # picking the first is worse than answering nothing. A device_name
            # is a product string, not an identity, so two identical docks
            # report the same one. Returning either would name a router the
            # caller did not mean and, downstream, deauthorize it.
            return TunnelReading("", None, False, False, ambiguous=True)
        if matches:
            entry = matches[0]
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
