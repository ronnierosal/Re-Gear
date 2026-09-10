"""ASUS ROG Ally X host classification."""

from __future__ import annotations

from dataclasses import dataclass

from ..adapters.steamos.host import HostRecord
from ..domain.control_plane import (
    CapabilitySupport,
    EgpuTransport,
    HostCapabilities,
)


PROFILE_ID = "asus-rog-ally-x"
_CERTIFIED_DMI_IDENTITIES = frozenset(
    {
        (
            "asustek computer inc.",
            "rog ally x rc72la",
            "rc72la",
        ),
        # Current SteamOS firmware reports the product and board identifiers
        # together. This is an exact observed DMI tuple, not a fuzzy match.
        (
            "asustek computer inc.",
            "rog ally x rc72la_rc72la",
            "rc72la",
        ),
    }
)
CAPABILITIES = HostCapabilities(
    profile_id=PROFILE_ID,
    egpu_support=CapabilitySupport.VERIFIED,
    egpu_transport=EgpuTransport.USB4,
    display_handoff=CapabilitySupport.EXPERIMENTAL,
    audio_handoff=CapabilitySupport.EXPERIMENTAL,
    internal_controller_suppression=CapabilitySupport.UNKNOWN,
    external_controller_promotion=CapabilitySupport.UNKNOWN,
    power_button_interception=CapabilitySupport.EXPERIMENTAL,
)


@dataclass(frozen=True, slots=True)
class AllyXMatch:
    exact: bool
    reason: str


def _normalize_dmi(value: str) -> str:
    return " ".join(value.split()).casefold()


def match_ally_x(host: HostRecord) -> AllyXMatch:
    identity = tuple(
        _normalize_dmi(value)
        for value in (host.sys_vendor, host.product_name, host.board_name)
    )
    if not all(identity):
        return AllyXMatch(False, "Handheld DMI identity is incomplete")
    if identity not in _CERTIFIED_DMI_IDENTITIES:
        return AllyXMatch(False, "Handheld DMI identity does not match a certified profile")
    return AllyXMatch(True, "Exact certified handheld DMI profile was observed")


def matches_ally_x(host: HostRecord) -> bool:
    return match_ally_x(host).exact
