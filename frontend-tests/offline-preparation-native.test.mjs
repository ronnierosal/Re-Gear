import assert from "node:assert/strict";
import test from "node:test";
import {
  PreparationUnavailableError,
  isExactAppId,
  projectDownloadItem,
  startOfflinePreparation,
} from "../src/offline-preparation-native.ts";

const INDEX = { content: 0, shader: 1, workshop: 2 };
const APP = 620;
const CLIENT = "local-client-0";

const typeInfo = (over = {}) => [
  { has_update: true, completed: false },
  { has_update: true, completed: false },
  { has_update: false, completed: false },
].map((entry, at) => ({ ...entry, ...(over[at] ?? {}) }));

const item = (over = {}) => ({
  appid: APP, active: false, completed: false, completed_time: 0, paused: false,
  queue_index: -1, buildid: 100, target_buildid: 101, update_result: 0,
  update_type_info: typeInfo(), ...over,
});

/** A fake native port. Nothing here touches Steam. */
function fakePorts(over = {}) {
  const calls = { queue: [], resume: [], unregister: 0 };
  let emit = null;
  const ports = {
    localClientId: () => CLIENT,
    queueAppUpdate: (appId, clientId) => calls.queue.push([appId, clientId]),
    resumeAppUpdate: (appId, clientId) => calls.resume.push([appId, clientId]),
    registerForDownloadItems: (cb) => {
      emit = cb;
      return { unregister: () => { calls.unregister++; } };
    },
    contentTypeIndex: INDEX,
    ...over,
  };
  return { ports, calls, send: (items, downloading = true) => emit(downloading, items) };
}

function collect(t, over = {}, kind = "queue", options = {}) {
  const reports = [];
  const f = fakePorts(over);
  const handle = startOfflinePreparation(APP, kind, f.ports, (r) => reports.push(r), options);
  return { ...f, handle, reports, states: () => reports.map((r) => r.state) };
}

test("dispatches with the resolved local client id and reports the observed lifecycle", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const c = collect(t);
  assert.deepEqual(c.calls.queue, [[APP, CLIENT]]);
  assert.deepEqual(c.states(), ["requested"]);
  c.send([item({ queue_index: 0 })]);
  c.send([item({ queue_index: 0, active: true })]);
  c.send([item({ completed: true, completed_time: 555 })]);
  assert.deepEqual(c.states(), ["requested", "queued", "active", "completed"]);
  // A terminal state unregisters; later traffic cannot revive it.
  assert.equal(c.calls.unregister, 1);
  c.send([item({ completed: true, completed_time: 999 })]);
  assert.deepEqual(c.states(), ["requested", "queued", "active", "completed"]);
});

test("resume uses ResumeAppUpdate and never the queue method", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const c = collect(t, {}, "resume");
  assert.deepEqual(c.calls.resume, [[APP, CLIENT]]);
  assert.deepEqual(c.calls.queue, []);
  c.handle.stop();
});

test("a missing native method throws a named error instead of doing nothing quietly", () => {
  for (const [over, expected] of [
    [{ queueAppUpdate: undefined }, "SteamClient.Downloads.QueueAppUpdate is unavailable"],
    [{ registerForDownloadItems: undefined }, "SteamClient.Downloads.RegisterForDownloadItems is unavailable"],
  ]) {
    assert.throws(
      () => startOfflinePreparation(APP, "queue", fakePorts(over).ports, () => {}),
      (error) => error instanceof PreparationUnavailableError && error.message === expected,
    );
  }
  assert.throws(
    () => startOfflinePreparation(APP, "resume", fakePorts({ resumeAppUpdate: undefined }).ports, () => {}),
    (error) => error.message === "SteamClient.Downloads.ResumeAppUpdate is unavailable",
  );
});

test("a subscription without a usable unregister is treated as unavailable", () => {
  for (const bad of [() => null, () => ({}), () => { throw new Error("no"); }]) {
    assert.throws(
      () => startOfflinePreparation(APP, "queue", fakePorts({ registerForDownloadItems: bad }).ports, () => {}),
      (error) => error instanceof PreparationUnavailableError,
    );
  }
});

test("an unidentifiable local client fails closed and never dispatches", () => {
  for (const bad of [null, "", 0, undefined]) {
    const f = fakePorts({ localClientId: () => bad });
    assert.throws(
      () => startOfflinePreparation(APP, "queue", f.ports, () => {}),
      (error) => error.message === "The local Steam client could not be identified",
    );
    assert.deepEqual(f.calls.queue, []);
  }
});

test("a dispatch that throws is reported and the subscription is released", () => {
  const f = fakePorts({ queueAppUpdate: () => { throw new Error("native refused"); } });
  assert.throws(
    () => startOfflinePreparation(APP, "queue", f.ports, () => {}),
    (error) => error.message === "SteamClient.Downloads.QueueAppUpdate did not accept the request",
  );
  assert.equal(f.calls.unregister, 1);
});

test("a non-exact app id is refused before any native call", () => {
  for (const bad of [0, -1, 1.5, 2 ** 32, "620", null]) {
    const f = fakePorts();
    assert.throws(() => startOfflinePreparation(bad, "queue", f.ports, () => {}), PreparationUnavailableError);
    assert.deepEqual(f.calls.queue, []);
  }
});

test("another game's download never moves our state", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const c = collect(t);
  c.send([item({ appid: 999, active: true, queue_index: 0 })]);
  c.send([{ appid: APP }, item({ appid: 12345, completed: true })]);
  assert.deepEqual(c.states(), ["requested"]);
  c.send([item({ active: true })]);
  assert.deepEqual(c.states(), ["requested", "active"]);
});

test("an item already complete before we asked is not this request's completion", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const done = item({ completed: true, completed_time: 42 });
  const c = collect(t);
  // Baseline arrives first, already complete, then repeats unchanged.
  c.send([done]);
  c.send([done]);
  assert.deepEqual(c.states(), ["requested"]);
  // Only a moved fingerprint counts as our completion.
  c.send([item({ completed: true, completed_time: 77 })]);
  assert.deepEqual(c.states(), ["requested", "completed"]);
});

test("a synchronous callback during registration becomes the baseline, not a result", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const reports = [];
  const calls = [];
  let emit = null;
  const ports = {
    localClientId: () => CLIENT,
    queueAppUpdate: (...a) => calls.push(a),
    registerForDownloadItems: (cb) => {
      // Fires before the caller holds the lease and before dispatch.
      cb(true, [item({ completed: true, completed_time: 5 })]);
      emit = cb;
      return { unregister() {} };
    },
    contentTypeIndex: INDEX,
  };
  startOfflinePreparation(APP, "queue", ports, (r) => reports.push(r));
  assert.equal(calls.length, 1);
  assert.deepEqual(reports.map((r) => r.state), ["requested"]);
  emit(true, [item({ completed: true, completed_time: 5 })]);
  assert.deepEqual(reports.map((r) => r.state), ["requested"]);
});

test("a void dispatch with no observed change expires to unconfirmed, never to completed", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const c = collect(t, {}, "queue", { unconfirmedAfterMs: 30000 });
  t.mock.timers.tick(29999);
  assert.deepEqual(c.states(), ["requested"]);
  t.mock.timers.tick(1);
  assert.deepEqual(c.states(), ["requested", "unconfirmed"]);
  assert.equal(c.calls.unregister, 1);
  // The expiry is terminal: late traffic cannot resurrect the request.
  c.send([item({ active: true })]);
  assert.deepEqual(c.states(), ["requested", "unconfirmed"]);
});

test("observed progress cancels the unconfirmed expiry", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const c = collect(t, {}, "queue", { unconfirmedAfterMs: 30000 });
  c.send([item({ active: true })]);
  t.mock.timers.tick(60000);
  assert.deepEqual(c.states(), ["requested", "active"]);
});

test("an update error is reported by code and Steam's raw string is never carried", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const c = collect(t);
  c.send([item({ update_result: 21, update_error: "k_EAppUpdateErrorNoDownloadSources" })]);
  const last = c.reports.at(-1);
  assert.equal(last.state, "error");
  assert.equal(last.errorCode, 21);
  assert.equal(JSON.stringify(last).includes("k_EAppUpdate"), false);
  assert.equal(c.calls.unregister, 1);
});

test("stop unregisters once, is idempotent, and silences later callbacks", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const c = collect(t);
  c.handle.stop();
  c.handle.stop();
  assert.equal(c.calls.unregister, 1);
  c.send([item({ active: true })]);
  assert.deepEqual(c.states(), ["requested"]);
  t.mock.timers.tick(60000);
  assert.deepEqual(c.states(), ["requested"]);
});

test("an unregister that throws does not escape stop", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = fakePorts({
    registerForDownloadItems: () => ({ unregister() { throw new Error("gone"); } }),
  });
  const handle = startOfflinePreparation(APP, "queue", f.ports, () => {});
  assert.doesNotThrow(() => handle.stop());
});

test("per content type reports shader separately and accepts either completion field", () => {
  const both = projectDownloadItem(
    item({ update_type_info: typeInfo({ 1: { has_update: true, completed: true } }) }), APP, INDEX,
  );
  assert.deepEqual(both.content.find((c) => c.type === "shader"), {
    type: "shader", hasUpdate: true, completed: true,
  });
  // The shipped client uses `completed`; the published type names
  // `completed_update`. Either is accepted.
  const declared = projectDownloadItem(
    item({ update_type_info: [{ has_update: true, completed_update: true }, {}, {}] }), APP, INDEX,
  );
  assert.equal(declared.content[0].completed, true);
});

test("an unexpected update_type_info shape is unknown, never a confident no-update", () => {
  for (const bad of [undefined, null, "x", [], [{}, {}, {}], [{ has_update: "yes" }]]) {
    const p = projectDownloadItem(item({ update_type_info: bad }), APP, INDEX);
    for (const entry of p.content) {
      assert.equal(entry.hasUpdate === null || typeof entry.hasUpdate === "boolean", true);
      assert.equal(entry.completed === null || typeof entry.completed === "boolean", true);
    }
    assert.equal(p.content.every((e) => e.hasUpdate === false), false);
  }
});

test("a missing content-type index yields unknown rather than a guessed slot", () => {
  const p = projectDownloadItem(item(), APP, { content: 0 });
  assert.equal(p.content.find((c) => c.type === "content").hasUpdate, true);
  assert.equal(p.content.find((c) => c.type === "shader").hasUpdate, null);
  assert.equal(p.content.find((c) => c.type === "workshop").hasUpdate, null);
});

test("projection rejects a foreign or malformed item", () => {
  for (const bad of [null, "x", [], { appid: 999 }, { appid: "620" }, {}]) {
    assert.equal(projectDownloadItem(bad, APP, INDEX), null);
  }
  const ok = projectDownloadItem(item(), APP, INDEX);
  assert.equal(ok.buildId, 100);
  assert.equal(ok.targetBuildId, 101);
});

test("exact app id guard matches the repo's existing identity rule", () => {
  for (const good of [1, 620, 2 ** 32 - 1]) assert.equal(isExactAppId(good), true);
  for (const bad of [0, -1, 1.5, 2 ** 32, NaN, "620", null, undefined]) {
    assert.equal(isExactAppId(bad), false);
  }
});
