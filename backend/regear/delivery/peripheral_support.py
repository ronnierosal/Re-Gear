"""Reduce private peripheral observations for support export."""
from __future__ import annotations
from ..application.support_bundle import PeripheralSupportStatus
from ..domain.peripheral_handoff import PeripheralObservation

def peripheral_support_status(value: PeripheralObservation) -> PeripheralSupportStatus:
    return PeripheralSupportStatus(
        value.controller.complete, value.controller.exact,
        value.controller.failure_code or "controller.observed",
        value.audio.complete, value.audio.exact,
        value.audio.failure_code or "audio.observed",
    )
