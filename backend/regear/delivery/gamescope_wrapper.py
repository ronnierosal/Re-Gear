"""Boot-scoped Gamescope argument shim with fail-closed portable fallback."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REAL_GAMESCOPE = "/usr/bin/gamescope"
CONFIG_FILENAME = "presentation.json"
MAX_CONFIG_BYTES = 4096
CONNECTOR_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
VENDOR_DEVICE_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_FIELDS = frozenset(
    {
        "schema_version",
        "boot_id_sha256",
        "target",
        "internal_connector",
        "external_connector",
        "vendor_device",
        "egpu_binding_sha256",
    }
)


@dataclass(frozen=True, slots=True)
class GamescopeLaunchConfig:
    boot_id_sha256: str
    target: str
    internal_connector: str
    external_connector: str = ""
    vendor_device: str = ""
    egpu_binding_sha256: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not SHA256_RE.fullmatch(self.boot_id_sha256):
            raise ValueError("Gamescope launch config identity is invalid")
        if self.target not in {"portable", "docked_igpu", "docked_egpu"}:
            raise ValueError("Gamescope launch target is invalid")
        if not CONNECTOR_RE.fullmatch(self.internal_connector):
            raise ValueError("internal connector is invalid")
        if self.target in {"docked_igpu", "docked_egpu"}:
            if (
                not CONNECTOR_RE.fullmatch(self.external_connector)
                or self.external_connector == self.internal_connector
            ):
                raise ValueError("docked Gamescope launch target is incomplete")
            if not VENDOR_DEVICE_RE.fullmatch(self.vendor_device):
                raise ValueError("docked Gamescope launch target is incomplete")
            if not SHA256_RE.fullmatch(self.egpu_binding_sha256):
                raise ValueError("docked Gamescope launch identity is incomplete")
        elif (
            self.external_connector
            or self.vendor_device
            or self.egpu_binding_sha256
        ):
            raise ValueError("portable Gamescope launch cannot select an eGPU")


def config_to_dict(value: GamescopeLaunchConfig) -> dict[str, Any]:
    return {
        "schema_version": value.schema_version,
        "boot_id_sha256": value.boot_id_sha256,
        "target": value.target,
        "internal_connector": value.internal_connector,
        "external_connector": value.external_connector,
        "vendor_device": value.vendor_device,
        "egpu_binding_sha256": value.egpu_binding_sha256,
    }


def config_from_dict(value: dict[str, Any]) -> GamescopeLaunchConfig:
    if set(value) != ALLOWED_FIELDS:
        raise ValueError("Gamescope launch config shape is invalid")
    if type(value["schema_version"]) is not int or any(
        not isinstance(value[field], str)
        for field in ALLOWED_FIELDS - {"schema_version"}
    ):
        raise ValueError("Gamescope launch config field type is invalid")
    return GamescopeLaunchConfig(
        schema_version=int(value["schema_version"]),
        boot_id_sha256=str(value["boot_id_sha256"]),
        target=str(value["target"]),
        internal_connector=str(value["internal_connector"]),
        external_connector=str(value["external_connector"]),
        vendor_device=str(value["vendor_device"]),
        egpu_binding_sha256=str(value["egpu_binding_sha256"]),
    )


def rewrite_gamescope_argv(
    argv: tuple[str, ...],
    *,
    output_order: str,
    vendor_device: str = "",
) -> tuple[str, ...]:
    if output_order:
        parts = output_order.split(",")
        valid_output = (
            len(parts) == 1 and bool(CONNECTOR_RE.fullmatch(parts[0]))
        ) or (
            len(parts) == 2
            and parts[0] == "*"
            and bool(CONNECTOR_RE.fullmatch(parts[1]))
        )
        if not valid_output:
            raise ValueError("Gamescope output order is invalid")
    if vendor_device and not VENDOR_DEVICE_RE.fullmatch(vendor_device):
        raise ValueError("Gamescope render selector is invalid")
    rewritten: list[str] = []
    tail: tuple[str, ...] = ()
    index = 0
    output_written = False
    while index < len(argv):
        item = argv[index]
        if item == "--":
            tail = argv[index:]
            break
        if item in {"-O", "--prefer-output"}:
            if index + 1 >= len(argv):
                raise ValueError("Gamescope output argument is incomplete")
            if output_order and not output_written:
                rewritten.extend((item, output_order))
                output_written = True
            elif not output_order:
                rewritten.extend((item, argv[index + 1]))
            index += 2
            continue
        if item.startswith("--prefer-output="):
            index += 1
            if output_order and not output_written:
                rewritten.append(f"--prefer-output={output_order}")
                output_written = True
            elif not output_order:
                rewritten.append(item)
            continue
        if item == "--prefer-vk-device":
            if index + 1 >= len(argv):
                raise ValueError("Gamescope render argument is incomplete")
            index += 2
            continue
        if item.startswith("--prefer-vk-device="):
            index += 1
            continue
        rewritten.append(item)
        index += 1
    if output_order and not output_written:
        rewritten.extend(("-O", output_order))
    if vendor_device:
        rewritten.extend(("--prefer-vk-device", vendor_device))
    rewritten.extend(tail)
    return tuple(rewritten)


def select_launch_configuration(
    config: GamescopeLaunchConfig | None,
    *,
    current_boot_id_sha256: str,
    connected_connectors: tuple[str, ...],
    internal_connectors: tuple[str, ...],
    present_vendor_devices: tuple[str, ...],
    verified_egpu_binding_sha256: str = "",
) -> tuple[str, str]:
    connected = tuple(dict.fromkeys(connected_connectors))
    internal = tuple(
        item for item in dict.fromkeys(internal_connectors) if item in connected
    )
    if (
        config is not None
        and config.boot_id_sha256 == current_boot_id_sha256
        and config.target == "docked_egpu"
        and connected.count(config.external_connector) == 1
        and config.external_connector not in internal
        and present_vendor_devices.count(config.vendor_device) == 1
        and verified_egpu_binding_sha256 == config.egpu_binding_sha256
    ):
        return config.external_connector, config.vendor_device
    if (
        config is not None
        and config.boot_id_sha256 == current_boot_id_sha256
        and config.target == "docked_igpu"
        and connected.count(config.external_connector) == 1
        and config.external_connector not in internal
        and present_vendor_devices.count(config.vendor_device) == 1
        and verified_egpu_binding_sha256 == config.egpu_binding_sha256
    ):
        return config.external_connector, config.vendor_device
    if (
        config is not None
        and config.boot_id_sha256 == current_boot_id_sha256
        and config.target == "docked_igpu"
        and connected.count(config.internal_connector) == 1
        and config.internal_connector in internal
        and present_vendor_devices.count(config.vendor_device) == 1
        and verified_egpu_binding_sha256 == config.egpu_binding_sha256
    ):
        return f"*,{config.internal_connector}", config.vendor_device
    if (
        config is not None
        and config.boot_id_sha256 == current_boot_id_sha256
        and config.target == "portable"
        and connected.count(config.internal_connector) == 1
        and config.internal_connector in internal
    ):
        return f"*,{config.internal_connector}", ""
    if len(internal) == 1:
        return f"*,{internal[0]}", ""
    return "", ""


def _boot_identity() -> tuple[str, str]:
    value = Path("/proc/sys/kernel/random/boot_id").read_text(
        encoding="utf-8", errors="strict"
    ).strip()
    return value, hashlib.sha256(value.encode("utf-8")).hexdigest()


def _connected_connectors(root: Path = Path("/sys/class/drm")) -> tuple[str, ...]:
    values: list[str] = []
    try:
        entries = tuple(root.iterdir())
    except OSError:
        return ()
    for entry in entries:
        if "-" not in entry.name:
            continue
        try:
            status = (entry / "status").read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except OSError:
            continue
        if status == "connected":
            values.append(entry.name.split("-", 1)[1])
    return tuple(values)


def _internal_connectors(values: tuple[str, ...]) -> tuple[str, ...]:
    prefixes = ("eDP-", "DSI-", "LVDS-")
    return tuple(value for value in values if value.startswith(prefixes))


def _present_vendor_devices(
    root: Path = Path("/sys/bus/pci/devices"),
) -> tuple[str, ...]:
    values: list[str] = []
    try:
        entries = tuple(root.iterdir())
    except OSError:
        return ()
    for entry in entries:
        try:
            vendor = (entry / "vendor").read_text(encoding="ascii").strip()
            device = (entry / "device").read_text(encoding="ascii").strip()
        except OSError:
            continue
        value = f"{vendor.removeprefix('0x')}:{device.removeprefix('0x')}".casefold()
        if VENDOR_DEVICE_RE.fullmatch(value):
            values.append(value)
    return tuple(values)


def _verified_egpu_binding_sha256(boot_id: str) -> str:
    """Re-resolve the exact private G1 identity immediately before Gamescope exec."""

    try:
        from ..adapters.steamos.drm import DrmDiscovery
        from ..adapters.steamos.pci import PciUsb4Discovery
        from ..profiles.gpd_g1 import match_gpd_g1

        topology = PciUsb4Discovery()
        matched = match_gpd_g1(
            DrmDiscovery().scan(),
            topology.scan_pci(),
            topology.scan_usb4(),
        )
    except Exception:
        return ""
    if not matched.verified or not boot_id:
        return ""
    material = f"{boot_id}:{matched.stable_id}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _load_config(state_root: Path) -> GamescopeLaunchConfig | None:
    try:
        if state_root.is_symlink() or not state_root.is_dir():
            return None
        target = state_root / CONFIG_FILENAME
        if target.is_symlink():
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags)
        with os.fdopen(descriptor, "rb") as source:
            raw = source.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            return None
        value = json.loads(raw.decode("utf-8"))
        return config_from_dict(value) if isinstance(value, dict) else None
    except (OSError, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        return None


def main() -> int:
    state_value = os.environ.get("HDM_STATE_ROOT", "")
    state_root = Path(state_value)
    config = _load_config(state_root) if state_root.is_absolute() else None
    connected = _connected_connectors()
    try:
        raw_boot_id, boot_id_sha256 = _boot_identity()
    except OSError:
        raw_boot_id = ""
        boot_id_sha256 = ""
    output_order, vendor_device = select_launch_configuration(
        config,
        current_boot_id_sha256=boot_id_sha256,
        connected_connectors=connected,
        internal_connectors=_internal_connectors(connected),
        present_vendor_devices=_present_vendor_devices(),
        verified_egpu_binding_sha256=_verified_egpu_binding_sha256(raw_boot_id),
    )
    arguments = tuple(os.sys.argv[1:])
    environment = dict(os.environ)
    if state_root.is_absolute():
        from .portable_trial_launch import consume_launch_candidate
        candidate = consume_launch_candidate(
            state_root, config=config, argv=arguments, environment=environment,
            raw_boot_id=raw_boot_id,
        )
        if candidate is not None:
            trial_arguments, trial_environment = candidate
            os.execve(REAL_GAMESCOPE, (REAL_GAMESCOPE, *trial_arguments), trial_environment)
            return 127
    environment.pop("MESA_VK_DEVICE_SELECT", None)
    environment.pop("MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE", None)
    arguments = rewrite_gamescope_argv(
        arguments,
        output_order=output_order,
        vendor_device=vendor_device,
    )
    if vendor_device:
        environment["MESA_VK_DEVICE_SELECT"] = vendor_device
    os.execve(REAL_GAMESCOPE, (REAL_GAMESCOPE, *arguments), environment)
    return 127
