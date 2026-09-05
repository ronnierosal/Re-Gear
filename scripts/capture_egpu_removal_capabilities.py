"""Read-only Thunderbolt removal research inventory; never authorizes unplug.

No PCI configuration reads, process termination, subprocesses or sysfs writes.
Router identity is inventory evidence, not a verified binding to a render GPU.
"""
import json
from pathlib import Path


def read(node):
    try:
        with node.open(encoding="ascii") as stream:
            value = stream.read(4097)
        return value.strip() if len(value) <= 4096 else None
    except (OSError, UnicodeError):
        return None


def flag(node):
    return {"0": False, "1": True}.get(read(node))


def collect(root=Path("/sys/bus/thunderbolt/devices")):
    result = {"read_only": True, "safe_to_unplug": False,
              "gpu_router_binding": "unverified", "domains": [], "routers": []}
    try:
        nodes = []
        for node in root.iterdir():
            nodes.append(node)
            if len(nodes) > 256:
                return {**result, "status": "inventory_limit"}
        resolved = {node: node.resolve(strict=True) for node in nodes}
    except (OSError, RuntimeError):
        return {**result, "status": "inventory_unavailable"}
    domains = {node: path for node, path in resolved.items()
               if node.name.startswith("domain") and node.name[6:].isdigit()}
    for node in sorted(domains):
        result["domains"].append({"name": node.name,
            "deauthorization_supported": flag(node / "deauthorization"),
            "security": read(node / "security"),
            "iommu_dma_protection": flag(node / "iommu_dma_protection")})
    for node, path in sorted(resolved.items()):
        if node in domains or not any((node / field).exists()
                                     for field in ("authorized", "unique_id", "device_name")):
            continue
        owners = [domain.name for domain, parent in domains.items()
                  if path.is_relative_to(parent)]
        result["routers"].append({"name": node.name,
            "domain": owners[0] if len(owners) == 1 else None,
            "authorized": flag(node / "authorized"),
            "vendor": read(node / "vendor"), "device": read(node / "device"),
            "device_name": read(node / "device_name"),
            "unique_id": read(node / "unique_id"),
            "nvm_version": read(node / "nvm_version")})
    # Detect disappearance/replacement during observation. This is not an atomic
    # snapshot, and even unchanged paths must never grant mutation authority.
    try:
        changed = any(node.resolve(strict=True) != path for node, path in resolved.items())
    except (OSError, RuntimeError):
        changed = True
    result["status"] = "inventory_changed" if changed else "observed"
    return result


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
