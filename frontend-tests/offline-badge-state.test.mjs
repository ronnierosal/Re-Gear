import assert from "node:assert/strict";
import test from "node:test";
import { offlineReportBadge } from "../src/offline-badge-state.ts";

test("limited Steam reports use supplied attention and verify icons", () => {
  assert.deepEqual(offlineReportBadge({ schema_version: 1, status: "needs_attention", reason_codes: ["update_pending"] }), { asset: "offline-attention", label: "Offline needs attention" });
  assert.deepEqual(offlineReportBadge({ schema_version: 1, status: "online_check_needed", reason_codes: ["steam_entitlement_unknown"] }), { asset: "offline-verify", label: "Online check needed" });
});

test("unknown, malformed, or insufficient reports never get a positive or internet-required badge", () => {
  for (const status of ["unknown", "ready_to_try_offline", "internet_required", "made_up"]) {
    assert.equal(offlineReportBadge({ schema_version: 1, status, reason_codes: ["local_readiness_confirmed"] }), null);
  }
  for (const report of [null, [], {}, { schema_version: 2, status: "needs_attention", reason_codes: ["update_pending"] }, { schema_version: 1, status: "needs_attention", reason_codes: ["private"] }]) {
    assert.equal(offlineReportBadge(report), null);
  }
});
