import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";


const source = readFileSync(
  new URL("../src/quick-access/modules/egpu-presentation.ts", import.meta.url),
  "utf8",
);
const { outputText } = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2020,
  },
});
const { egpuPresentation } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);


function payload(lifecycle) {
  return {
    delivery_schema_version: 1,
    snapshot: {
      schema_version: 1,
      observed_at: "2026-09-19T00:00:00Z",
      host_profile: "test",
      support_tier: "certified",
      game_state: "idle",
      gpus: [],
      displays: [],
      gamescope: { running: true, confidence: "verified" },
      disconnect_readiness: {},
      sleep_guard: {},
      egpu_link: { applicable: false, state: "unknown", confidence: "unknown" },
      blockers: [],
    },
    inference: { mode: "portable", reasons: [] },
    connection_readiness: {
      schema_version: 1,
      stage: "timed_out",
      code: "connection.readiness_timed_out",
      poll_after_ms: 5000,
      window_age_ms: 120000,
    },
    whole_dock_lifecycle: {
      schema_version: 1,
      state: lifecycle,
      code: `whole_dock.${lifecycle}`,
    },
  };
}


test("durable software-down state replaces the attach observer timeout only", () => {
  const result = egpuPresentation(payload("software_down"));
  assert.equal(result.lifecycle.text, "Software disconnected");
  assert.equal(result.lifecycle.known, true);
  assert.equal(result.connection.text, "Unknown");
  assert.equal(result.renderGpu.text, "Unknown");
  assert.equal(result.disconnect.safeClaim, false);
  assert.match(result.disconnect.reason, /cannot confirm/i);
});

test("a lifecycle contradiction fails closed as needs attention", () => {
  const result = egpuPresentation(payload("conflict"));
  assert.equal(result.lifecycle.text, "Needs attention");
  assert.equal(result.disconnect.safeClaim, false);
});

test("an unreadable durable claim does not fall back to a misleading timeout", () => {
  const result = egpuPresentation(payload("unknown"));
  assert.equal(result.lifecycle.text, "Unknown");
  assert.equal(result.lifecycle.known, false);
});

test("a retained intermediate claim never invents active work", () => {
  for (const code of [
    "whole_dock.teardown_state_unconfirmed",
    "whole_dock.reconnect_state_unconfirmed",
  ]) {
    const input = payload("unknown");
    input.whole_dock_lifecycle.code = code;
    const result = egpuPresentation(input);
    assert.equal(result.lifecycle.text, "Unknown");
    assert.doesNotMatch(result.lifecycle.text, /disconnecting|reconnecting/i);
  }
});

test("no durable claim preserves the independent connection lifecycle", () => {
  assert.equal(egpuPresentation(payload("none")).lifecycle.text, "Timed out");
  const legacy = payload("none");
  delete legacy.whole_dock_lifecycle;
  assert.equal(egpuPresentation(legacy).lifecycle.text, "Timed out");
});
