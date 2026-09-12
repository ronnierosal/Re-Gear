"""Standing consent must be exactly True before anything is observed or moved.

`execute_automatic` is the boundary where a persisted player opt-in turns into
a real display transition. It guarded that with `if not standing_consent`,
which asks "is this truthy" rather than "is this consent". Those differ for
every value that is not a bool: the string `"false"`, `{"enabled": False}`, a
stray `1`, a bare object -- each is truthy, and each would have been accepted
as the player having opted in.

The defect was latent rather than live. The only production caller passes the
value from `AutomaticDockPreferenceStore.load()`, which refuses to return
anything but a real bool, so no shipped path could reach the boundary with a
string. That is a property of today's single caller, not of this service, and
a boundary that is only safe because of who happens to call it is not safe. So
the check moves to identity here, where it belongs.

Identity also sidesteps a trap the old check could not see: in Python `1 ==
True`. Any comparison-based guard treats the integer `1` as consent. `is True`
does not, which is the whole reason for spelling it that way.

Two facts are asserted for every rejection, not just the returned code:

- **no plan reached the orchestrator** -- nothing was moved;
- **no observation was consumed** -- the refusal happened at ingress, before
  the service looked at the hardware at all. A guard that rejects only after
  observing has already done work on an unverified caller's say-so.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.control_plane import PlacementState  # noqa: E402
from regear.ports.transition import VersionedObservation  # noqa: E402

# The real service harness, not a stand-in: these tests must exercise the
# production object, which is the only way to prove the ingress guard runs
# where the caller actually enters.
from tests.test_supervised_transition import (  # noqa: E402
    Observations,
    service,
    snapshot,
)


#: Truthy, and none of them consent. `1` is here deliberately: it equals True.
INVALID_TRUTHY = (
    "true",
    "false",
    "1",
    1,
    2,
    1.0,
    {"enabled": True},
    {"enabled": False},
    [True],
    (True,),
    object(),
)

#: Falsy, and still not a bool. These refuse too, but they are not the player
#: having switched the feature off, so they do not claim to be.
INVALID_FALSY = (0, 0.0, "", {}, [], ())

#: The only two values that mean "the player has not opted in".
GENUINELY_OFF = (False, None)


class ConsentMustBeExactlyTrue(unittest.TestCase):
    def _reject(self, consent, expected_code):
        observed = Observations(
            VersionedObservation("generation-1", snapshot()),
            VersionedObservation("generation-1", snapshot()),
        )
        value, orchestrator, _ = service(observed)
        before = len(observed.values)

        result = value.execute_automatic(
            PlacementState.DOCKED_EGPU,
            expected_generation="generation-1",
            standing_consent=consent,
        )

        self.assertFalse(result.accepted, f"{consent!r} was accepted as consent")
        self.assertEqual(result.code, expected_code)
        self.assertEqual(
            orchestrator.plans, [], f"{consent!r} reached the orchestrator"
        )
        self.assertEqual(
            len(observed.values),
            before,
            f"{consent!r} was observed before being refused",
        )

    def test_truthy_non_bool_values_are_not_consent(self):
        for consent in INVALID_TRUTHY:
            with self.subTest(consent=repr(consent)):
                self._reject(consent, "automatic_dock.consent_invalid")

    def test_the_integer_one_is_not_consent_even_though_it_equals_true(self):
        """`1 == True` in Python. Only identity separates them."""
        self.assertEqual(1, True)
        self._reject(1, "automatic_dock.consent_invalid")

    def test_falsy_non_bool_values_are_invalid_rather_than_switched_off(self):
        for consent in INVALID_FALSY:
            with self.subTest(consent=repr(consent)):
                self._reject(consent, "automatic_dock.consent_invalid")

    def test_false_and_none_still_report_the_feature_as_not_enabled(self):
        """Preserved exactly: these are the real 'off', not a caller bug."""
        for consent in GENUINELY_OFF:
            with self.subTest(consent=repr(consent)):
                self._reject(consent, "automatic_dock.not_enabled")


class ExactTrueStillWorks(unittest.TestCase):
    def test_true_runs_the_transition(self):
        """The positive path, through the real service, unchanged."""
        observed = Observations(
            VersionedObservation("generation-1", snapshot()),
            VersionedObservation("generation-1", snapshot()),
        )
        value, orchestrator, _ = service(observed)

        result = value.execute_automatic(
            PlacementState.DOCKED_EGPU,
            expected_generation="generation-1",
            standing_consent=True,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(len(orchestrator.plans), 1)
        self.assertEqual(
            orchestrator.plans[0].target_placement, PlacementState.DOCKED_EGPU
        )

    def test_consent_alone_does_not_bypass_the_remaining_gates(self):
        """Exact True is necessary, never sufficient. Unready integration wins."""
        observed = Observations(
            VersionedObservation("generation-1", snapshot()),
            VersionedObservation("generation-1", snapshot()),
        )
        value, orchestrator, _ = service(observed, ready=False)

        result = value.execute_automatic(
            PlacementState.DOCKED_EGPU,
            expected_generation="generation-1",
            standing_consent=True,
        )

        self.assertFalse(result.accepted)
        self.assertNotEqual(result.code, "automatic_dock.consent_invalid")
        self.assertEqual(orchestrator.plans, [])


if __name__ == "__main__":
    unittest.main()
