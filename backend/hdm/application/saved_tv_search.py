"""Hold the search for a saved TV across readings, so waiting can end.

Two pieces already exist. The domain decides one reading -- is this the saved
TV, and is it verified enough to switch to. The store remembers one TV across
boots. Neither owns the thing that makes waiting *bounded*: the count of
finished looks that did not find it.

That count is the whole reason this exists. Without it every reading is the
first reading, "connecting..." never ends, and a player whose TV is in another
room is told the dock is still working on it forever. With it, the search says
so and stops, which is the answer they can actually act on.

Two rules about the count, both of which have cost this codebase before:

- **only a finished look spends it.** A reading that did not complete is not
  evidence of an absent TV, so a reader that keeps failing must not be able to
  exhaust the budget and abandon a TV that was there the whole time;
- **a new dock re-arms it.** The budget bounds one attempt to find the TV, not
  the lifetime of the plugin. A player who gives up, walks away and docks again
  is asking again, and gets a fresh search.

A record this cannot read is reported as unobservable rather than as an absent
TV or a crash. The store refuses a symlinked record loudly, by design; that
refusal should reach a caller as "cannot tell", never as "no saved TV" -- which
would silently stop resuming -- and never as an exception thrown into a polling
loop.

This composes and counts. It observes no hardware, switches no display, and
authorizes nothing on its own.
"""

from __future__ import annotations

from ..domain.models import DisplayObservation
from ..domain.saved_tv import (
    DEFAULT_MAX_ATTEMPTS,
    SavedTvDecision,
    SavedTvProfile,
    SavedTvState,
    decide_saved_tv,
    remember_docked_tv,
)


class SavedTvSearch:
    """The bounded search for one player's saved TV."""

    def __init__(self, store, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> None:
        self._store = store
        self._max_attempts = max_attempts
        self._attempts = 0
        self._cached: SavedTvProfile | None = None
        self._loaded = False

    @property
    def attempts(self) -> int:
        """Finished looks that did not find it. For reporting and tests."""
        return self._attempts

    def rearm(self) -> None:
        """Begin the search again, and re-read the record.

        Called when a new dock begins. The budget bounds one attempt to find
        the TV, not the lifetime of the plugin.
        """
        self._attempts = 0
        self._cached = None
        self._loaded = False

    def observe(
        self,
        *,
        displays: tuple[DisplayObservation, ...],
        scan_complete: bool,
    ) -> SavedTvDecision:
        """Decide this reading, and spend the budget only if it was a real look."""
        try:
            profile = self._profile()
        except (ValueError, OSError):
            # A record that cannot be read is "cannot tell", never "no saved
            # TV". The latter would silently stop resuming and look like the
            # feature was never configured.
            return SavedTvDecision(
                SavedTvState.UNOBSERVABLE, "saved_tv.record_unreadable"
            )
        decision = decide_saved_tv(
            profile=profile,
            displays=displays,
            scan_complete=scan_complete,
            attempts=self._attempts,
            max_attempts=self._max_attempts,
        )
        if decision.state is SavedTvState.WAITING:
            # The only state that means "looked, finished, did not find it".
            self._attempts += 1
        return decision

    def remember(
        self,
        *,
        display: DisplayObservation | None,
        transition_succeeded: bool,
        label: str = "",
    ) -> SavedTvProfile | None:
        """Record the TV a completed dock earned, if it earned one.

        Writing also re-arms the search: the TV just docked to is the intent
        now, and any budget spent looking for the previous one is spent.
        """
        profile = remember_docked_tv(
            display=display,
            transition_succeeded=transition_succeeded,
            label=label,
        )
        if profile is None:
            return None
        self._store.record(profile)
        self._attempts = 0
        self._cached = profile
        self._loaded = True
        return profile

    def forget(self) -> None:
        self._store.forget()
        self.rearm()

    def _profile(self) -> SavedTvProfile | None:
        if not self._loaded:
            self._cached = self._store.load()
            self._loaded = True
        return self._cached
