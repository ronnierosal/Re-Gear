"""Unbound injected observation/receipt port, not a live provider or effect API.

M1 needs separately reviewed installed-provider identities, exact enumeration,
coherent committed readback, a fresh exact owned_request issuer, revocation and
qualified revert semantics. A matching mode or accepted command cannot prove ownership.
No setters are exposed in M0; Operation is a pure plan, not dispatch authority.
"""
from typing import Protocol
from ..domain.display_modes import Observation
from ..domain.display_mode_cycle import Receipt


class DisplayModeEvidence(Protocol):
    def observation(self) -> Observation:
        """Return coherent evidence supplied by a separately qualified binding."""
        ...

    def receipt(self, request: str) -> Receipt | None:
        """Return committed readback tied to that exact request, never acceptance."""
        ...
