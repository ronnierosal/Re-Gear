"""Strict, read-only single-dock topology binding for the experimental writer.

This deliberately refuses cascades, multiple PCI consumers of one NHI, and
additional endpoint types. A firmware devlink establishes host association;
only the bounded one-branch/one-router topology is supported here. Fingerprints
are evidence, not authorization or cross-boot durable attachment generations.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import stat

from .whole_dock_writer import NodeIdentity, SysfsTarget

SYSFS_ROOT = Path("/sys")
_PCI = re.compile(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]")
_ROUTER = re.compile(r"\d+-[0-9a-f]+")
_DOMAIN = re.compile(r"domain\d+")
_LIMIT = 1024


class TopologyRefused(ValueError):
    pass


@dataclass(frozen=True)
class WholeDockBinding:
    gpu_bdf: str
    audio_bdf: str
    usb_bdf: str
    router_id: str
    usb_target: SysfsTarget
    router_target: SysfsTarget
    branch_target: SysfsTarget
    domain_target: SysfsTarget
    nhi_target: SysfsTarget
    pci_targets: tuple[SysfsTarget, ...]
    binding: str
    generation: str


def _children(path: Path) -> tuple[Path, ...]:
    entries = tuple(path.iterdir())
    if len(entries) > _LIMIT:
        raise TopologyRefused("dock_topology.inventory_excessive")
    return entries


def _read(path: Path) -> str:
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise TopologyRefused("dock_topology.attribute_invalid")
    with path.open("r", encoding="ascii") as source:
        value = source.read(129)
    if len(value) > 128:
        raise TopologyRefused("dock_topology.attribute_excessive")
    return value.strip()


def _canonical(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    root = SYSFS_ROOT / "devices"
    if root not in resolved.parents:
        raise TopologyRefused("dock_topology.path_outside_devices")
    return resolved


def _pin(path: Path) -> SysfsTarget:
    root = SYSFS_ROOT / "devices"
    parts = path.relative_to(root).parts
    paths = [root]
    for part in parts:
        paths.append(paths[-1] / part)
    identities = []
    for node in paths:
        observed = node.lstat()
        if not stat.S_ISDIR(observed.st_mode):
            raise TopologyRefused("dock_topology.anchor_not_directory")
        identities.append(NodeIdentity(observed.st_dev, observed.st_ino))
    return SysfsTarget(parts, tuple(identities))


def _path(target: SysfsTarget) -> Path:
    return (SYSFS_ROOT / "devices").joinpath(*target.parts)


def _pci_inventory() -> dict[str, Path]:
    found = {}
    for entry in _children(SYSFS_ROOT / "bus/pci/devices"):
        if not _PCI.fullmatch(entry.name):
            raise TopologyRefused("dock_topology.pci_name_invalid")
        path = _canonical(entry)
        if path.name != entry.name:
            raise TopologyRefused("dock_topology.pci_alias_mismatch")
        found[entry.name] = path
    return found


def _supplier_for(branch: Path) -> Path | None:
    links = [p for p in _children(branch) if p.name.startswith("supplier:")]
    if not links:
        return None
    if len(links) != 1 or not links[0].name.startswith("supplier:pci:"):
        raise TopologyRefused("dock_topology.supplier_ambiguous")
    link = links[0].resolve(strict=True)
    if link.parent != SYSFS_ROOT / "devices/virtual/devlink":
        raise TopologyRefused("dock_topology.devlink_invalid")
    if _canonical(link / "consumer") != branch:
        raise TopologyRefused("dock_topology.consumer_mismatch")
    supplier = _canonical(link / "supplier")
    if links[0].name != "supplier:pci:" + supplier.name:
        raise TopologyRefused("dock_topology.supplier_mismatch")
    return supplier


def _host_link(branch: Path, nhi: Path) -> None:
    if _supplier_for(branch) != nhi:
        raise TopologyRefused("dock_topology.host_changed")
    consumers = []
    for reference in _children(nhi):
        if not reference.name.startswith("consumer:"):
            continue
        if not reference.name.startswith("consumer:pci:"):
            raise TopologyRefused("dock_topology.host_consumer_unknown")
        link = reference.resolve(strict=True)
        if link.parent != SYSFS_ROOT / "devices/virtual/devlink":
            raise TopologyRefused("dock_topology.devlink_invalid")
        supplier = _canonical(link / "supplier")
        consumer = _canonical(link / "consumer")
        if (supplier != nhi or not _PCI.fullmatch(consumer.name)
                or reference.name != "consumer:pci:" + consumer.name):
            raise TopologyRefused("dock_topology.host_consumer_mismatch")
        if (consumer / ("supplier:pci:" + nhi.name)).resolve(strict=True) != link:
            raise TopologyRefused("dock_topology.consumer_backlink_mismatch")
        consumers.append(consumer)
    if consumers != [branch]:
        raise TopologyRefused("dock_topology.host_consumers_ambiguous")
    reverse = nhi / ("consumer:pci:" + branch.name)
    if reverse.resolve(strict=True) != (branch / ("supplier:pci:" + nhi.name)).resolve(strict=True):
        raise TopologyRefused("dock_topology.reverse_link_mismatch")


def _router_for(nhi: Path, *, down: bool = False) -> tuple[Path, Path]:
    domains = []
    routers = []
    for entry in _children(SYSFS_ROOT / "bus/thunderbolt/devices"):
        path = _canonical(entry)
        if _DOMAIN.fullmatch(entry.name) and path.parent == nhi:
            domains.append(path)
        if _ROUTER.fullmatch(entry.name):
            if path.name != entry.name:
                raise TopologyRefused("dock_topology.router_alias_mismatch")
            routers.append(path)
        elif (path / "authorized").exists():
            raise TopologyRefused("dock_topology.router_name_unknown")
    if len(domains) != 1:
        raise TopologyRefused("dock_topology.domain_ambiguous")
    domain = domains[0]
    if _read(domain / "deauthorization") != "1":
        raise TopologyRefused("dock_topology.deauthorization_unsupported")
    members = [p for p in routers if domain in p.parents]
    hosts = [p for p in members if p.parent == domain and p.name.endswith("-0")]
    external = [p for p in members if p not in hosts]
    if len(hosts) != 1 or len(external) != 1 or external[0].parent != hosts[0]:
        raise TopologyRefused("dock_topology.router_ambiguous")
    router = external[0]
    if _read(router / "authorized") != ("0" if down else "1"):
        raise TopologyRefused("dock_topology.authorization_changed")
    identity = _read(router / "unique_id")
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", identity):
        raise TopologyRefused("dock_topology.router_identity_invalid")
    return domain, router


def _fingerprint(paths: tuple[SysfsTarget, ...], router: Path) -> tuple[str, str]:
    identity = _read(router / "unique_id")
    binding = hashlib.sha256((repr(tuple(p.parts for p in paths)) + identity).encode()).hexdigest()
    generation = hashlib.sha256((binding + repr(tuple(p.identities for p in paths))).encode()).hexdigest()
    return binding, generation


def resolve_whole_dock(gpu_bdf: str) -> WholeDockBinding:
    """Capture a complete attachment while GPU/audio/USB are still present."""
    try:
        return _resolve(gpu_bdf)
    except (OSError, UnicodeError, RuntimeError) as error:
        raise TopologyRefused("dock_topology.observation_incomplete") from error


def _resolve(gpu_bdf: str) -> WholeDockBinding:
    if type(gpu_bdf) is not str or not _PCI.fullmatch(gpu_bdf):
        raise TopologyRefused("dock_topology.gpu_invalid")
    pci = _pci_inventory()
    gpu = pci.get(gpu_bdf)
    if gpu is None or _read(gpu / "class") not in ("0x030000", "0x030200"):
        raise TopologyRefused("dock_topology.gpu_missing")
    linked = []
    for ancestor in gpu.parents:
        if ancestor == SYSFS_ROOT / "devices":
            break
        if _PCI.fullmatch(ancestor.name):
            supplier = _supplier_for(ancestor)
            if supplier is not None:
                linked.append((ancestor, supplier))
    if len(linked) != 1:
        raise TopologyRefused("dock_topology.branch_unidentified")
    branch, nhi = linked[0]
    if (pci.get(branch.name) != branch or pci.get(nhi.name) != nhi
            or not re.fullmatch(r"pci[0-9a-f]{4}:[0-9a-f]{2}", branch.parent.name)
            or _read(branch / "class") != "0x060400" or branch in nhi.parents):
        raise TopologyRefused("dock_topology.host_link_invalid")
    _host_link(branch, nhi)
    domain, router = _router_for(nhi)
    descendants = [p for p in pci.values() if branch in p.parents]
    groups = {p.relative_to(branch).parts[0] for p in descendants}
    if len(groups) != 1:
        raise TopologyRefused("dock_topology.multiple_branches")
    gpu_nodes, audio_nodes, usb_nodes = [], [], []
    for path in descendants:
        category = _read(path / "class")
        if category in ("0x030000", "0x030200"):
            gpu_nodes.append(path)
        elif category == "0x040300":
            audio_nodes.append(path)
        elif category == "0x0c0330":
            usb_nodes.append(path)
        elif category != "0x060400":
            raise TopologyRefused("dock_topology.additional_endpoint")
    if (gpu_nodes != [gpu] or len(audio_nodes) != 1 or len(usb_nodes) != 1
            or audio_nodes[0].name.rsplit(".", 1)[0] != gpu_bdf.rsplit(".", 1)[0]
            or audio_nodes[0].parent != gpu.parent or usb_nodes[0] == nhi):
        raise TopologyRefused("dock_topology.functions_ambiguous")
    targets = tuple(_pin(p) for p in sorted(descendants))
    anchors = (_pin(branch), _pin(nhi), _pin(domain), _pin(router))
    binding, generation = _fingerprint(anchors, router)
    result = WholeDockBinding(gpu_bdf, audio_nodes[0].name, usb_nodes[0].name,
        router.name, _pin(usb_nodes[0]), anchors[3], anchors[0], anchors[2],
        anchors[1], targets, binding, generation)
    revalidate_retained(result)
    return result


def revalidate_retained(binding: WholeDockBinding, *, gpu_removed: bool = False,
                        usb_removed: bool = False, tunnel_down: bool = False) -> bool:
    """Check retained anchors and exact permitted disappearance; never clearance."""
    try:
        anchors = (binding.branch_target, binding.nhi_target,
                   binding.domain_target, binding.router_target)
        if any(_pin(_path(target)) != target for target in anchors):
            raise TopologyRefused("dock_topology.anchor_changed")
        branch, nhi, _, router = tuple(_path(t) for t in anchors)
        _host_link(branch, nhi)
        domain_now, router_now = _router_for(nhi, down=tunnel_down)
        if domain_now != _path(binding.domain_target) or router_now != router:
            raise TopologyRefused("dock_topology.router_changed")
        if _fingerprint(anchors, router) != (binding.binding, binding.generation):
            raise TopologyRefused("dock_topology.attachment_changed")
        pci = _pci_inventory()
        actual = {p for p in pci.values() if branch in p.parents}
        absent = ({binding.gpu_bdf, binding.audio_bdf} if gpu_removed else set())
        if usb_removed:
            absent.add(binding.usb_bdf)
        expected = {_path(t) for t in binding.pci_targets if t.parts[-1] not in absent}
        if tunnel_down:
            if actual:
                raise TopologyRefused("dock_topology.pci_branch_remains")
        else:
            if actual != expected:
                raise TopologyRefused("dock_topology.pci_inventory_changed")
            for target in binding.pci_targets:
                if target.parts[-1] not in absent and _pin(_path(target)) != target:
                    raise TopologyRefused("dock_topology.pci_identity_changed")
        return True
    except (OSError, UnicodeError, RuntimeError) as error:
        raise TopologyRefused("dock_topology.observation_incomplete") from error
