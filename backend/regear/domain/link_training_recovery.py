"""Offer to bounce the session when the eGPU's PCIe link will not train.

An eGPU is plugged in. The Thunderbolt transport appears, the dock is right
there in the topology, and then nothing: PCI enumeration never completes, so
there is no GPU to bind a driver to and no display to switch. Readiness spends
its whole budget waiting and reports a timeout.

Waiting longer does not appear to help, and something about bouncing the
session does. Measured on the certified Ally X / GPD G1 profile on 2026-09-11:
the link had not trained after 150 seconds of sampling, the session was
bounced, and the kernel logged `pciehp: Slot(0): Card present` followed by
`Link Up` -- twice, and again on two later occasions read from the journal.

**What that correlation is not.** An earlier version of this docstring claimed
the mechanism was the *gap*: that the slot cannot see the card while the
session holds it, so only holding the session down would do. That claim is
withdrawn. The journals show the link appearing 0.8s and 1.3s after a **new
session started** -- and in one of those the session service never reported
inactive at all, so there was no gap. A session start is what the link follows;
*why* is not established, and this module must not imply that it is. Which
mechanism to try is therefore a choice the caller makes per call, and lives in
`regear.application.link_recovery`, not here.

What this module decides is whether offering a bounce at all is honest right
now. It does not perform one, and deliberately does not authorize one either --
bouncing the session destroys whatever the player is looking at, so the act
itself stays behind an explicit confirmation. This only answers "would it be
worth trying, and is it safe to ask".

The rules, each of which declines on its own:

- **nothing to recover.** A complete PCI enumeration means the link trained.
  There is no failure to act on and offering one would invent a problem;
- **no transport, no theory.** Without the dock in the topology this is an
  absent eGPU, not a link that failed to train. The session is innocent and
  bouncing it would be a wild guess at someone's unplugged cable;
- **not yet exhausted.** Readiness is still inside its window. A link that is
  merely slow does train on its own -- one boot the same evening came up in
  11.7 seconds unaided -- and pre-empting that would restart sessions nobody
  needed to lose;
- **never over a running game.** Bouncing the session closes the game. That is
  never worth an automatic display fix, and the invariant that Re-Gear does
  not force-close Gamescope or Steam to make hardware look better applies here
  exactly as it does to disconnect;
- **unknown game state fails closed,** like every other unknown in this
  codebase. "Probably nothing is running" is not evidence that nothing is;
- **once per attachment.** If a bounce did not train the link, a panel that
  keeps offering the same destructive button after it failed is worse than one
  that stops. The latch belongs to the attachment and not to the mechanism, so
  trying a different strategy also needs a replug -- deliberately, because
  "try the next rung" is a decision for whoever is holding the device, not a
  reason to bounce somebody's session repeatedly.

Pure. It holds no state, touches no unit, and bounces nothing. The caller owns
the latch, and the caller's chosen strategy owns the mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import GameState


class LinkRecoveryAvailability(StrEnum):
    #: Bouncing the session is worth offering, and safe to ask about.
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
    """Decide whether to offer a session bounce for a link that never trained.

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
