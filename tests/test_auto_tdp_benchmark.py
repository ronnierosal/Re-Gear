import threading
import unittest
from dataclasses import replace

import test_tdp_control as control_fixtures
from hdm.application.auto_tdp_session import AutoTdpEvidence, AutoTdpLiveContext
from hdm.delivery.auto_tdp_benchmark import benchmark_auto_tdp
from hdm.domain.auto_tdp import AutoTdpObservation
from hdm.domain.models import GameState


class Evidence:
    def __init__(self):
        self.now = 0.0
        self.collect_cost = .002
        self.revalidation_cost = .003
        self.calls = 0
        self.resets = 0
        self.key = "workload"
        self.reading = control_fixtures.reading()
        self.warming = 4
        self.cancel = threading.Event()
        self.sample = None
        self.after_collect = lambda: None

    def reset(self):
        self.resets += 1

    def collect(self):
        self.calls += 1
        self.now += self.collect_cost
        observation = AutoTdpObservation(self.key, int(self.now * 1000), 55.0, 15,
                                         GameState.RUNNING, True, True, True, True)
        self.after_collect()
        return None if self.calls <= self.warming else self.sample or AutoTdpEvidence(observation, self.reading)

    def revalidate(self):
        self.now += self.revalidation_cost
        return AutoTdpLiveContext(self.key, self.reading)

    def wait(self, seconds):
        self.now += seconds
        return self.cancel.is_set()

    def run(self, **kwargs):
        return benchmark_auto_tdp(self, cancel=self.cancel, clock=lambda: self.now, wait=self.wait, **kwargs)


class AutoBenchmarkTests(unittest.TestCase):
    def test_full_composition_cost_and_warmup_are_measured_without_an_actuator(self):
        evidence = Evidence()
        result = evidence.run()
        self.assertEqual(result.code, "auto_tdp.benchmark_within_budget")
        self.assertEqual(result.attempts, 12)
        self.assertEqual(result.usable_samples, 8)
        self.assertGreaterEqual(result.maximum_collection_and_revalidation_ms, 5)
        self.assertGreaterEqual(result.elapsed_ms, 11000)
        self.assertEqual(evidence.resets, 1)
        self.assertNotIn("workload", str(result.to_dict()))

    def test_slow_revalidation_fails_budget_even_with_cheap_frames(self):
        evidence = Evidence()
        evidence.revalidation_cost = .020
        result = evidence.run()
        self.assertEqual(result.code, "auto_tdp.benchmark_budget_exceeded")
        self.assertGreaterEqual(result.maximum_collection_and_revalidation_ms, 22)

    def test_context_change_aborts_instead_of_averaging_distinct_runs(self):
        evidence = Evidence()
        evidence.after_collect = lambda: setattr(evidence, "key", str(evidence.calls))
        result = evidence.run()
        self.assertEqual(result.code, "auto_tdp.benchmark_context_changed")
        self.assertEqual(result.attempts, 2)

    def test_repeated_or_stale_sample_never_proves_sustained_collection(self):
        for revalidation_cost in (.003, 3.0):
            evidence = Evidence()
            evidence.warming = 0
            evidence.revalidation_cost = revalidation_cost
            evidence.sample = evidence.collect()
            result = evidence.run()
            self.assertEqual(result.code, "auto_tdp.benchmark_samples_insufficient")

    def test_cancel_before_or_during_collection_skips_further_reads(self):
        evidence = Evidence()
        evidence.cancel.set()
        self.assertEqual(evidence.run().code, "auto_tdp.benchmark_cancelled")
        self.assertEqual(evidence.calls, 0)
        evidence.cancel.clear()
        evidence.after_collect = evidence.cancel.set
        self.assertEqual(evidence.run().code, "auto_tdp.benchmark_cancelled")
        self.assertEqual(evidence.calls, 1)
        self.assertEqual(evidence.now, .002)

    def test_unknown_context_and_reader_exceptions_are_categorical(self):
        evidence = Evidence()
        evidence.revalidate = lambda: None
        self.assertEqual(evidence.run().code, "auto_tdp.benchmark_context_unavailable")
        def fail():
            raise OSError("private socket details")
        evidence.collect = fail
        self.assertEqual(evidence.run().code, "auto_tdp.benchmark_unavailable")

    def test_invalid_clock_and_time_limit_do_not_create_budget_evidence(self):
        evidence = Evidence()
        evidence.now = float("nan")
        self.assertEqual(evidence.run().code, "auto_tdp.benchmark_unavailable")
        evidence = Evidence()
        evidence.collect_cost = 61.0
        self.assertEqual(evidence.run().code, "auto_tdp.benchmark_time_limit")

    def test_lost_samples_at_end_are_not_hidden_by_earlier_success(self):
        evidence = Evidence()
        evidence.warming = 0
        evidence.after_collect = lambda: setattr(evidence, "warming", 100 if evidence.calls >= 10 else 0)
        self.assertEqual(evidence.run().code, "auto_tdp.benchmark_samples_insufficient")

    def test_iteration_and_cadence_bounds(self):
        for kwargs in (dict(attempts=9), dict(attempts=31), dict(interval_ms=500), dict(interval_ms=2001)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Evidence().run(**kwargs)
