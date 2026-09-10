import assert from "node:assert/strict";
import test from "node:test";

import { deliverBlockedAttempt } from "../src/blocked-attempt-delivery.ts";


const warning = {
  kind: "unknown",
  title: "Sleep blocked — safety state is unknown",
  body: "Re-Gear could not verify safe absence.",
  critical: true,
};

test("a modal delivery is preferred when the visible Steam host accepts it", () => {
  let modalCalls = 0;
  let toastCalls = 0;
  const result = deliverBlockedAttempt(warning, {
    showModal: () => { modalCalls += 1; },
    showFallbackToast: () => { toastCalls += 1; },
  });

  assert.equal(result, "modal");
  assert.equal(modalCalls, 1);
  assert.equal(toastCalls, 0);
});

test("a modal-host failure falls back to one critical attempted-action toast", () => {
  const toasts = [];
  const result = deliverBlockedAttempt(warning, {
    showModal: () => { throw new Error("modal host unavailable"); },
    showFallbackToast: (value) => { toasts.push(value); },
  });

  assert.equal(result, "fallback");
  assert.deepEqual(toasts, [warning]);
});

test("warning delivery failures never escape into the Steam suspend hook", () => {
  const result = deliverBlockedAttempt(warning, {
    showModal: () => { throw new Error("modal host unavailable"); },
    showFallbackToast: () => { throw new Error("toaster unavailable"); },
  });

  assert.equal(result, "unavailable");
});
