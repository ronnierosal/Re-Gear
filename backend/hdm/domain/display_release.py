"""Decide whether an external display may be released before a removal.

The blocker in #168 is not a client holding the eGPU. It is the kernel's own
fbdev client: when the compositor gives the external output back, `drm_fb_helper`
restores the console's mode on the eGPU CRTC, so the card keeps a committed mode
that no userspace process owns. Releasing every holder cannot clear it, and
`removal_safety` correctly declines while it stands.

What can clear it is a DRM master on that device turning the CRTC off. That is
the operation a display server performs, it is scoped to the one card, and its
recovery is structural rather than procedural: dropping master, closing the
descriptor, or dying causes `drm_client_dev_restore()` to put the console's mode
back. The lever recorded earlier -- `/sys/class/vtconsole/vtcon1/bind` -- is a
system-wide console change with no equivalent recovery, and this is not that.

Turning off a display is still a visible act, so the question this answers is
narrow: **is the thing being turned off something nobody is looking at?**

Four facts have to hold together, and each one refuses on its own:

- the external card really does have a committed mode, from CRTC evidence
  rather than from `enabled`, and that reading finished;
- **no userspace process holds the card**, over a scan that finished. This is
  the one that carries the argument. A committed mode with no client is the
  console; a committed mode with a client may be a player watching a game, and
  the two must never be confused;
- the internal panel has a committed mode of its own, so the player is left
  with a display rather than with nothing;
- the step was explicitly approved.

Approval is checked last on purpose. A caller that has not approved still gets
told which substantive fact would have blocked it, which is what an operator
running a plan needs; the facts are read-only and already available to it.

Pure. It releases nothing, observes nothing and takes no master; the act lives
behind a port. Producing a permitted decision authorises one bounded release and
nothing else. It is not a claim that any device is safe to unplug: safety
invariant 10 is untouched, and whether an unplug may follow a software removal
is a separate question.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class DisplayReleaseEvidence:
    """One reading of both displays and of who holds the external card.

    Every field carries its own completeness, because the failure this guards
    against is a reading that did not finish being taken for a reading that
    found nothing.
    """

    #: CRTC ids on the external card that have a committed mode.
    external_committed: tuple[int, ...]
    #: Whether the external card's CRTC reading finished.
    external_complete: bool
    #: Whether the internal panel has a committed mode; None when unknown.
    internal_committed: bool | None
    #: Userspace processes holding the external card's device node.
    client_holders: tuple[str, ...]
    #: Whether the holder scan managed to look everywhere.
    client_scan_complete: bool


class DisplayReleaseState(StrEnum):
    #: The external card is driving nothing, so there is nothing to release.
    NOT_NEEDED = "not_needed"
    #: One bounded release of the named CRTCs is authorised.
    PERMITTED = "permitted"
    #: A reading did not finish. Not knowing is not permission.
    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    #: Userspace holds the card and may be presenting to the player.
    CLIENT_PRESENT = "client_present"
    #: The internal panel is not known to be driving anything, so releasing
    #: the external one could leave the player with no display at all.
    NO_INTERNAL_DISPLAY = "no_internal_display"
    #: Every fact holds and the step was not approved.
    NOT_APPROVED = "not_approved"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class DisplayReleaseDecision:
    """Whether a release may run, and over exactly which CRTCs."""

    state: DisplayReleaseState
    code: str
    crtcs: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.state is DisplayReleaseState.PERMITTED and not self.crtcs:
            raise ValueError("a permitted release names the CRTCs it may turn off")
        if self.state is not DisplayReleaseState.PERMITTED and self.crtcs:
            raise ValueError("only a permitted release names CRTCs")

    @property
    def permitted(self) -> bool:
        """Whether the caller may turn those CRTCs off now.

        One state says yes. `not_needed` deliberately does not: there is
        nothing to release, and a caller must not read it as having released
        something.
        """
        return self.state is DisplayReleaseState.PERMITTED

    @property
    def blocks_removal(self) -> bool:
        """Whether a committed external mode is still standing after this.

        True for every refusal that leaves the display up. False for
        `not_needed`, where the display was never up, and for `permitted`,
        where the caller may now take it down.
        """
        return self.state not in (
            DisplayReleaseState.NOT_NEEDED,
            DisplayReleaseState.PERMITTED,
        )


def decide_display_release(
    evidence: DisplayReleaseEvidence, *, approved: bool
) -> DisplayReleaseDecision:
    """Decide whether the external display may be turned off.

    `evidence` must be one fresh reading. A committed mode observed before a
    holder scan describes a different moment from the scan, and this decision
    reads them as though they describe the same one.
    """
    if type(evidence) is not DisplayReleaseEvidence or type(approved) is not bool:
        return DisplayReleaseDecision(
            DisplayReleaseState.INVALID, "display_release.input_invalid"
        )
    if type(evidence.external_committed) is not tuple or any(
        type(crtc) is not int for crtc in evidence.external_committed
    ):
        return DisplayReleaseDecision(
            DisplayReleaseState.INVALID, "display_release.input_invalid"
        )
    if type(evidence.client_holders) is not tuple or any(
        type(holder) is not str for holder in evidence.client_holders
    ):
        return DisplayReleaseDecision(
            DisplayReleaseState.INVALID, "display_release.input_invalid"
        )

    if not evidence.external_complete:
        return DisplayReleaseDecision(
            DisplayReleaseState.EVIDENCE_INCOMPLETE,
            "display_release.external_state_unknown",
        )
    if not evidence.external_committed:
        return DisplayReleaseDecision(
            DisplayReleaseState.NOT_NEEDED, "display_release.not_driving_a_display"
        )

    if not evidence.client_scan_complete:
        # An empty holder list from a scan that could not finish is exactly the
        # fail-open this project removed elsewhere; it must not reappear as
        # permission to turn a display off.
        return DisplayReleaseDecision(
            DisplayReleaseState.EVIDENCE_INCOMPLETE,
            "display_release.client_scan_incomplete",
        )
    if evidence.client_holders:
        # The whole safety argument is here. A committed mode with no client is
        # the kernel console; a committed mode with a client may be a player
        # watching something, and turning that off is not this decision's to
        # make.
        return DisplayReleaseDecision(
            DisplayReleaseState.CLIENT_PRESENT, "display_release.client_holds_the_card"
        )

    if evidence.internal_committed is not True:
        # Unknown counts as not driving. Releasing the external display while
        # the internal panel may be dark would leave the player with nothing.
        return DisplayReleaseDecision(
            DisplayReleaseState.NO_INTERNAL_DISPLAY,
            "display_release.internal_display_not_verified",
        )

    if not approved:
        return DisplayReleaseDecision(
            DisplayReleaseState.NOT_APPROVED, "display_release.not_approved"
        )
    return DisplayReleaseDecision(
        DisplayReleaseState.PERMITTED,
        "display_release.permitted",
        evidence.external_committed,
    )
