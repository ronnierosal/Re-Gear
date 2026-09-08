import assert from "node:assert/strict";
import test from "node:test";
import { sanitizeAutoTdpPreferences } from "../src/auto-tdp-preferences-ui.ts";

const row = { placement: "portable", target_fps: 40, minimum_watts: 7, maximum_watts: 25 };
const payload = { schema_version: 1, code: "auto_tdp_preferences.loaded", preferences: [row] };
test("saved mode preferences remain distinct and reject malformed values", () => {
  assert.notEqual(sanitizeAutoTdpPreferences(payload), null);
  assert.notEqual(sanitizeAutoTdpPreferences({ ...payload, preferences: [row, { ...row, placement: "docked_egpu" }] }), null);
  assert.equal(sanitizeAutoTdpPreferences({ ...payload, preferences: [row, row] }), null);
  for (const change of [{ placement: "unknown" }, { minimum_watts: true }, { maximum_watts: 3 }, { target_fps: Infinity }, { target_fps: "40" }]) {
    assert.equal(sanitizeAutoTdpPreferences({ ...payload, preferences: [{ ...row, ...change }] }), null);
  }
  assert.equal(sanitizeAutoTdpPreferences({ ...payload, code: "private path" }), null);
});
