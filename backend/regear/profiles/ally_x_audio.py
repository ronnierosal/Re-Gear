"""Experimental Ally X analog-audio relationship, not transition authority.

Observed on the supported Ally X: Phoenix GPU and Ryzen HD audio are sibling
functions with identical upstream ancestry. Addresses and function numbers are
resolved from each inventory, never saved as a hardware binding. Callers must
still prove freshness, session/game state and the actual PipeWire default sink.
"""
from dataclasses import dataclass
import re

from .ally_x import match_ally_x
from ..adapters.steamos.host import HostRecord
from ..adapters.steamos.drm import DrmCardRecord, DrmConnectorRecord
from ..adapters.steamos.pci import PciDeviceRecord

_BDF = re.compile(r"[0-9a-f]{4}:[0-9a-f]{2}:[01][0-9a-f]\.[0-7]")


@dataclass(frozen=True, slots=True)
class AllyXAnalogAudioIdentity:
    gpu_bdf: str
    audio_bdf: str
    upstream: tuple[str, ...]


def match_ally_x_analog_audio(host, cards, devices):
    """Return one positively matched relationship or None for ambiguous evidence."""
    if (type(host) is not HostRecord
            or any(type(v) is not str for v in (host.sys_vendor, host.product_name, host.board_name))
            or not match_ally_x(host).exact
            or type(cards) is not tuple or not 0 < len(cards) <= 64
            or type(devices) is not tuple or not 0 < len(devices) <= 4096):
        return None
    inventory = {}
    for device in devices:
        if (type(device) is not PciDeviceRecord or type(device.bdf) is not str
                or _BDF.fullmatch(device.bdf) is None or device.bdf in inventory):
            return None
        inventory[device.bdf] = device
    if any(type(card) is not DrmCardRecord or type(card.pci_bdf) is not str
           or _BDF.fullmatch(card.pci_bdf) is None for card in cards):
        return None
    if len({card.pci_bdf for card in cards}) != len(cards):
        return None
    candidates = [card for card in cards if card.boot_vga is True]
    if len(candidates) != 1:
        return None
    card = candidates[0]
    if ((card.vendor, card.device, card.driver) != ('0x1002', '0x15bf', 'amdgpu')
            or type(card.connectors) is not tuple or len(card.connectors) > 64
            or type(card.name) is not str
            or any(type(c) is not DrmConnectorRecord or type(c.name) is not str
                   or type(c.card) is not str for c in card.connectors)
            or not any(c.card == card.name and c.internal for c in card.connectors)):
        return None
    gpu = inventory.get(card.pci_bdf)
    if gpu is None or (gpu.vendor, gpu.device, gpu.class_code, gpu.driver) != (
            '0x1002', '0x15bf', '0x030000', 'amdgpu'):
        return None

    def ancestry_valid(device):
        path = device.ancestry
        return (type(path) is tuple and 2 <= len(path) <= 32
                and all(type(p) is str and _BDF.fullmatch(p) is not None for p in path)
                and len(set(path)) == len(path) and path[-1] == device.bdf)

    if not ancestry_valid(gpu):
        return None
    audio = [device for device in devices
             if (device.vendor, device.device, device.class_code, device.driver) == (
                 '0x1022', '0x15e3', '0x040300', 'snd_hda_intel')
             and device.bdf.rsplit('.', 1)[0] == gpu.bdf.rsplit('.', 1)[0]
             and device.bdf != gpu.bdf and ancestry_valid(device)
             and device.ancestry[:-1] == gpu.ancestry[:-1]]
    if len(audio) != 1:
        return None
    return AllyXAnalogAudioIdentity(gpu.bdf, audio[0].bdf, gpu.ancestry[:-1])
