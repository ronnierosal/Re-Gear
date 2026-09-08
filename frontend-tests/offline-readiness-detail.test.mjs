import assert from "node:assert/strict";
import test from "node:test";

import { sanitizeJourneyStatus } from "../src/journey-status-delivery.ts";
import { journeyStatusRows } from "../src/quick-access-ui.ts";
import { sanitizeOfflineReasonCodes } from "../src/offline-readiness-detail.ts";

test("offline delivery explains the most important actionable reason", () => {
  const sanitized = sanitizeJourneyStatus({ offline_readiness: {
    schema_version: 1, status: "needs_attention",
    reason_codes: ["update_pending", "cloud_save_conflict", "private/path", "cloud_save_conflict"],
    title: "private game",
  }});
  assert.deepEqual(sanitized.offline_readiness.reason_codes, ["update_pending", "cloud_save_conflict"]);
  const row = journeyStatusRows(sanitized).find(row => row.name === "Offline readiness");
  assert.equal(row.value, "Needs attention");
  assert.equal(row.detail, "Resolve the Steam Cloud conflict for this game before going offline.");
  assert.doesNotMatch(JSON.stringify(sanitized), /private/);
});

test("malformed, oversized and inherited property names never become guidance", () => {
  for (const value of [null, {}, "update_pending", Array(17).fill("update_pending")]) {
    assert.deepEqual(sanitizeOfflineReasonCodes(value), []);
  }
  assert.deepEqual(sanitizeOfflineReasonCodes(["__proto__", "constructor", 1, {}]), []);
});

test("unavailable or stale evidence offers a next step without claiming success", () => {
  for (const [reason, text] of [
    ["offline_evidence_context_changed", "Select the game you want to check and try again."],
    ["offline_evidence_stale", "This check is out of date. Check the selected game again."],
    ["offline_evidence_game_active", "Close the game, then check again."],
  ]) {
    const rows = journeyStatusRows(sanitizeJourneyStatus({ offline_readiness: {
      schema_version: 1, status: "unknown", reason_codes: [reason],
    }}));
    const row = rows.find(row => row.name === "Offline readiness");
    assert.equal(row.value, "Unknown");
    assert.equal(row.detail, text);
  }
});
