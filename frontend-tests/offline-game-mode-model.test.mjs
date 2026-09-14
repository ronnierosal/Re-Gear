import assert from "node:assert/strict";
import test from "node:test";
import {
  createOfflineGameModeModel,
  isExactAppId,
} from "../src/offline-game-mode-model.ts";

const GAME = { appId: 620, name: "Portal 2" };
const OTHER = { appId: 440, name: "Team Fortress 2" };

function harness(initial = { available: true, game: GAME }) {
  const calls = { sync: [], schedule: [] };
  let clock = 1000;
  const ports = {
    startSync: (appId, generation, attempt) => calls.sync.push([appId, generation, attempt]),
    persistSchedule: (s) => calls.schedule.push(s),
    now: () => clock,
  };
  const model = createOfflineGameModeModel(ports, { initial });
  const seen = [];
  model.subscribe((s) => seen.push(s));
  return { model, calls, seen, tick: (ms) => { clock += ms; }, at: () => clock };
}

const readiness = (h, over = {}) => ({
  generation: h.model.getSnapshot().generation,
  appId: GAME.appId,
  status: "likely_offline_ready",
  label: "Likely offline-ready",
  reasons: ["Steam reports ready to launch."],
  checkedAt: h.at(),
  expiresAt: h.at() + 60000,
  ...over,
});

const prep = (h, over = {}) => ({
  generation: h.model.getSnapshot().generation,
  attempt: h.model.getSnapshot().attempt,
  appId: GAME.appId,
  state: "active",
  ...over,
});

test("reads never dispatch a command", () => {
  const h = harness();
  for (let i = 0; i < 5; i++) { h.model.getSnapshot(); h.model.subscribe(() => {}); }
  assert.deepEqual(h.calls.sync, []);
  assert.deepEqual(h.calls.schedule, []);
});

test("unresolved initial state reports loading rather than a confident empty view", () => {
  const model = createOfflineGameModeModel(
    { startSync() {}, persistSchedule() {}, now: () => 0 }, {},
  );
  const before = model.getSnapshot();
  assert.equal(before.loading, true);
  assert.equal(before.available, false);
  assert.equal(before.capabilities.canSyncNow, false);
  model.applyInitialState({ available: true, game: GAME });
  const after = model.getSnapshot();
  assert.equal(after.loading, false);
  assert.equal(after.available, true);
  assert.equal(after.game.appId, GAME.appId);
});

test("an unavailable model explains itself and refuses every action", () => {
  const h = harness({ available: false, unavailableReason: "Steam is not reachable" });
  const s = h.model.getSnapshot();
  assert.equal(s.available, false);
  assert.equal(s.unavailableReason, "Steam is not reachable");
  assert.equal(h.model.syncNow(), false);
  assert.equal(h.model.setSyncSchedule({ enabled: true, intervalMinutes: 60 }), false);
  h.model.selectGame(OTHER);
  assert.equal(h.model.getSnapshot().game, null);
  assert.deepEqual(h.calls.sync, []);
  assert.deepEqual(h.calls.schedule, []);
});

test("a manual sync calls the port exactly once and reports requested", () => {
  const h = harness();
  assert.equal(h.model.syncNow(), true);
  const s = h.model.getSnapshot();
  assert.deepEqual(h.calls.sync, [[GAME.appId, s.generation, s.attempt]]);
  assert.equal(s.preparation.state, "requested");
  assert.equal(s.preparation.inFlight, true);
  assert.equal(s.capabilities.canSyncNow, false);
});

test("a command return is never an outcome; only an observation moves state", () => {
  const h = harness();
  h.model.syncNow();
  // The port returned normally. That is not queued, and certainly not completed.
  assert.equal(h.model.getSnapshot().preparation.state, "requested");
  h.model.applyPreparation(prep(h, { state: "queued" }));
  assert.equal(h.model.getSnapshot().preparation.state, "queued");
});

test("duplicate presses are suppressed while in flight and released on any terminal state", () => {
  for (const terminal of ["completed", "error", "unconfirmed"]) {
    const h = harness();
    assert.equal(h.model.syncNow(), true);
    assert.equal(h.model.syncNow(), false);
    assert.equal(h.model.syncNow(), false);
    assert.equal(h.calls.sync.length, 1);
    h.model.applyPreparation(prep(h, { state: terminal }));
    assert.equal(h.model.getSnapshot().preparation.inFlight, false);
    assert.equal(h.model.getSnapshot().capabilities.canSyncNow, true);
    // Retry is never permanently blocked.
    assert.equal(h.model.syncNow(), true);
    assert.equal(h.calls.sync.length, 2);
  }
});

test("a port that throws surfaces an error and leaves retry available", () => {
  const h = harness();
  h.model.getSnapshot();
  const model = createOfflineGameModeModel(
    { startSync() { throw new Error("native gone"); }, persistSchedule() {}, now: () => 0 },
    { initial: { available: true, game: GAME } },
  );
  assert.equal(model.syncNow(), false);
  const s = model.getSnapshot();
  assert.equal(s.preparation.state, "error");
  assert.equal(s.preparation.inFlight, false);
  assert.equal(s.capabilities.canSyncNow, true);
});

test("same-state progress still notifies: a content entry completing is a real change", () => {
  const h = harness();
  h.model.syncNow();
  h.model.applyPreparation(prep(h, {
    state: "active",
    content: [{ type: "shader", hasUpdate: true, completed: false, bytesDownloaded: 0, bytesTotal: 100 }],
  }));
  const before = h.seen.length;
  h.model.applyPreparation(prep(h, {
    state: "active",
    content: [{ type: "shader", hasUpdate: true, completed: true, bytesDownloaded: 100, bytesTotal: 100 }],
  }));
  assert.equal(h.seen.length, before + 1, "shader completion under an unchanged state must notify");
  const shader = h.model.getSnapshot().preparation.content.find((c) => c.type === "shader");
  assert.equal(shader.completed, true);
  assert.equal(shader.bytesDownloaded, 100);
});

test("an identical observation does not notify twice", () => {
  const h = harness();
  h.model.applyPreparation(prep(h, { state: "active" }));
  const before = h.seen.length;
  h.model.applyPreparation(prep(h, { state: "active" }));
  assert.equal(h.seen.length, before);
});

test("an observation for another game or an old generation is dropped", () => {
  const h = harness();
  h.model.syncNow();
  assert.equal(h.model.applyPreparation(prep(h, { appId: OTHER.appId, state: "completed" })), false);
  assert.equal(h.model.applyReadiness(readiness(h, { appId: OTHER.appId })), false);
  const stale = h.model.getSnapshot().generation;
  h.model.selectGame(OTHER);
  assert.equal(h.model.applyPreparation({ generation: stale, appId: GAME.appId, state: "completed" }), false);
  assert.equal(h.model.getSnapshot().preparation.state, "idle");
});

test("selecting a game resets readiness and preparation and bumps the generation", () => {
  const h = harness();
  h.model.applyReadiness(readiness(h));
  h.model.applyPreparation(prep(h, { state: "active" }));
  const before = h.model.getSnapshot();
  assert.equal(before.readiness.status, "likely_offline_ready");
  h.model.selectGame(OTHER);
  const after = h.model.getSnapshot();
  assert.equal(after.generation > before.generation, true);
  assert.equal(after.readiness.status, null);
  assert.equal(after.preparation.state, "idle");
  assert.equal(after.preparation.inFlight, false);
});

test("re-selecting the same game is a no-op and does not reset evidence", () => {
  const h = harness();
  h.model.applyReadiness(readiness(h));
  const before = h.model.getSnapshot();
  h.model.selectGame({ ...GAME });
  assert.equal(h.model.getSnapshot(), before);
});

test("a non-exact app id is refused", () => {
  const h = harness();
  for (const bad of [0, -1, 1.5, 2 ** 32, "620"]) {
    h.model.selectGame({ appId: bad, name: "bad" });
    assert.equal(h.model.getSnapshot().game.appId, GAME.appId);
  }
});

test("readiness expires on the clock and expiry is computed, never stored stale", () => {
  const h = harness();
  h.model.applyReadiness(readiness(h));
  assert.equal(h.model.getSnapshot().readiness.expired, false);
  h.tick(59999);
  assert.equal(h.model.getSnapshot().readiness.expired, false);
  h.tick(1);
  assert.equal(h.model.getSnapshot().readiness.expired, true);
  assert.equal(h.model.getSnapshot().readiness.status, "likely_offline_ready");
});

test("preparation progress never renews readiness expiry", () => {
  const h = harness();
  h.model.applyReadiness(readiness(h));
  const expiresAt = h.model.getSnapshot().readiness.expiresAt;
  h.tick(59000);
  h.model.syncNow();
  for (const state of ["queued", "active", "completed"]) {
    h.model.applyPreparation(prep(h, { state }));
    assert.equal(h.model.getSnapshot().readiness.expiresAt, expiresAt);
  }
  h.tick(1000);
  assert.equal(h.model.getSnapshot().readiness.expired, true, "a finished download is not fresh evidence");
});

test("fresh readiness is the only thing that renews expiry", () => {
  const h = harness();
  h.model.applyReadiness(readiness(h));
  h.tick(60000);
  assert.equal(h.model.getSnapshot().readiness.expired, true);
  h.model.applyReadiness(readiness(h));
  assert.equal(h.model.getSnapshot().readiness.expired, false);
});

test("a schedule is reported as injected and never enabled on its own", () => {
  const h = harness({ available: true, game: GAME, schedule: { enabled: false, intervalMinutes: null } });
  assert.deepEqual(h.model.getSnapshot().schedule, { enabled: false, intervalMinutes: null });
  assert.deepEqual(h.calls.schedule, []);
  assert.equal(h.model.setSyncSchedule({ enabled: true, intervalMinutes: 120 }), true);
  assert.deepEqual(h.model.getSnapshot().schedule, { enabled: true, intervalMinutes: 120 });
  assert.deepEqual(h.calls.schedule, [{ enabled: true, intervalMinutes: 120 }]);
});

test("an invalid schedule is refused and never persisted", () => {
  const h = harness();
  for (const bad of [null, {}, { enabled: true }, { enabled: true, intervalMinutes: 0 },
    { enabled: true, intervalMinutes: -5 }, { enabled: true, intervalMinutes: "60" }]) {
    assert.equal(h.model.setSyncSchedule(bad), false);
  }
  assert.deepEqual(h.calls.schedule, []);
  assert.equal(h.model.getSnapshot().schedule.enabled, false);
});

test("disabling a schedule clears its interval", () => {
  const h = harness();
  h.model.setSyncSchedule({ enabled: true, intervalMinutes: 30 });
  h.model.setSyncSchedule({ enabled: false, intervalMinutes: 30 });
  assert.deepEqual(h.model.getSnapshot().schedule, { enabled: false, intervalMinutes: null });
});

test("snapshots are frozen, value-stable and defensively copied", () => {
  const h = harness();
  h.model.applyReadiness(readiness(h));
  const a = h.model.getSnapshot();
  assert.equal(h.model.getSnapshot(), a, "an unchanged model returns the same object");
  assert.equal(Object.isFrozen(a), true);
  assert.equal(Object.isFrozen(a.preparation), true);
  assert.equal(Object.isFrozen(a.readiness), true);
  assert.throws(() => { a.preparation.state = "completed"; }, TypeError);
  h.model.applyPreparation(prep(h, { state: "active" }));
  assert.notEqual(h.model.getSnapshot(), a);
  assert.equal(a.preparation.state, "idle", "an old snapshot is never mutated in place");
});

test("an unexpected content shape stays unknown rather than a confident no-update", () => {
  const h = harness();
  for (const bad of [undefined, null, "x", [{}], [{ type: "nope" }], [{ type: "shader", hasUpdate: "yes" }]]) {
    h.model.applyPreparation(prep(h, { state: "queued", content: bad }));
    const content = h.model.getSnapshot().preparation.content;
    assert.equal(content.length, 3);
    assert.equal(content.every((c) => c.hasUpdate === false), false);
  }
});

test("dispose stops notifications, refuses actions and drops later observations", () => {
  const h = harness();
  h.model.syncNow();
  const before = h.seen.length;
  h.model.dispose();
  h.model.dispose();
  assert.equal(h.model.syncNow(), false);
  assert.equal(h.model.setSyncSchedule({ enabled: true, intervalMinutes: 10 }), false);
  assert.equal(h.model.applyPreparation(prep(h, { state: "completed" })), false);
  assert.equal(h.model.applyReadiness(readiness(h)), false);
  assert.equal(h.seen.length, before);
  assert.equal(h.calls.sync.length, 1);
  assert.equal(h.model.getSnapshot().capabilities.canSyncNow, false);
});

test("unsubscribing stops that listener only", () => {
  const h = harness();
  const mine = [];
  const off = h.model.subscribe((s) => mine.push(s));
  h.model.applyPreparation(prep(h, { state: "queued" }));
  assert.equal(mine.length, 1);
  off();
  const others = h.seen.length;
  h.model.applyPreparation(prep(h, { state: "active" }));
  assert.equal(mine.length, 1);
  assert.equal(h.seen.length, others + 1);
});

test("one throwing subscriber does not stop the others", () => {
  const h = harness();
  const ok = [];
  h.model.subscribe(() => { throw new Error("bad listener"); });
  h.model.subscribe((s) => ok.push(s));
  assert.doesNotThrow(() => h.model.applyPreparation(prep(h, { state: "queued" })));
  assert.equal(ok.length, 1);
});

test("losing availability clears in-flight state and disables actions", () => {
  const h = harness();
  h.model.syncNow();
  h.model.setAvailability({ available: false, unavailableReason: "Steam went away" });
  const s = h.model.getSnapshot();
  assert.equal(s.available, false);
  assert.equal(s.unavailableReason, "Steam went away");
  assert.equal(s.preparation.inFlight, false);
  assert.equal(s.capabilities.canSyncNow, false);
  assert.equal(h.model.syncNow(), false);
});

test("exact app id guard matches the repo's identity rule", () => {
  for (const good of [1, 620, 2 ** 32 - 1]) assert.equal(isExactAppId(good), true);
  for (const bad of [0, -1, 1.5, 2 ** 32, NaN, "620", null, undefined]) assert.equal(isExactAppId(bad), false);
});

// --- Review findings from hub message 248fab0c ---

test("refresh notifies a subscriber when readiness crosses its expiry", () => {
  const h = harness();
  h.model.applyReadiness(readiness(h));
  const before = h.seen.length;
  h.tick(30000);
  assert.equal(h.model.refresh(), false, "nothing changed yet, so no notification");
  assert.equal(h.seen.length, before);
  h.tick(30000);
  assert.equal(h.model.refresh(), true, "crossing expiry must reach subscribers");
  assert.equal(h.seen.length, before + 1);
  assert.equal(h.seen.at(-1).readiness.expired, true);
  // Idempotent: a second refresh with nothing new does not notify again.
  assert.equal(h.model.refresh(), false);
  assert.equal(h.seen.length, before + 1);
});

test("refresh after dispose does nothing", () => {
  const h = harness();
  h.model.applyReadiness(readiness(h));
  h.model.dispose();
  h.tick(120000);
  assert.equal(h.model.refresh(), false);
});

test("an account change invalidates evidence even for the same app", () => {
  const h = harness({ available: true, game: { ...GAME, account: "player-one" } });
  h.model.applyReadiness(readiness(h));
  const before = h.model.getSnapshot();
  assert.equal(before.readiness.status, "likely_offline_ready");
  h.model.selectGame({ ...GAME, account: "player-two" });
  const after = h.model.getSnapshot();
  assert.equal(after.generation > before.generation, true);
  assert.equal(after.readiness.status, null, "another account is another subject");
  assert.equal(after.preparation.state, "idle");
});

test("a build change invalidates evidence even for the same app and account", () => {
  const h = harness({ available: true, game: { ...GAME, account: "p", buildId: 100 } });
  h.model.applyReadiness(readiness(h));
  const before = h.model.getSnapshot();
  h.model.selectGame({ ...GAME, account: "p", buildId: 101 });
  const after = h.model.getSnapshot();
  assert.equal(after.generation > before.generation, true);
  assert.equal(after.readiness.status, null, "a rebuilt game is not the one we checked");
});

test("identical app, account and build is still a no-op", () => {
  const h = harness({ available: true, game: { ...GAME, account: "p", buildId: 100 } });
  h.model.applyReadiness(readiness(h));
  const before = h.model.getSnapshot();
  h.model.selectGame({ ...GAME, account: "p", buildId: 100 });
  assert.equal(h.model.getSnapshot(), before);
});

test("a late reply from an earlier attempt cannot land on the current one", () => {
  const h = harness();
  h.model.syncNow();
  const first = h.model.getSnapshot().attempt;
  h.model.applyPreparation(prep(h, { attempt: first, state: "error", errorCode: 21 }));
  assert.equal(h.model.getSnapshot().preparation.inFlight, false);
  h.model.syncNow();
  const second = h.model.getSnapshot().attempt;
  assert.equal(second > first, true);
  // The first attempt finally answers. It is not this request's outcome.
  assert.equal(h.model.applyPreparation(prep(h, { attempt: first, state: "completed" })), false);
  assert.equal(h.model.getSnapshot().preparation.state, "requested");
  assert.equal(h.model.applyPreparation(prep(h, { attempt: second, state: "completed" })), true);
  assert.equal(h.model.getSnapshot().preparation.state, "completed");
});

test("attempt resets with a new selection so counters cannot leak across games", () => {
  const h = harness();
  h.model.syncNow();
  assert.equal(h.model.getSnapshot().attempt, 1);
  h.model.selectGame(OTHER);
  assert.equal(h.model.getSnapshot().attempt, 0);
});

test("a callback delivered synchronously during startSync is kept, not overwritten", () => {
  const calls = [];
  let model;
  const ports = {
    startSync: (appId, generation, attempt) => {
      calls.push([appId, generation, attempt]);
      // Steam answers before the dispatch call returns.
      model.applyPreparation({ generation, appId, attempt, state: "active" });
    },
    persistSchedule() {},
    now: () => 0,
  };
  model = createOfflineGameModeModel(ports, { initial: { available: true, game: GAME } });
  assert.equal(model.syncNow(), true);
  assert.equal(calls.length, 1);
  assert.equal(model.getSnapshot().preparation.state, "active",
    "the synchronous observation must survive the optimistic requested state");
  assert.equal(model.getSnapshot().preparation.inFlight, true);
});

test("a synchronous observation survives a port that then throws", () => {
  let model;
  const ports = {
    startSync: (appId, generation, attempt) => {
      model.applyPreparation({ generation, appId, attempt, state: "queued" });
      throw new Error("native gone after accepting");
    },
    persistSchedule() {},
    now: () => 0,
  };
  model = createOfflineGameModeModel(ports, { initial: { available: true, game: GAME } });
  assert.equal(model.syncNow(), false);
  assert.equal(model.getSnapshot().preparation.state, "queued",
    "real evidence must not be clobbered by the throw handler");
  assert.equal(model.getSnapshot().preparation.inFlight, false);
});

test("a preparation observation without a matching attempt is refused", () => {
  const h = harness();
  h.model.syncNow();
  for (const bad of [undefined, null, "1", 0, 99, 1.5]) {
    assert.equal(h.model.applyPreparation(prep(h, { attempt: bad, state: "completed" })), false);
  }
  assert.equal(h.model.getSnapshot().preparation.state, "requested");
});
