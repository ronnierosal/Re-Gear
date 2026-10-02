import assert from "node:assert/strict";
import test from "node:test";
import { createOfflineSyncRuntime } from "../src/offline-sync-runtime.ts";

const APP = 620;
const CLIENT = "local-client-0";
const GAME = { appId: APP, name: "Portal 2", account: "player-one", buildId: 100 };
const INDEX = { content: 0, shader: 1, workshop: 2 };

const settle = async (n = 8) => { for (let i = 0; i < n; i++) await Promise.resolve(); };

const item = (over = {}) => ({
  appid: APP, active: false, completed: false, completed_time: 0, paused: false,
  queue_index: -1, buildid: 100, target_buildid: 101, update_result: 0,
  update_type_info: [{ has_update: true, completed: false }, { has_update: false, completed: false }, {}],
  ...over,
});
const envelope = (items) => [{ remote_client_id: CLIENT, item_data: items }];

/** Fake native and evidence ports. Nothing here touches Steam. */
function harness(options = {}) {
  const calls = { queue: [], readiness: [], writes: [], unregister: 0 };
  let clock = 1000;
  let idle = options.idle ?? true;
  let emitItems = null;
  const timers = new Map();
  let nextTimer = 1;
  let stored = options.stored;
  let readinessGate = null;

  const ports = {
    preparation: {
      localClientId: () => (options.noClient ? null : CLIENT),
      queueAppUpdate: (appId, clientId) => calls.queue.push([appId, clientId]),
      registerForDownloadItems: (cb) => { emitItems = cb; return { unregister: () => { calls.unregister++; } }; },
      contentTypeIndex: INDEX,
    },
    refreshReadiness: async (appId) => {
      calls.readiness.push(appId);
      if (readinessGate) await readinessGate.promise;
      if (options.readiness) return options.readiness(appId, calls.readiness.length);
      return { status: "likely_offline_ready", label: "Likely offline-ready", reasons: ["r"],
        checkedAt: clock + calls.readiness.length, expiresAt: clock + 60000 };
    },
    isIdle: () => idle,
    now: () => clock,
    setTimer: (run, ms) => { const id = nextTimer++; timers.set(id, { run, at: clock + ms }); return id; },
    clearTimer: (id) => { timers.delete(id); },
    preferencesStore: {
      read: () => stored,
      write: (value) => {
        if (options.refuseWrites) throw new Error("storage unavailable");
        calls.writes.push(value); stored = value;
      },
    },
  };
  const runtime = createOfflineSyncRuntime(ports);
  const seen = [];
  runtime.subscribe((s) => seen.push(s));
  return {
    runtime, calls, seen,
    snap: () => runtime.getSnapshot(),
    send: (items) => emitItems?.(true, envelope(items)),
    setIdle: (v) => { idle = v; },
    holdReadiness: () => {
      let release; const promise = new Promise((r) => { release = r; });
      readinessGate = { promise, release: () => { readinessGate = null; release(); } };
      return readinessGate;
    },
    advance: async (ms) => {
      clock += ms;
      for (const [id, t] of [...timers]) if (t.at <= clock) { timers.delete(id); t.run(); }
      await settle();
    },
    pendingTimers: () => timers.size,
  };
}

const ready = (h) => { h.runtime.applyInitialState({ available: true, game: GAME }); return h; };

test("loading until initial state resolves, and reads never dispatch", () => {
  const h = harness();
  assert.equal(h.snap().loading, true);
  assert.equal(h.snap().capabilities.canSyncNow, false);
  for (let i = 0; i < 5; i++) { h.runtime.getSnapshot(); h.runtime.subscribe(() => {}); }
  assert.deepEqual(h.calls.queue, []);
  assert.deepEqual(h.calls.readiness, []);
  assert.equal(h.pendingTimers(), 0);
});

test("unavailable preparation is reported honestly and refuses actions", () => {
  const h = harness();
  h.runtime.applyInitialState({ available: false, unavailableReason: "Steam downloads API is unavailable", game: GAME });
  const s = h.snap();
  assert.equal(s.loading, false);
  assert.equal(s.available, false);
  assert.equal(s.unavailableReason, "Steam downloads API is unavailable");
  assert.equal(h.runtime.syncNow(), false);
  assert.deepEqual(h.calls.queue, []);
});

test("schedule stays default-off and comes only from Re-Gear's stored preference", async () => {
  for (const stored of [undefined, null, { enabled: true }, { enabled: true, intervalMinutes: 1 }, "x"]) {
    const h = ready(harness({ stored }));
    assert.deepEqual(h.snap().schedule, { enabled: false, intervalMinutes: null });
    assert.equal(h.pendingTimers(), 0, "no timer is armed without consent");
  }
  const h = ready(harness({ stored: { enabled: true, intervalMinutes: 30 } }));
  assert.deepEqual(h.snap().schedule, { enabled: true, intervalMinutes: 30 });
  assert.equal(h.pendingTimers(), 1);
});

test("Sync now: one game, one dispatch, observed progress, then a real recheck", async () => {
  const h = ready(harness());
  assert.equal(h.runtime.syncNow(), true);
  assert.equal(h.snap().preparation.inFlight, true);
  await settle();
  assert.deepEqual(h.calls.queue, [[APP, CLIENT]]);
  assert.equal(h.snap().readiness.status, "likely_offline_ready");
  h.send([item({ queue_index: 0 })]);
  assert.equal(h.snap().preparation.state, "queued");
  h.send([item({ active: true })]);
  assert.equal(h.snap().preparation.state, "active");
  h.send([item({ completed: true, completed_time: 9 })]);
  // The download finished but readiness is still being re-measured.
  assert.equal(h.snap().preparation.inFlight, true);
  await settle();
  assert.equal(h.calls.readiness.length, 2, "readiness was re-measured, not assumed");
  assert.equal(h.snap().preparation.state, "completed");
  assert.equal(h.snap().preparation.inFlight, false);
  assert.equal(h.snap().capabilities.canSyncNow, true);
});

test("a completed download is never reported as offline readiness", async () => {
  const h = ready(harness({
    readiness: (_app, n) => ({ status: "needs_preparation", label: "Needs preparation", reasons: [],
      checkedAt: 1000 + n, expiresAt: 61000 }),
  }));
  h.runtime.syncNow();
  await settle();
  h.send([item({ active: true })]);
  h.send([item({ completed: true, completed_time: 9 })]);
  await settle();
  assert.equal(h.snap().preparation.state, "completed");
  assert.equal(h.snap().readiness.status, "needs_preparation");
});

test("an unrecognised readiness status is shown as unverified", async () => {
  const h = ready(harness({
    readiness: () => ({ status: "ready_for_anything", label: "?", checkedAt: 1001, expiresAt: 61000 }),
  }));
  h.runtime.syncNow();
  await settle();
  assert.equal(h.snap().readiness.status, "unverified");
});

test("duplicate presses while a run is in flight dispatch once", async () => {
  const h = ready(harness());
  assert.equal(h.runtime.syncNow(), true);
  assert.equal(h.runtime.syncNow(), false);
  assert.equal(h.runtime.syncNow(), false);
  await settle();
  assert.equal(h.calls.queue.length, 1);
});

test("Sync now while a game runs fails closed without dispatch", async () => {
  const h = ready(harness({ idle: false }));
  h.runtime.syncNow();
  await settle();
  assert.deepEqual(h.calls.queue, []);
  assert.equal(h.snap().preparation.state, "error");
  assert.equal(h.snap().preparation.inFlight, false);
  h.setIdle(true);
  assert.equal(h.runtime.syncNow(), true, "the press is retryable once idle");
});

test("gameplay starting during the readiness check stops before dispatch", async () => {
  const h = ready(harness());
  const gate = h.holdReadiness();
  h.runtime.syncNow();
  h.setIdle(false);
  gate.release();
  await settle();
  assert.deepEqual(h.calls.queue, []);
  assert.equal(h.snap().preparation.inFlight, false);
});

test("a local client that cannot be identified fails the press, not the tab", async () => {
  const h = ready(harness({ noClient: true }));
  assert.equal(h.runtime.syncNow(), true);
  await settle();
  assert.deepEqual(h.calls.queue, [], "never dispatched to a guessed client");
  assert.equal(h.snap().preparation.state, "error");
  assert.equal(h.snap().preparation.inFlight, false);
  assert.equal(h.snap().available, true);
});

test("selecting another game discards late work from the previous one", async () => {
  const h = ready(harness());
  const gate = h.holdReadiness();
  h.runtime.syncNow();
  const before = h.snap().generation;
  h.runtime.selectGame({ appId: 730, name: "Other", account: "player-one", buildId: 5 });
  assert.notEqual(h.snap().generation, before);
  gate.release();
  await settle();
  assert.deepEqual(h.calls.queue, [], "no dispatch for a game no longer selected");
  assert.equal(h.snap().game.appId, 730);
  assert.equal(h.snap().readiness.status, null);
  assert.equal(h.snap().preparation.state, "idle");
});

test("a rebuilt or re-owned game is a new subject; a renamed one is not", async () => {
  const h = ready(harness());
  const g0 = h.snap().generation;
  h.runtime.selectGame({ ...GAME, name: "Portal 2 (renamed)" });
  assert.equal(h.snap().generation, g0);
  h.runtime.selectGame({ ...GAME, buildId: 101 });
  const g1 = h.snap().generation;
  assert.notEqual(g1, g0);
  h.runtime.selectGame({ ...GAME, buildId: 101, account: "player-two" });
  assert.notEqual(h.snap().generation, g1);
});

test("a schedule the store refuses is not shown and arms nothing", () => {
  const h = ready(harness({ refuseWrites: true }));
  assert.equal(h.runtime.setSyncSchedule({ enabled: true, intervalMinutes: 60 }), false);
  assert.deepEqual(h.snap().schedule, { enabled: false, intervalMinutes: null });
  assert.equal(h.pendingTimers(), 0);
});

test("an out-of-range schedule is refused before any write", () => {
  const h = ready(harness());
  assert.equal(h.runtime.setSyncSchedule({ enabled: true, intervalMinutes: 5 }), false);
  assert.deepEqual(h.calls.writes, []);
  assert.equal(h.runtime.setSyncSchedule({ enabled: true, intervalMinutes: 60 }), true);
  assert.deepEqual(h.calls.writes, [{ enabled: true, intervalMinutes: 60 }]);
  assert.deepEqual(h.snap().schedule, { enabled: true, intervalMinutes: 60 });
  assert.equal(h.pendingTimers(), 1);
  assert.equal(h.runtime.setSyncSchedule({ enabled: false, intervalMinutes: null }), true);
  assert.equal(h.pendingTimers(), 0);
});

test("a scheduled run shows progress and a press during it joins the same run", async () => {
  const h = ready(harness({ stored: { enabled: true, intervalMinutes: 15 } }));
  await h.advance(15 * 60000);
  await settle();
  assert.equal(h.calls.queue.length, 1);
  h.send([item({ active: true })]);
  assert.equal(h.snap().preparation.state, "active");
  assert.equal(h.snap().preparation.inFlight, false, "a scheduled run is not a press");
  assert.equal(h.runtime.syncNow(), true);
  await settle();
  assert.equal(h.calls.queue.length, 1, "the press joined the run instead of dispatching again");
  h.send([item({ completed: true, completed_time: 9 })]);
  await settle();
  assert.equal(h.snap().preparation.state, "completed");
  assert.equal(h.snap().preparation.inFlight, false);
});

test("a scheduled tick during gameplay does nothing", async () => {
  const h = ready(harness({ stored: { enabled: true, intervalMinutes: 15 }, idle: false }));
  await h.advance(15 * 60000);
  assert.deepEqual(h.calls.queue, []);
  assert.deepEqual(h.calls.readiness, []);
  assert.equal(h.snap().preparation.state, "idle");
});

test("a download removed from Steam's list releases the press", async () => {
  const h = ready(harness());
  h.runtime.syncNow();
  await settle();
  h.send([item({ queue_index: 0 })]);
  h.send([]);
  await settle();
  assert.equal(h.snap().preparation.state, "unconfirmed");
  assert.equal(h.snap().preparation.inFlight, false);
  assert.equal(h.runtime.syncNow(), true);
});

test("a void dispatch that Steam never shows expires to unconfirmed", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const h = ready(harness());
  h.runtime.syncNow();
  await settle();
  t.mock.timers.tick(30000);
  await settle();
  assert.equal(h.snap().preparation.state, "unconfirmed");
  assert.equal(h.snap().preparation.inFlight, false);
});

test("readiness renewal comes only from a real check, never from a schedule tick or download", async () => {
  const h = ready(harness());
  h.runtime.syncNow();
  await settle();
  const expiresAt = h.snap().readiness.expiresAt;
  h.send([item({ active: true })]);
  assert.equal(h.snap().readiness.expiresAt, expiresAt);
  await h.advance(61000);
  assert.equal(h.snap().readiness.expired, true);
});

test("disposal detaches observation without cancelling the native download", async () => {
  const h = ready(harness());
  h.runtime.syncNow();
  await settle();
  h.send([item({ active: true })]);
  const seen = h.seen.length;
  h.runtime.dispose();
  h.runtime.dispose();
  assert.equal(h.calls.unregister, 1, "only our observer was released");
  h.send([item({ completed: true, completed_time: 9 })]);
  await settle();
  assert.equal(h.seen.length, seen);
  assert.equal(h.runtime.syncNow(), false);
  assert.equal(h.pendingTimers(), 0);
});

test("a fresh runtime after unload starts clean from the stored preference", async () => {
  const first = ready(harness({ stored: { enabled: true, intervalMinutes: 30 } }));
  first.runtime.syncNow();
  await settle();
  first.runtime.dispose();
  const second = ready(harness({ stored: { enabled: true, intervalMinutes: 30 } }));
  assert.equal(second.snap().preparation.state, "idle");
  assert.equal(second.snap().preparation.inFlight, false);
  assert.deepEqual(second.snap().schedule, { enabled: true, intervalMinutes: 30 });
});
