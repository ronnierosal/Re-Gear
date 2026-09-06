import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const js = ts.transpileModule(readFileSync(new URL("../src/controller-safe-disconnect.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { startControllerSafeDisconnect, VIEW_BUTTON: G, Y_BUTTON: Y } = await import(
  "data:text/javascript;base64," + Buffer.from(js).toString("base64"));
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function context(mode = "docked_egpu") {
  return { snapshot: { delivery_schema_version: 2, inference: { mode }, snapshot: {
    schema_version: 3, observed_at: new Date().toISOString(),
    game_state: "idle", support_tier: "certified", gamescope: { running: true },
    disconnect_readiness: { applicable: true },
    gpus: [{ role: "external", present: true, confidence: "verified" }],
  } }, journal: { code: "journal.idle" } };
}
function setup(t, read, changesMethod = "RegisterForControllerListChanges") {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let input, state, removed = 0, reads = 0, busy = false;
  const current = context(); const confirmations = [];
  const handle = startControllerSafeDisconnect({
    input: {
      RegisterForControllerInputMessages(callback) { input = callback; return { unregister() { removed++; } }; },
      [changesMethod](callback) { state = callback; return { unregister() { removed++; } }; },
    },
    readContext: () => { reads++; return read ? read() : Promise.resolve(structuredClone(current)); },
    isBusy: () => busy,
    confirm: portable => confirmations.push(portable),
  });
  t.after(handle.stop);
  return { handle, current, confirmations, input: (...args) => input(...args), state: () => state(),
    chord(id = 0) { input(id, G, true); input(id, Y, true); },
    release(id = 0) { input(id, G, false); input(id, Y, false); },
    counts: () => ({ reads, removed }), busy: value => { busy = value; } };
}
test("same-controller chord opens confirmation at three seconds only once per hold", async t => {
  const s = setup(t); s.chord(); await flush();
  t.mock.timers.tick(2999); await flush(); assert.deepEqual(s.confirmations, []);
  s.input(0, Y, true); t.mock.timers.tick(1); await flush();
  assert.deepEqual(s.confirmations, ["ally"]);
  s.input(0, G, true); t.mock.timers.tick(10000); await flush();
  assert.deepEqual(s.confirmations, ["ally"]);
  s.release(); s.current.snapshot.inference.mode = "portable"; s.chord(); await flush();
  t.mock.timers.tick(3000); await flush(); assert.deepEqual(s.confirmations, ["ally", "tv"]);
});
test("release before threshold cancels and a new hold needs all three seconds", async t => {
  const s = setup(t); s.chord(); await flush(); t.mock.timers.tick(2999); s.release();
  t.mock.timers.tick(1); await flush(); assert.equal(s.confirmations.length, 0);
  s.chord(); await flush(); t.mock.timers.tick(2999); await flush(); assert.equal(s.confirmations.length, 0);
  t.mock.timers.tick(1); await flush(); assert.equal(s.confirmations.length, 1);
});
test("buttons from different controllers never combine", async t => {
  const s = setup(t); s.input(0, G, true); s.input(1, Y, true);
  t.mock.timers.tick(4000); await flush(); assert.equal(s.counts().reads, 0);
});
test("extra buttons, malformed input and controller changes cancel holds", async t => {
  const s = setup(t);
  for (const invalidate of [() => s.input(0, 0, true), () => s.input(-1, Y, true), s.state]) {
    s.state(); s.chord(); await flush(); t.mock.timers.tick(1000); invalidate();
    t.mock.timers.tick(3000); await flush(); assert.equal(s.confirmations.length, 0);
  }
});
test("running or unknown game and pending journal block confirmation", async t => {
  const s = setup(t);
  for (const kind of ["running", "unknown", "journal", "no_egpu"]) {
    s.state(); s.current.snapshot.snapshot.game_state = kind === "running" || kind === "unknown" ? kind : "idle";
    s.current.journal.code = kind === "journal" ? "journal.result_required" : "journal.idle";
    s.current.snapshot.snapshot.disconnect_readiness.applicable = kind !== "no_egpu";
    s.chord(); await flush(); t.mock.timers.tick(3000); await flush();
    assert.equal(s.confirmations.length, 0);
  }
});
test("fresh end-of-hold check catches game start", async t => {
  const s = setup(t); s.chord(); await flush();
  s.current.snapshot.snapshot.game_state = "running";
  t.mock.timers.tick(3000); await flush(); assert.equal(s.confirmations.length, 0);
  assert.equal(s.counts().reads, 2);
});
test("release during final context request cancels stale delivery", async t => {
  let finish; let count = 0;
  const s = setup(t, () => ++count === 1 ? Promise.resolve(context()) : new Promise(resolve => { finish = resolve; }));
  s.chord(); await flush(); t.mock.timers.tick(3000); await flush();
  s.release(); finish(context()); await flush(); assert.equal(s.confirmations.length, 0);
});
test("context timeout stays closed and allows only one outstanding read", async t => {
  let finish;
  const s = setup(t, () => new Promise(resolve => { finish = resolve; }));
  s.chord(); await flush(); t.mock.timers.tick(3000); await flush();
  s.release(); s.chord(); await flush(); t.mock.timers.tick(3000); await flush();
  assert.equal(s.counts().reads, 1); finish(context()); await flush();
  assert.equal(s.confirmations.length, 0);
});
test("busy modal/action and unload prevent duplicate or late confirmation", async t => {
  const s = setup(t); s.busy(true); s.chord(); await flush();
  t.mock.timers.tick(3000); await flush(); assert.equal(s.confirmations.length, 0);
  s.release(); s.busy(false); s.chord(); await flush(); s.handle.stop();
  t.mock.timers.tick(3000); await flush(); s.chord(); assert.equal(s.confirmations.length, 0);
  assert.equal(s.counts().removed, 2);
});
test("unavailable or partial native subscription stays inert and cleans up", () => {
  const deps = { readContext: async () => context(), isBusy: () => false, confirm() { assert.fail("unexpected confirmation"); } };
  assert.equal(startControllerSafeDisconnect(deps).available, false);
  let removed = 0;
  const handle = startControllerSafeDisconnect({ ...deps, input: {
    RegisterForControllerListChanges() { return { unregister() { removed++; } }; },
    RegisterForControllerInputMessages() { throw new Error("unavailable"); },
  } });
  assert.equal(handle.available, false); assert.equal(removed, 1);
});


test("stale, future, malformed and unsupported snapshot evidence stays closed", async t => {
  const s = setup(t);
  for (const stamp of [new Date(Date.now() - 16000).toISOString(), new Date(Date.now() + 6000).toISOString(), "invalid", undefined]) {
    s.state(); s.current.snapshot.snapshot.observed_at = stamp;
    s.chord(); await flush(); t.mock.timers.tick(3000); await flush();
    assert.equal(s.confirmations.length, 0);
  }
  s.state(); s.current.snapshot.snapshot.observed_at = new Date().toISOString();
  s.current.snapshot.delivery_schema_version = 999;
  s.chord(); await flush(); t.mock.timers.tick(3000); await flush();
  assert.equal(s.confirmations.length, 0);
});

test("successful chord must release both buttons before rearming", async t => {
  const s = setup(t); s.chord(); await flush(); t.mock.timers.tick(3000); await flush();
  s.input(0, Y, false); s.input(0, Y, true); await flush();
  t.mock.timers.tick(3000); await flush(); assert.equal(s.confirmations.length, 1);
  s.release(); s.chord(); await flush(); t.mock.timers.tick(3000); await flush();
  assert.equal(s.confirmations.length, 2);
});

test("controller removal while final read is pending cancels confirmation", async t => {
  let finish; let count = 0;
  const s = setup(t, () => ++count === 1 ? Promise.resolve(context()) : new Promise(resolve => { finish = resolve; }));
  s.chord(); await flush(); t.mock.timers.tick(3000); await flush();
  s.state(); finish(context()); await flush(); assert.equal(s.confirmations.length, 0);
});


test("Ally active-controller API works without controller-list API and cancels a pending hold", async t => {
  const s = setup(t, undefined, "RegisterForActiveControllerChanges");
  assert.equal(s.handle.available, true);
  s.chord(); await flush(); t.mock.timers.tick(1000); s.state();
  t.mock.timers.tick(2000); await flush(); assert.equal(s.confirmations.length, 0);
  s.chord(); await flush(); t.mock.timers.tick(3000); await flush();
  assert.equal(s.confirmations.length, 1);
  s.handle.stop(); assert.equal(s.counts().removed, 2);
});

test("button API alone is insufficient without a controller-change subscription", () => {
  let registered = false;
  const result = startControllerSafeDisconnect({
    input: { RegisterForControllerInputMessages() { registered = true; return { unregister() {} }; } },
    readContext: async () => context(), isBusy: () => false,
    confirm() { assert.fail("unexpected confirmation"); },
  });
  assert.equal(result.available, false); assert.equal(registered, false);
});


test("only View plus Y works; Xbox/Guide and Menu plus Y remain inactive", async t => {
  const s = setup(t);
  for (const wrongButton of [34, 8]) {
    s.state(); s.input(0, wrongButton, true); s.input(0, Y, true); await flush();
    t.mock.timers.tick(3000); await flush();
    assert.equal(s.confirmations.length, 0); assert.equal(s.counts().reads, 0);
  }
  s.state(); s.input(0, 9, true); s.input(0, 3, true); await flush();
  t.mock.timers.tick(2999); await flush(); assert.equal(s.confirmations.length, 0);
  t.mock.timers.tick(1); await flush(); assert.equal(s.confirmations.length, 1);
});


test("a mode change during the hold cancels rather than reversing the requested direction", async t => {
  const s = setup(t); s.chord(); await flush();
  s.current.snapshot.inference.mode = "portable";
  t.mock.timers.tick(3000); await flush(); assert.equal(s.confirmations.length, 0);
});

test("controller confirmation has only TV and Ally routes, never shutdown", () => {
  const source = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8");
  const route = source.split('const shortcut = createDisplayShortcutRuntime({')[1].split('  let warningModal')[0];
  assert.match(route, /executeSupervisedTvSwitch\(token\)/);
  assert.match(route, /executeSupervisedPortableSwitch\(token\)/);
  assert.doesNotMatch(route, /executeSafeDisconnectShutdown|approveSafeDisconnectShutdown/);
});
