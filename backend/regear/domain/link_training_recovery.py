"""Offer to release the session when the eGPU's PCIe link will not train.

An eGPU is plugged in. The Thunderbolt transport appears, the dock is right
there in the topology, and then nothing: PCI enumeration never completes, so
there is no GPU to bind a driver to and no display to switch. Readiness spends
its whole budget waiting and reports a timeout.

Waiting longer does not help, and that is the finding this module exists for.
Measured on the certified Ally X / GPD G1 profile on 2026-09-11: the link had
not trained after 150 seconds of sampling, `gamescope-session.target` was
stopped, and the kernel logged `pciehp: Slot(0): Card present` followed by
`Link Up` 6.7 seconds later. A second occurrence the same evening trained 2.2
seconds after the session stopped. The hotplug controller reports the card as
*newly present* at the moment the session lets go, which is a stronger claim
than slow enumeration: while the session holds on, the slot is not detecting
the card at all, so no budget would ever have been long enough.

So the recovery is to release the session and let the slot see the card. What
this module decides is whether offering that is honest right now. It does not
perform it, and deliberately does not authorize it either -- releasing the
session destroys whatever the player is looking at, so the act itself stays
behind an explicit confirmation. This only answers "would it help, and is it
safe to ask".

The rules, each of which declines on its own:

- **nothing to recover.** A complete PCI enumeration means the link trained.
  There is no failure to act on and offering one would invent a problem;
- **no transport, no theory.** Without the dock in the topology this is an
  absent eGPU, not a link that failed to train. The session is innocent and
  restarting it would be a wild guess at someone's unplugged cable;
- **not yet exhausted.** Readiness is still inside its window. A link that is
  merely slow does train on its own -- one boot the same evening came up in
  11.7 seconds unaided -- and pre-empting that would restart sessions nobody
  needed to lose;
- **never over a running game.** Releasing the session closes the game. That
  is never worth an automatic display fix, and the invariant that Re-Gear does
  not force-close Gamescope or Steam to make hardware look better applies here
  exactly as it does to disconnect;
- **unknown game state fails closed,** like every other unknown in this
  codebase. "Probably nothing is running" is not evidence that nothing is;
- **once per attachment.** If releasing the session did not train the link, it
  will not train on the second try either, and a panel that keeps offering the
  same destructive button after it failed is worse than one that stops. The
  latch belongs to the attachment, so unplugging and plugging back in earns a
  fresh offer.

Pure. It holds no state, touches no unit, and restarts nothing. The caller
owns the latch and the executor owns the restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import GameState


class LinkRecoveryAvailability(StrEnum):
    #: Releasing the session is worth offering, and safe to ask about.
    OFFERED = "offered"
    #: It is not. `code` says why, and is the only thing worth showing.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class LinkRecoveryAssessment:
    availability: LinkRecoveryAvailability
    code: str

    @property
    def offered(self) -> bool:
        return self.availability is LinkRecoveryAvailability.OFFERED


def _no(code: str) -> LinkRecoveryAssessment:
    return LinkRecoveryAssessment(LinkRecoveryAvailability.UNAVAILABLE, code)


def assess_link_recovery(
    *,
    readiness_exhausted: bool,
    transport_present: bool,
    pci_complete: bool,
    game_state: GameState,
    attempted: bool,
) -> LinkRecoveryAssessment:
    """Decide whether to offer a session release for a link that never trained.

    `readiness_exhausted` is the caller's reading of its own window, passed as
    a fact rather than a stage so the domain keeps no opinion about the
    readiness lifecycle's vocabulary. `attempted` is the caller's latch for
    this attachment.
    """
    if pci_complete:
        return _no("link_recovery.pci_complete")
    if not transport_present:
        return _no("link_recovery.transport_absent")
    if not readiness_exhausted:
        return _no("link_recovery.readiness_not_exhausted")
    if game_state is GameState.RUNNING:
        return _no("link_recovery.game_running")
    if game_state is not GameState.IDLE:
        return _no("link_recovery.game_state_unknown")
    if attempted:
        return _no("link_recovery.already_attempted")
    return LinkRecoveryAssessment(
        LinkRecoveryAvailability.OFFERED, "link_recovery.available"
    )
