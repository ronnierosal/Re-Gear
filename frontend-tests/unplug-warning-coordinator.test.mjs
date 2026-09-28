import assert from "node:assert/strict";
import test from "node:test";

import { createUnplugWarningCoordinator } from "../src/unplug-warning-coordinator.ts";

const REQUEST = "a".repeat(32);
const NEXT = "b".repeat(32);

function harness() {
  let now = 0;
  let next = 1;
  let warnings = 0;
  const timers = new Map();
  const schedule = (run, delay, repeating = false) => {
    const id = next++;
    timers.set(id, { run, at: now + delay, delay, repeating });
    return id;
  };
  const coordinator = createUnplugWarningCoordinator({
    schedule: (run, delay) => schedule(run, delay),
    cancel: (id) => timers.delete(id),
    repeat: (run, delay) => schedule(run, delay, true),
    cancelRepeat: (id) => timers.delete(id),
    playWarning: () => { warnings++; },
  });
  return {
    coordinator,
    warnings: () => warnings,
    timers: () => timers.size,
    advance(ms) {
      const target = now + ms;
      while (true) {
        const due = [...timers.entries()]
          .filter(([, timer]) => timer.at <= target)
          .sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        const [id, timer] = due;
        now = timer.at;
        if (timer.repeating) timer.at += timer.delay;
        else timers.delete(id);
        timer.run();
      }
      now = target;
    },
  };
}

test("deauthorization prompts immediately and escalates once after five seconds", () => {
  const h = harness();
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  assert.deepEqual(h.coordinator.read(), { phase: "prompt", requestId: REQUEST });
  assert.equal(h.timers(), 1);

  h.advance(4999);
  assert.equal(h.warnings(), 0);
  h.advance(1);
  assert.deepEqual(h.coordinator.read(), { phase: "alarm", requestId: REQUEST });
  assert.equal(h.warnings(), 1);
  assert.equal(h.timers(), 1, "only the repeating alarm remains");
  h.advance(4000);
  assert.equal(h.warnings(), 3);
});

test("duplicate observations do not restart escalation or duplicate audio", () => {
  const h = harness();
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  h.advance(4000);
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  assert.equal(h.timers(), 1);
  h.advance(1000);
  assert.equal(h.warnings(), 1, "the original five-second deadline survives rerender");
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  assert.equal(h.timers(), 1, "alarm polling does not duplicate the interval");
});

test("only exact correlated strict absence clears the warning", () => {
  const h = harness();
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  h.advance(5000);

  h.coordinator.observe({ requestId: NEXT, physicalAbsenceVerified: true });
  h.coordinator.observe({ requestId: REQUEST });
  assert.equal(h.coordinator.read().phase, "alarm");
  assert.equal(h.timers(), 1);

  h.coordinator.observe({ requestId: REQUEST, physicalAbsenceVerified: true });
  assert.deepEqual(h.coordinator.read(), { phase: "cleared", requestId: REQUEST });
  assert.equal(h.timers(), 0);
  const before = h.warnings();
  h.advance(10000);
  assert.equal(h.warnings(), before);
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  assert.deepEqual(h.coordinator.read(), { phase: "cleared", requestId: REQUEST },
    "late software-down replay cannot reopen a cleared request");
  assert.equal(h.timers(), 0);
});

test("synchronous clear during escalation installs no sound or interval", () => {
  const h = harness();
  h.coordinator.subscribe((state) => {
    if (state.phase === "alarm") {
      h.coordinator.observe({ requestId: REQUEST, physicalAbsenceVerified: true });
    }
  });
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  h.advance(5000);
  assert.deepEqual(h.coordinator.read(), { phase: "cleared", requestId: REQUEST });
  assert.equal(h.warnings(), 0);
  assert.equal(h.timers(), 0);
});

test("sound failure does not cancel the repeating warning lifecycle", () => {
  let plays = 0;
  let interval;
  const coordinator = createUnplugWarningCoordinator({
    schedule(run) { run(); return 1; },
    cancel() {},
    repeat(run) { interval = run; return 2; },
    cancelRepeat() {},
    playWarning() { plays++; throw new Error("native sound unavailable"); },
  });
  coordinator.observe({ requestId: REQUEST, deauthorized: true });
  assert.equal(coordinator.read().phase, "alarm");
  assert.equal(plays, 1);
  interval();
  assert.equal(plays, 2);
});

test("a new request replaces old timers and stop tears everything down", () => {
  const h = harness();
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  h.advance(2000);
  h.coordinator.observe({ requestId: NEXT, deauthorized: true });
  assert.deepEqual(h.coordinator.read(), { phase: "prompt", requestId: NEXT });
  assert.equal(h.timers(), 1);
  h.advance(3000);
  assert.equal(h.warnings(), 0, "the cancelled request cannot alarm");
  h.advance(2000);
  assert.equal(h.warnings(), 1);
  h.coordinator.stop();
  assert.deepEqual(h.coordinator.read(), { phase: "idle", requestId: null });
  assert.equal(h.timers(), 0);
});
