import assert from "node:assert/strict";
import test from "node:test";

import { createUnplugWarningCoordinator } from "../src/unplug-warning-coordinator.ts";

const REQUEST = "a".repeat(32);
const NEXT = "b".repeat(32);

test("exact terminal retirement stops alarm without asserting physical absence", () => {
  const h = harness();
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  h.advance(3000);
  h.coordinator.retire(NEXT);
  assert.equal(h.coordinator.read().phase, "alarm", "foreign retirement is ignored");
  h.coordinator.retire(REQUEST);
  assert.deepEqual(h.coordinator.read(), { phase: "retired", requestId: REQUEST });
  assert.equal(h.timers(), 0);
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  h.advance(10000);
  assert.equal(h.warnings(), 1, "stale observation cannot restart a retired request");
  h.coordinator.observe({ requestId: NEXT, deauthorized: true });
  assert.equal(h.coordinator.read().phase, "prompt");
});

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

test("deauthorization prompts immediately, chimes at three seconds and repeats every two", () => {
  const h = harness();
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  assert.deepEqual(h.coordinator.read(), { phase: "prompt", requestId: REQUEST });
  assert.equal(h.timers(), 1);

  h.advance(2999);
  assert.equal(h.warnings(), 0);
  h.advance(1);
  assert.deepEqual(h.coordinator.read(), { phase: "alarm", requestId: REQUEST });
  assert.equal(h.warnings(), 1);
  assert.equal(h.timers(), 1, "only the repeating alarm remains");
  h.advance(1999);
  assert.equal(h.warnings(), 1, "no early repeat");
  h.advance(1);
  assert.equal(h.warnings(), 2);
  h.advance(1999);
  assert.equal(h.warnings(), 2, "repeat cadence remains two seconds");
  h.advance(1);
  assert.equal(h.warnings(), 3);
});

test("duplicate observations do not restart escalation or duplicate audio", () => {
  const h = harness();
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  h.advance(2000);
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  assert.equal(h.timers(), 1);
  h.advance(1000);
  assert.equal(h.warnings(), 1, "the original three-second deadline survives rerender");
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  assert.equal(h.timers(), 1, "alarm polling does not duplicate the interval");
});

test("only exact correlated strict absence clears the warning", () => {
  const h = harness();
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  h.advance(3000);

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
  h.advance(3000);
  assert.deepEqual(h.coordinator.read(), { phase: "cleared", requestId: REQUEST });
  assert.equal(h.warnings(), 0);
  assert.equal(h.timers(), 0);
});

test("first correlated observation after remount may already be absent", () => {
  const h = harness();
  h.coordinator.observe({ requestId: REQUEST, physicalAbsenceVerified: true });
  assert.deepEqual(h.coordinator.read(), { phase: "cleared", requestId: REQUEST });
  assert.equal(h.timers(), 0);
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  assert.equal(h.coordinator.read().phase, "cleared");
});

test("synchronous stop while publishing prompt leaves no escalation timer", () => {
  const h = harness();
  h.coordinator.subscribe((state) => {
    if (state.phase === "prompt") h.coordinator.stop();
  });
  h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
  assert.deepEqual(h.coordinator.read(), { phase: "idle", requestId: null });
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
  h.advance(2999);
  assert.equal(h.warnings(), 0, "the cancelled request cannot alarm");
  h.advance(1);
  assert.equal(h.warnings(), 1);
  h.coordinator.stop();
  assert.deepEqual(h.coordinator.read(), { phase: "idle", requestId: null });
  assert.equal(h.timers(), 0);
});

test("unverified or malformed observations never start a reminder", () => {
  for (const observation of [
    { requestId: REQUEST },
    { requestId: REQUEST, deauthorized: false },
    { requestId: REQUEST, deauthorized: "true" },
    { requestId: "invalid", deauthorized: true },
    { deauthorized: true },
  ]) {
    const h = harness();
    h.coordinator.observe(observation);
    h.advance(10000);
    assert.deepEqual(h.coordinator.read(), { phase: "idle", requestId: null });
    assert.equal(h.timers(), 0);
    assert.equal(h.warnings(), 0);
  }
});

test("exact absence, retirement and stop before the first chime cancel every timer", () => {
  for (const end of ["absence", "retirement", "stop"]) {
    const h = harness();
    h.coordinator.observe({ requestId: REQUEST, deauthorized: true });
    h.advance(2999);
    h.coordinator.observe({ requestId: NEXT, physicalAbsenceVerified: true });
    h.coordinator.retire(NEXT);
    assert.equal(h.coordinator.read().phase, "prompt", "foreign proof or retirement is ignored");
    if (end === "absence") {
      h.coordinator.observe({ requestId: REQUEST, physicalAbsenceVerified: true });
      assert.equal(h.coordinator.read().phase, "cleared");
    } else if (end === "retirement") {
      h.coordinator.retire(REQUEST);
      assert.equal(h.coordinator.read().phase, "retired", "retirement never asserts physical absence");
    } else {
      h.coordinator.stop();
      assert.deepEqual(h.coordinator.read(), { phase: "idle", requestId: null });
    }
    h.advance(10000);
    assert.equal(h.warnings(), 0);
    assert.equal(h.timers(), 0);
  }
});
