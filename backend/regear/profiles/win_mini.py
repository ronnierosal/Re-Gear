"""Inert exact Mini identity; experimental/unqualified, no runtime admission.

This module is not registered in the runtime catalog. Matching identifies the
host only and grants no display/audio, power, sleep, removal or other capability.
"""
from dataclasses import dataclass

from ..adapters.steamos.host import HostRecord

PROFILE_ID = "gpd-win-mini-experimental"
QUALIFICATION_STATUS = "experimental-unqualified"
_OBSERVED_DMI_IDENTITY = ('gpd', 'g1617-01', 'g1617-01')


@dataclass(frozen=True, slots=True)
class WinMiniMatch:
    exact: bool
    reason: str


def match_win_mini(host: HostRecord) -> WinMiniMatch:
    """Compare one bounded complete normalized tuple; never infer capability."""
    if type(host) is not HostRecord:
        return WinMiniMatch(False, "Host identity record is invalid")
    fields = (host.sys_vendor, host.product_name, host.board_name)
    try:
        if any(type(value) is not str or not value.strip()
               or len(value.encode("utf-8")) > 256 for value in fields):
            return WinMiniMatch(False, "Host DMI identity is incomplete or invalid")
        identity = tuple(" ".join(value.split()).casefold() for value in fields)
    except UnicodeError:
        return WinMiniMatch(False, "Host DMI identity is invalid")
    if identity != _OBSERVED_DMI_IDENTITY:
        return WinMiniMatch(False, "Host DMI identity does not match the observed Mini tuple")
    return WinMiniMatch(True, "Exact observed Mini identity; lifecycle remains unqualified")
