"""Seeded closed-loop invariants for Auto TDP over arbitrary workloads.

The named replays in test_auto_tdp_replays cover chosen scenarios. These cover
the space between them: across a spread of workload shapes the loop must stay
inside its configured range, keep one restorable baseline, honour its settling
window, and stop writing the moment it is disabled. Seeds are fixed so a failure
is reproducible rather than merely observed once.

These are finite simulated trajectories, not a proof over arbitrary workloads.
Their value is conditional on each one actually driving the loop, so the
non-vacuity test below asserts that every workload writes, that a journal record
is created, and that the runs collectively reach both the floor and the ceiling.
Without that last check a workload set can quietly stop exercising a clamp: the
upper-clamp mutation survived this suite until a workload reached 30 W.
"""

import random
import unittest

import test_auto_tdp_session as fixtures


SEEDS = (1, 7, 13, 29, 101)
DURATION_MS = 180_000


def flat(rng, watts):
    """A workload that never responds to power."""
    return 45.0


def responsive(rng, watts):
    """Frames scale with configured watts."""
    return 25.0 + 4.0 * (watts - 15)


def regressive(rng, watts):
    """Pathological: more power reads as fewer frames."""
    return 70.0 - 2.0 * (watts - 15)


def noisy(rng, watts):
    """Unrelated jitter spanning the target."""
    return rng.uniform(40.0, 80.0)


def boundary(rng, watts):
    """Adversarial: hovers on the deadband edge to induce flapping."""
    return 60.0 - 2.0 + rng.choice((-0.75, -0.25, 0.25, 0.75))


def starved(rng, watts):
    """Improves faster than the deadband but never reaches target, so the loop
    climbs all the way to its ceiling and must stop there."""
    return 10.0 + 3.0 * (watts - 15)


WORKLOADS = (flat, responsive, regressive, noisy, boundary, starved)


class AutoTdpInvariantTests(unittest.TestCase):
    def drive(self, seed, workload, duration_ms=DURATION_MS):
        """Run the real session, policy and transaction service to completion."""
        case = fixtures.AutoSessionTests()
        case.setUp()
        writes = []
        provider = case.provider
        original = provider.set_limit

        def recording_set_limit(expected, watts, *, dispatch_guard=None):
            outcome = original(expected, watts, dispatch_guard=dispatch_guard)
            if outcome.attempted:
                writes.append((case.now, watts))
            return outcome

        provider.set_limit = recording_set_limit

        # Record what the loop asks for, not only what a lower layer let through:
        # the port rejects an out-of-range request before it ever becomes a write.
        requests = []
        apply_original = case.service.apply

        def recording_apply(watts, *, dispatch_guard=None):
            requests.append(watts)
            return apply_original(watts, dispatch_guard=dispatch_guard)

        case.service.apply = recording_apply
        case.session.start(case.policy)
        rng = random.Random(seed)
        while case.now <= duration_ms:
            case.fps = workload(rng, provider.current.sustained.current)
            case.session.tick()
            case.now += 1000
        return case, writes, requests

    def each_run(self, duration_ms=DURATION_MS):
        for workload in WORKLOADS:
            for seed in SEEDS:
                with self.subTest(workload=workload.__name__, seed=seed):
                    yield self.drive(seed, workload, duration_ms)

    def test_configured_watts_never_leave_the_policy_range(self):
        for case, writes, requests in self.each_run():
            policy = case.policy
            for watts in requests:
                self.assertGreaterEqual(watts, policy.minimum_watts)
                self.assertLessEqual(watts, policy.maximum_watts)
            for _, watts in writes:
                self.assertGreaterEqual(watts, policy.minimum_watts)
                self.assertLessEqual(watts, policy.maximum_watts)
            observed = case.provider.current.sustained.current
            self.assertGreaterEqual(observed, policy.minimum_watts)
            self.assertLessEqual(observed, policy.maximum_watts)

    def test_one_restorable_baseline_survives_every_workload(self):
        for case, _, _ in self.each_run():
            record = case.journal.record
            if record is not None:
                # The baseline is the pre-session setting, never a later step.
                self.assertEqual(record.baseline.sustained.current, 15)
                self.assertEqual(case.service.restore().state, "restored")
                self.assertEqual(case.provider.current.sustained.current, 15)

    def test_verified_writes_never_fall_inside_one_settling_window(self):
        for case, writes, requests in self.each_run():
            settling = case.policy.settling_ms
            for (earlier, _), (later, _) in zip(writes, writes[1:]):
                self.assertGreaterEqual(later - earlier, settling)

    def test_no_workload_produces_unbounded_adjustment(self):
        for case, writes, requests in self.each_run():
            # Each verified write costs at least one settling window, so the run
            # length bounds how many the loop can possibly have made.
            self.assertLessEqual(len(writes), DURATION_MS // case.policy.settling_ms)

    def test_every_workload_actually_drives_the_loop(self):
        """Guards the invariants above from passing vacuously."""
        reached = set()
        for case, writes, _ in self.each_run():
            policy = case.policy
            self.assertGreater(len(writes), 0)
            self.assertIsNotNone(case.journal.record)
            reached.update(watts for _, watts in writes)
        # Both clamps must be exercised by the set as a whole, or a mutation
        # that removes one can survive unnoticed.
        self.assertIn(policy.minimum_watts, reached)
        self.assertIn(policy.maximum_watts, reached)

    def test_a_stopped_session_writes_nothing_further(self):
        for case, writes, requests in self.each_run():
            before = list(writes)
            case.session.stop()
            self.assertFalse(case.session.enabled)
            for _ in range(30):
                case.now += 1000
                case.session.tick()
            self.assertEqual(writes, before)


if __name__ == "__main__":
    unittest.main()
