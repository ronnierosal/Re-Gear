"""Exact-attachment operations for the post-GPU dock teardown transaction.

No production writer is supplied by this contract. Implementations must retain
the exclusive journal/automatic-docking inhibit after any unresolved operation.
"""
from dataclasses import dataclass
from typing import Protocol

from ..domain.dock_teardown import TunnelEvidence, UsbBranchEvidence


@dataclass(frozen=True)
class DockObservation:
    binding: str
    generation: str
    usb: UsbBranchEvidence
    tunnel: TunnelEvidence
    gpu_functions_present: tuple[str, ...]
    gpu_scan_complete: bool
    topology_complete: bool
    idle: bool


class WholeDockPort(Protocol):
    def observe(self) -> DockObservation: ...

    def claim(self, operation: str, observation: DockObservation) -> bool:
        """Atomically persist exclusive ownership and inhibit automatic docking.

        Refuse any existing or interrupted transaction, including this operation
        ID. Returning true guarantees durable ownership before any device write.
        """

    def record(self, operation: str, stage: str) -> None:
        """Durably record intent/result; exceptions stop further mutations."""

    def remove_usb(self, observation: DockObservation) -> None:
        """Remove only the bound USB controller, rechecking exact target identity.

        Return only when the kernel write has finished. A timeout/error must not
        permit another write; the journal remains unresolved for explicit recovery.
        """

    def deauthorize(self, observation: DockObservation) -> None:
        """Deauthorize only the bound router after immediate target revalidation."""

