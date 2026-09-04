import assert from "node:assert/strict";
import test from "node:test";

import { healthAttentionMessages, healthStatusLabel } from "../src/health-ui.ts";


test("primary health label remains categorical and controller-friendly", () => {
  for (const [state, expected] of [
    ["ready", "Ready"],
    ["recovering", "Recovering"],
    ["degraded", "Degraded"],
    ["attention_required", "Needs attention"],
  ]) {
    assert.equal(healthStatusLabel({ state }), expected);
  }
});

test("missing health never resembles a healthy system", () => {
  assert.equal(healthStatusLabel(undefined), "Unavailable");
  assert.equal(healthStatusLabel(undefined, true), "Checking…");
});

test("health attention exposes only bounded controller-readable messages", () => {
  const messages = healthAttentionMessages({
    state: "attention_required",
    blockers: [
      "health.display_unknown",
      "private.health.code",
      "health.display_unknown",
      "health.controller_unknown",
      "health.audio_unknown",
    ],
  });
  assert.deepEqual(messages, [
    "Active display needs verification.",
    "Re-Gear health evidence needs review.",
    "Built-in controls need verification.",
  ]);
  assert.doesNotMatch(JSON.stringify(messages), /private\.health\.code/);
  assert.deepEqual(healthAttentionMessages({ state: "ready", blockers: ["health.display_unknown"] }), []);
});
