"""Port for turning an external display off and giving it back.

Separated from the adapter for the usual reason -- a service can be tested
without a DRM device -- and for one that is specific to this operation.

A display release is not a call, it is a **held state**. The console's mode
comes back when the last descriptor on the device closes, so what a caller
owns after a successful release is a handle whose lifetime *is* the release.
That shape has to survive into the port, because a port that returned only a
result would let a caller believe the display stays off after the thing
holding it off has gone.

The same property is what makes the recovery structural: there is no restore
step that can be skipped and no state to reconcile after a crash, because
closing the descriptor is what restores, and that happens whether the process
exits deliberately, raises, or is killed.

Nothing here decides whether a release may happen. That is
`regear.domain.display_release`, and a permitted decision authorises one bounded
release and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class DisplayReleaseOutcome(StrEnum):
    RELEASED = "released"
    #: The card could not be opened, so nothing was attempted.
    UNAVAILABLE = "unavailable"
    #: Master was refused. Something else holds the device, or the kernel
    #: declined; either way this must not continue.
    NOT_MASTER = "not_master"
    #: The write failed, or returned without error and left a mode committed.
    STILL_COMMITTED = "still_committed"


@dataclass(frozen=True, slots=True)
class DisplayReleaseResult:
    """How far a release attempt got, and over which CRTCs."""

    outcome: DisplayReleaseOutcome
    code: str = ""
    released: tuple[int, ...] = ()

    @property
    def ok(self) -> bool:
        return self.outcome is DisplayReleaseOutcome.RELEASED


class HeldRelease(Protocol):
    """A display held off for exactly as long as this handle is open."""

    released: tuple[int, ...]

    @property
    def held(self) -> bool:
        """Whether this still holds the display off."""

    def still_released(self) -> bool | None:
        """Re-read the CRTCs; None when they cannot be read.

        A caller about to act on the release asks again rather than trusting
        that it still holds, in the same way readiness is re-assessed before a
        removal instead of being carried from earlier.
        """

    def restore(self) -> None:
        """Give the display back. Idempotent, and safe from a failure path."""


class DisplayReleasePort(Protocol):
    """Turn the named CRTCs off on one card, and hand back what holds them off."""

    def release(
        self, node: str, crtcs: tuple[int, ...]
    ) -> tuple[DisplayReleaseResult, HeldRelease | None]:
        """Release `crtcs` on `node`.

        A handle is returned only on success, and discarding it restores the
        display, so a caller that needs the CRTCs to stay off must keep it for
        as long as that matters.
        """
