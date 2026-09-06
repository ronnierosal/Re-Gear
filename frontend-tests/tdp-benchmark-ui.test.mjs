import assert from "node:assert/strict";
import test from "node:test";
import { sanitizeTdpBenchmark, tdpBenchmarkMessage } from "../src/tdp-benchmark-ui.ts";

const idle = { schema_version: 1, running: false, cancelling: false, code: "auto_tdp.benchmark_idle", result: null };
const report = { code: "auto_tdp.benchmark_within_budget", attempts: 12, usable_samples: 8, consecutive_samples: 8, maximum_collection_and_revalidation_ms: 5, elapsed_ms: 11060, interval_ms: 1000 };

test("benchmark schema separates cancellation and running, accepts empty reports", () => {
  for (const status of [idle, { ...idle, running: true }, { ...idle, running: true, cancelling: true }, { ...idle, result: report }, { ...idle, result: { ...report, attempts: 0, usable_samples: 0, consecutive_samples: 0, maximum_collection_and_revalidation_ms: null } }]) {
    assert.notEqual(sanitizeTdpBenchmark(status), null);
  }
  for (const change of [{ schema_version: 2 }, { cancelling: true }, { running: 1 }, { result: undefined }, { code: "private.host/path" }]) assert.equal(sanitizeTdpBenchmark({ ...idle, ...change }), null);
});

test("malformed or contradictory measurements cannot reach the display", () => {
  for (const change of [{ attempts: 31 }, { attempts: true }, { usable_samples: 13 }, { consecutive_samples: 9 }, { elapsed_ms: Infinity }, { interval_ms: 999 }, { maximum_collection_and_revalidation_ms: NaN }, { maximum_collection_and_revalidation_ms: -1 }, { code: "private/path" }]) {
    assert.equal(sanitizeTdpBenchmark({ ...idle, result: { ...report, ...change } }), null);
  }
});

test("messages distinguish measured admission, insufficient samples and cancellation", () => {
  assert.match(tdpBenchmarkMessage({ ...idle, code: report.code, result: report }), /has not been enabled/);
  assert.match(tdpBenchmarkMessage({ ...idle, code: "auto_tdp.benchmark_samples_insufficient" }), /Not enough/);
  assert.match(tdpBenchmarkMessage({ ...idle, running: true, cancelling: true }), /current read/);
  assert.match(tdpBenchmarkMessage(null), /unavailable/);
  assert.doesNotMatch(tdpBenchmarkMessage({ ...idle, code: "auto_tdp.private_secret" }), /private_secret/);
});
