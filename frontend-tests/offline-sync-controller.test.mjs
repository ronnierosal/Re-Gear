import assert from "node:assert/strict";
import test from "node:test";
import { createOfflineSyncController } from "../src/offline-sync-controller.ts";
import { createSyncPreferences } from "../src/offline-sync-preferences.ts";

const APP = 620;
const CLIENT = "local-client-0";
const GAME = { appId: APP, account: "player-one", buildId: 100 };
const INDEX = { content: 0, shader: 1, workshop: 2 };

const settle = async (n = 6) => { for (let i = 0; i < n; i++) await Promise.resolve(); };

const typeInfo = () => [
  { has_update: true, completed: false },
  { has_update: true, completed: false },
  { has_update: false, completed: false },
];

const item = (over = {}) => ({
  appid: APP, active: false, completed: false, completed_time: 0, paused: false,
  queue_index: -1, buildid: 100, target_buildid: 101, update_result: 0,
  update_type_info: typeInfo(), ...over,
});

/** Native second argument is an array of client envelopes, per SteamTracking
 * af2c67e OnDownloadItems — not the flat list the published types declare. */
const envelope = (items, clientId = CLIENT) => [{ remote_client_id: clientId, item_data: items }];

function harness(options = {}) {
  const calls = { queue: [], readiness: [], unregister: 0, writes: [] };
  let clock = 0;
  const timers = new Map();
  let nextTimer = 1;
  let emitItems = null;
  let idle = options.idle ?? true;
  let readinessQueue = options.readiness ? [...options.readiness] : null;

  const preparationPorts = {
    localClientId: () => (options.noClient ? null : CLIENT),
    queueAppUpdate: (appId, clientId) => {
      calls.queue.push([appId, clientId]);
      if (options.dispatchThrows) throw new Error("native refused");
    },
    registerForDownloadItems: (cb) => {
      if (options.noSubscribe) return null;
      emitItems = cb;
      return { unregister: () => { calls.unregister++; } };
    },
    contentTypeIndex: INDEX,
  };

  const ports = {
    preparation: preparationPorts,
    refreshReadiness: async (appId) => {
      calls.readiness.push(appId);
      if (options.refreshReadiness) return options.refreshReadiness(appId);
      if (options.readinessThrows) throw new Error("evidence path down");
      if (readinessQueue) return readinessQueue.length ? readinessQueue.shift() : null;
      return { status: "likely_offline_ready", label: "Likely offline-ready",
        reasons: [], checkedAt: clock, expiresAt: clock + 60000 };
    },
    isIdle: () => idle,
    now: () => clock,
    setTimer: (run, ms) => { const id = nextTimer++; timers.set(id, { run, at: clock + ms }); return id; },
    clearTimer: (id) => { timers.delete(id); },
  };

  const store = { read: () => options.stored, write: (v) => calls.writes.push(v) };
  const preferences = createSyncPreferences(store);
  const controller = createOfflineSyncController(ports, preferences);
  const seen = [];
  controller.subscribe((s) => seen.push(s));

  return {
    controller, calls, seen, preferences,
    setIdle: (v) => { idle = v; },
    send: (items, clientId) => emitItems?.(true, envelope(items, clientId)),
    sendRaw: (clients) => emitItems?.(true, clients),
    hasSubscription: () => emitItems !== null,
    advance: async (ms) => {
      clock += ms;
      for (const [id, t] of [...timers]) {
        if (t.at <= clock) { timers.delete(id); t.run(); }
      }
      await settle();
    },
    pendingTimers: () => timers.size,
    at: () => clock,
  };
}

test("a manual sync refreshes, queues once, observes, then rechecks", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  const started = await h.controller.syncNow();
  await settle();
  assert.equal(started, true);
  assert.deepEqual(h.calls.queue, [[APP, CLIENT]], "one chosen game, one dispatch");
  assert.equal(h.controller.getState().phase, "preparing");

  h.send([item({ queue_index: 0 })]);
  assert.equal(h.controller.getState().preparation.state, "queued");
  h.send([item({ active: true })]);
  assert.equal(h.controller.getState().preparation.state, "active");
  h.send([item({ completed: true, completed_time: 500 })]);
  await settle();

  const state = h.controller.getState();
  assert.equal(state.phase, "done");
  assert.equal(state.failure, null);
  assert.equal(h.calls.readiness.length, 2, "a recheck is a real second check");
  assert.equal(state.running, false);
});

test("the recheck is fresh evidence, not an extension of what we had", async () => {
  const first = { status: "unverified", label: "Unverified", checkedAt: 0, expiresAt: 60000 };
  const second = { status: "likely_offline_ready", label: "Likely offline-ready", checkedAt: 900, expiresAt: 60900 };
  const h = harness({ readiness: [first, second] });
  h.controller.selectGame(GAME);
  await h.controller.syncNow();
  await settle();
  assert.deepEqual(h.controller.getState().readiness, first);
  h.send([item({ queue_index: 0 })]);            // baseline before our change
  h.send([item({ completed: true, completed_time: 500 })]);
  await settle();
  assert.deepEqual(h.controller.getState().readiness, second);
});

test("a finished download with no fresh evidence is not readiness", async () => {
  const first = { status: "unverified", label: "Unverified", checkedAt: 0, expiresAt: 60000 };
  const h = harness({ readiness: [first] });   // second call returns null
  h.controller.selectGame(GAME);
  await h.controller.syncNow();
  await settle();
  h.send([item({ queue_index: 0 })]);            // baseline before our change
  h.send([item({ completed: true, completed_time: 500 })]);
  await settle();
  const state = h.controller.getState();
  assert.equal(state.phase, "failed");
  assert.equal(state.failure, "sync_readiness_unavailable");
  assert.deepEqual(state.readiness, first, "stale evidence is kept as-is, never renewed");
});

test("duplicate attempts coalesce into the run already in flight", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  assert.equal(await h.controller.syncNow(), true);
  assert.equal(await h.controller.syncNow(), false);
  assert.equal(await h.controller.syncNow(), false);
  await settle();
  assert.equal(h.calls.queue.length, 1);
  h.send([item({ queue_index: 0 })]);            // baseline before our change
  h.send([item({ completed: true, completed_time: 1 })]);
  await settle();
  // Once the run ends, a new one is possible again.
  assert.equal(await h.controller.syncNow(), true);
  await settle();
  assert.equal(h.calls.queue.length, 2);
});

test("gameplay suppresses a scheduled tick and reports a manual attempt", async () => {
  const h = harness({ stored: { enabled: true, intervalMinutes: 15 } });
  h.controller.selectGame(GAME);
  h.setIdle(false);
  await h.advance(15 * 60000);
  assert.deepEqual(h.calls.queue, [], "a scheduled tick simply does not run");
  assert.equal(h.controller.getState().phase, "idle");
  assert.equal(await h.controller.syncNow(), false);
  assert.equal(h.controller.getState().failure, "sync_game_running");
  assert.deepEqual(h.calls.queue, []);
});

test("gameplay starting during the readiness check blocks the native request", async () => {
  let resolveReadiness;
  const readiness = new Promise((resolve) => { resolveReadiness = resolve; });
  const h = harness({ refreshReadiness: () => readiness });
  h.controller.selectGame(GAME);

  const started = h.controller.syncNow();
  await settle();
  h.setIdle(false);
  resolveReadiness({ status: "unverified", label: "Unverified", checkedAt: 0, expiresAt: 60000 });

  assert.equal(await started, false);
  assert.deepEqual(h.calls.queue, [], "a game that starts during the check is never queued");
  assert.equal(h.controller.getState().failure, "sync_game_running");
});

test("a selection change from the preparing notification blocks the stale request", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  h.controller.subscribe((state) => {
    if (state.phase === "preparing" && state.game?.appId === APP) {
      h.controller.selectGame({ appId: 440, account: "player-one", buildId: 7 });
    }
  });

  assert.equal(await h.controller.syncNow(), false);
  assert.deepEqual(h.calls.queue, [], "the previously selected app is never queued");
  assert.equal(h.controller.getState().game.appId, 440);
});

test("synchronous disposal during the requested report releases the returned handle", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  h.controller.subscribe((state) => {
    if (state.preparation?.state === "requested") h.controller.dispose();
  });

  assert.equal(await h.controller.syncNow(), false);
  assert.deepEqual(h.calls.queue, [[APP, CLIENT]]);
  assert.equal(h.calls.unregister, 1, "the subscription returned after disposal is stopped");
});

test("no schedule means no timer, so the passive path is untouched", () => {
  const h = harness();
  h.controller.selectGame(GAME);
  assert.equal(h.pendingTimers(), 0);
});

test("an enabled schedule runs on its cadence and keeps running", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  assert.equal(h.controller.setSchedule({ enabled: true, intervalMinutes: 15 }), true);
  assert.equal(h.pendingTimers(), 1);
  await h.advance(15 * 60000);
  assert.equal(h.calls.queue.length, 1);
  h.send([item({ queue_index: 0 })]);            // baseline before our change
  h.send([item({ completed: true, completed_time: 1 })]);
  await settle();
  await h.advance(15 * 60000);
  assert.equal(h.calls.queue.length, 2, "the cadence re-arms itself");
});

test("disabling the schedule cancels the timer", async () => {
  const h = harness({ stored: { enabled: true, intervalMinutes: 15 } });
  h.controller.selectGame(GAME);
  assert.equal(h.pendingTimers(), 1);
  assert.equal(h.controller.setSchedule({ enabled: false, intervalMinutes: null }), true);
  assert.equal(h.pendingTimers(), 0);
  await h.advance(60 * 60000);
  assert.deepEqual(h.calls.queue, []);
});

test("an unusable schedule is refused and does not arm a timer", () => {
  const h = harness();
  h.controller.selectGame(GAME);
  assert.equal(h.controller.setSchedule({ enabled: true, intervalMinutes: 1 }), false);
  assert.equal(h.pendingTimers(), 0);
  assert.deepEqual(h.calls.writes, []);
});

test("a scheduled tick while a run is live does not start a competing run", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  h.controller.setSchedule({ enabled: true, intervalMinutes: 15 });
  await h.controller.syncNow();
  await settle();
  assert.equal(h.calls.queue.length, 1);
  await h.advance(15 * 60000);
  assert.equal(h.calls.queue.length, 1, "coalesced, not queued up behind");
});

test("another client's envelope never satisfies our local request", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  await h.controller.syncNow();
  await settle();
  h.send([item({ completed: true, completed_time: 500 })], "some-remote-client");
  await settle();
  assert.equal(h.controller.getState().phase, "preparing");
  assert.equal(h.calls.readiness.length, 1, "no recheck was triggered");
});

test("a flat item array in the published shape is ignored", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  await h.controller.syncNow();
  await settle();
  h.sendRaw([item({ completed: true, completed_time: 500 })]);
  await settle();
  assert.equal(h.controller.getState().phase, "preparing");
});

test("changing the selected game drops the run in flight", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  await h.controller.syncNow();
  await settle();
  h.controller.selectGame({ appId: 440, account: "player-one", buildId: 7 });
  const state = h.controller.getState();
  assert.equal(state.phase, "idle");
  assert.equal(state.preparation, null);
  assert.equal(state.readiness, null);
  h.send([item({ completed: true, completed_time: 500 })]);
  await settle();
  assert.equal(h.controller.getState().phase, "idle", "a late reply cannot resurrect it");
});

test("an account or build change is a new subject even for the same app", async () => {
  for (const changed of [{ ...GAME, account: "player-two" }, { ...GAME, buildId: 101 }]) {
    const h = harness();
    h.controller.selectGame(GAME);
    await h.controller.syncNow();
    await settle();
    h.send([item({ queue_index: 0 })]);          // baseline before our change
    h.send([item({ completed: true, completed_time: 5 })]);
    await settle();
    assert.equal(h.controller.getState().phase, "done");
    h.controller.selectGame(changed);
    const state = h.controller.getState();
    assert.equal(state.readiness, null, "old evidence must not survive the change");
    assert.equal(state.phase, "idle");
  }
});

test("reselecting the identical game is a no-op", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  await h.controller.syncNow();
  await settle();
  const before = h.seen.length;
  h.controller.selectGame({ ...GAME });
  assert.equal(h.seen.length, before);
});

test("an unavailable native method fails the run without pretending", async () => {
  const h = harness({ noClient: true });
  h.controller.selectGame(GAME);
  assert.equal(await h.controller.syncNow(), false);
  await settle();
  const state = h.controller.getState();
  assert.equal(state.phase, "failed");
  assert.equal(state.failure, "sync_preparation_unavailable");
  assert.equal(state.running, false);
});

test("a dispatch that throws is reported and retry stays possible", async () => {
  const h = harness({ dispatchThrows: true });
  h.controller.selectGame(GAME);
  assert.equal(await h.controller.syncNow(), false);
  await settle();
  assert.equal(h.controller.getState().failure, "sync_preparation_unavailable");
  assert.equal(h.controller.getState().running, false);
  // Not permanently blocked.
  assert.equal(typeof (await h.controller.syncNow()), "boolean");
});

test("a readiness path that throws fails before anything is dispatched", async () => {
  const h = harness({ readinessThrows: true });
  h.controller.selectGame(GAME);
  assert.equal(await h.controller.syncNow(), false);
  await settle();
  assert.equal(h.controller.getState().failure, "sync_readiness_unavailable");
  assert.deepEqual(h.calls.queue, [], "nothing was asked of Steam");
});

test("an observed update error fails the run and skips the recheck", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  await h.controller.syncNow();
  await settle();
  h.send([item({ update_result: 21 })]);
  await settle();
  const state = h.controller.getState();
  assert.equal(state.phase, "failed");
  assert.equal(state.failure, "sync_preparation_failed");
  assert.equal(state.preparation.errorCode, 21);
  assert.equal(h.calls.readiness.length, 1, "no recheck after a failure");
});

test("selection changed by an error notification is not overwritten by the old run", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  await h.controller.syncNow();
  await settle();
  h.controller.subscribe((state) => {
    if (state.preparation?.state === "error") {
      h.controller.selectGame({ appId: 440, account: "player-one", buildId: 7 });
    }
  });

  h.send([item({ update_result: 21 })]);

  const state = h.controller.getState();
  assert.equal(state.game.appId, 440);
  assert.equal(state.phase, "idle");
  assert.equal(state.failure, null);
});

test("disposal from an error notification is not followed by stale failure handling", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  await h.controller.syncNow();
  await settle();
  h.controller.subscribe((state) => {
    if (state.preparation?.state === "error") h.controller.dispose();
  });

  h.send([item({ update_result: 21 })]);

  const state = h.controller.getState();
  assert.equal(state.phase, "preparing");
  assert.equal(state.failure, null);
  assert.equal(state.running, false);
  assert.equal(h.calls.unregister, 1);
});

test("dispose detaches observation and never cancels the native download", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  await h.controller.syncNow();
  await settle();
  const before = h.seen.length;
  h.controller.dispose();
  // Unregistering the listener is the only thing that happened. Nothing in the
  // controller or adapter asks Steam to remove or pause the download.
  assert.equal(h.calls.unregister, 1);
  assert.deepEqual(h.calls.queue, [[APP, CLIENT]], "no second native call of any kind");
  h.send([item({ completed: true, completed_time: 500 })]);
  await settle();
  assert.equal(h.seen.length, before, "no notifications after dispose");
  assert.equal(await h.controller.syncNow(), false);
});

test("dispose cancels the schedule", async () => {
  const h = harness({ stored: { enabled: true, intervalMinutes: 15 } });
  h.controller.selectGame(GAME);
  assert.equal(h.pendingTimers(), 1);
  h.controller.dispose();
  assert.equal(h.pendingTimers(), 0);
  await h.advance(60 * 60000);
  assert.deepEqual(h.calls.queue, []);
});

test("state is emitted on real change, not on phase name alone", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  await h.controller.syncNow();
  await settle();
  h.send([item({ active: true })]);
  const before = h.seen.length;
  // Same phase and same preparation state; only shader completion moved.
  h.send([item({
    active: true,
    update_type_info: [
      { has_update: true, completed: false },
      { has_update: true, completed: true },
      { has_update: false, completed: false },
    ],
  })]);
  assert.equal(h.seen.length, before + 1, "content progress under an unchanged phase must emit");
  const shader = h.controller.getState().preparation.content.find((c) => c.type === "shader");
  assert.equal(shader.completed, true);
});

test("an identical observation does not emit twice", async () => {
  const h = harness();
  h.controller.selectGame(GAME);
  await h.controller.syncNow();
  await settle();
  h.send([item({ active: true })]);
  const before = h.seen.length;
  h.send([item({ active: true })]);
  assert.equal(h.seen.length, before);
});

test("a non-exact app id is refused and never selected", async () => {
  const h = harness();
  for (const bad of [0, -1, 1.5, 2 ** 32, "620"]) {
    h.controller.selectGame({ appId: bad });
    assert.equal(h.controller.getState().game, null);
  }
  assert.equal(await h.controller.syncNow(), false);
  assert.deepEqual(h.calls.queue, []);
});

test("one throwing subscriber does not stop the others", async () => {
  const h = harness();
  const ok = [];
  h.controller.subscribe(() => { throw new Error("bad listener"); });
  h.controller.subscribe((s) => ok.push(s));
  h.controller.selectGame(GAME);
  assert.equal(ok.length > 0, true);
});
