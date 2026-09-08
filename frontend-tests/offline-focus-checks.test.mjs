import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const js = ts.transpileModule(readFileSync(new URL("../src/offline-focus-checks.tsx", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText.replace(/^import .*;\r?\n/gm, "").replace("export function startOfflineFocusChecks", "function startOfflineFocusChecks");

function setup(t, classify = async () => ({}), options = {}) {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const listeners = new Map();
  const app = { display_status: 0 };
  const store = { GetAppOverviewByAppID: () => app };
  const router = { RunningApps: [], ...options.router };
  let account = "account";
  const document = { addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) };
  const observers = [];
  const view = { document, MutationObserver: class { constructor(callback) { this.callback = callback; observers.push(this); } observe() {} disconnect() {} } };
  const tile = { id: 123, ownerDocument: { ...document, defaultView: view }, isConnected: true, closest: () => tile };
  tile.ownerDocument = document; document.defaultView = view; document.activeElement = tile;
  let requests = 0; let shown = 0; const badges = [];
  const start = new Function("window", "Router", "routerHook", "callable", "OfflineDetailsSession", "offlineNativeSource", "attachOfflineTileBadge", "exactTileElementAppId", "OFFLINE_TILE_SELECTOR", "offlineReportBadge", "offlineBadgeImages", "offlineConfidenceForGame", "offlineConfidenceBadge", "offlineAccountScope", "offlineTestMemory", js + "\nreturn startOfflineFocusChecks;")(
    { appStore: store, DFL: { getGamepadNavigationTrees: () => [{ m_window: view }] } }, router,
    { addPatch: () => ({}), removePatch() {} }, () => classify,
    class { invalidate() {} async request() { requests++; return options.request ? options.request() : { details: {}, isValid: () => true }; } },
    () => ({ store, subscribe() {} }), (_view, _id, _image, _label, valid, _tile, _expired, expiry) => {
      shown++; const badge = { stopped: false, expired: false, stop() { this.stopped = true; }, validate() { if (!valid()) this.stop(); } };
      setTimeout(() => { badge.expired = true; }, expiry); badges.push(badge); return badge;
    }, tile => tile.id,
    "tile", options.reportBadge ?? (() => ({ asset: "offline-verify", label: "Check" })), { "offline-verify": "badge.svg" }, () => ({}), () => ({asset: "offline-verify", label:"Check"}), () => account, {clear() {}},
  );
  const handle = start(); t.after(() => handle.stop());
  return { document, tile, app, router, store, listeners, observers, badges, handle, setAccount: value => { account = value; }, counts: () => ({ requests, shown }) };
}
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

test("already focused game checks once after settling", async t => {
  const s = setup(t); t.mock.timers.tick(449); assert.equal(s.counts().requests, 0);
  t.mock.timers.tick(1); await flush(); assert.deepEqual(s.counts(), { requests: 1, shown: 1 });
});
test("loss of focus or game start before settling suppresses requests", async t => {
  const s = setup(t); s.document.activeElement = null;
  t.mock.timers.tick(450); await flush(); assert.equal(s.counts().requests, 0);
  s.document.activeElement = s.tile; s.listeners.get("focusin")({ target: s.tile, type: "focusin" }); s.app.display_status = 4;
  t.mock.timers.tick(450); await flush(); assert.equal(s.counts().requests, 0);
});
test("classification failure is contained and subsequent focus can retry", async t => {
  let calls = 0;
  const s = setup(t, async () => { if (++calls === 1) throw Error("Decky unavailable"); return {}; });
  t.mock.timers.tick(450); await flush(); assert.equal(s.counts().shown, 0);
  s.listeners.get("focusin")({ target: s.tile, type: "focusin" }); t.mock.timers.tick(450); await flush();
  assert.deepEqual(s.counts(), { requests: 2, shown: 1 });
});
test("late classification cannot show after focus changes", async t => {
  let resolve;
  const s = setup(t, () => new Promise(done => { resolve = done; }));
  t.mock.timers.tick(450); await flush(); s.document.activeElement = null;
  resolve({}); await flush(); assert.equal(s.counts().shown, 0);
});


test("tab replacement without focusin checks the new active tile", async t => {
  const s = setup(t); t.mock.timers.tick(450); await flush();
  const next = { ...s.tile, id: 456 }; next.closest = () => next;
  s.document.activeElement = next;
  s.observers[0].callback(); t.mock.timers.tick(450); await flush();
  assert.deepEqual(s.counts(), { requests: 2, shown: 2 });
});
test("unrelated mutations do not restart the settle timer or repeat checks", async t => {
  const s = setup(t); t.mock.timers.tick(400); s.observers[0].callback();
  t.mock.timers.tick(50); await flush();
  for (let i = 0; i < 20; i++) s.observers[0].callback();
  t.mock.timers.tick(450); await flush();
  assert.deepEqual(s.counts(), { requests: 1, shown: 1 });
});

test("selected game refreshes at sixty seconds and suppresses refresh during gameplay", async t => {
 const s=setup(t); t.mock.timers.tick(450); await flush();
 t.mock.timers.tick(30000); await flush(); assert.equal(s.counts().requests,1);
 t.mock.timers.tick(29999); await flush(); assert.equal(s.counts().requests,1);
 t.mock.timers.tick(1); await flush(); assert.deepEqual(s.counts(),{requests:2,shown:2});
 s.router.RunningApps=[123]; t.mock.timers.tick(60000); await flush();
 assert.equal(s.counts().requests,2);
});

test("same selected tile refreshes after display status changes without another focus event", async t => {
  const s = setup(t); t.mock.timers.tick(450); await flush();
  s.app.display_status = 6; t.mock.timers.tick(60000); await flush();
  assert.deepEqual(s.counts(), { requests: 2, shown: 2 });
  assert.equal(s.badges[0].stopped, true);
});

test("same tile resumes after gameplay with no focus or DOM event", async t => {
  const s = setup(t); t.mock.timers.tick(450); await flush();
  s.router.RunningApps = [123]; s.app.display_status = 4;
  t.mock.timers.tick(60000); await flush(); assert.equal(s.counts().requests, 1);
  t.mock.timers.tick(60000); await flush(); assert.equal(s.counts().requests, 1);
  s.router.RunningApps = []; s.app.display_status = 0;
  t.mock.timers.tick(60000); await flush(); assert.equal(s.counts().requests, 2);
});

test("unknown RunningApps never requests and recovers on existing cadence", async t => {
  const s = setup(t, undefined, { router: { RunningApps: undefined } });
  t.mock.timers.tick(450); await flush(); t.mock.timers.tick(60000); await flush();
  assert.equal(s.counts().requests, 0);
  s.router.RunningApps = []; t.mock.timers.tick(60000); await flush();
  assert.deepEqual(s.counts(), { requests: 1, shown: 1 });
});

test("same tile mutation observes eligibility changes without unrelated mutation retries", async t => {
  const s = setup(t); t.mock.timers.tick(450); await flush();
  s.router.RunningApps = [123]; s.observers[0].callback();
  t.mock.timers.tick(450); await flush(); assert.equal(s.counts().requests, 1);
  s.router.RunningApps = []; s.observers[0].callback();
  t.mock.timers.tick(450); await flush(); assert.equal(s.counts().requests, 2);
});

test("transient failures retry twice at five seconds then sixty, success resets budget", async t => {
  let calls = 0;
  const s = setup(t, async () => { if (++calls !== 4) throw Error("temporary"); return {}; });
  t.mock.timers.tick(450); await flush();
  for (const expected of [2, 3]) {
    t.mock.timers.tick(4999); await flush(); assert.equal(s.counts().requests, expected - 1);
    t.mock.timers.tick(1); await flush(); assert.equal(s.counts().requests, expected);
  }
  t.mock.timers.tick(59999); await flush(); assert.equal(s.counts().requests, 3);
  t.mock.timers.tick(1); await flush(); assert.equal(s.counts().shown, 1);
  t.mock.timers.tick(60000); await flush(); assert.equal(s.counts().requests, 5);
  t.mock.timers.tick(5000); await flush(); assert.equal(s.counts().requests, 6);
});

test("null native report retries and failed refresh never renews badge expiry", async t => {
  let calls = 0;
  const s = setup(t, undefined, { request: () => ++calls === 1 ? { details: {}, isValid: () => true } : null });
  t.mock.timers.tick(450); await flush();
  t.mock.timers.tick(60000); await flush();
  assert.equal(s.badges[0].expired, false);
  t.mock.timers.tick(5000); await flush();
  assert.deepEqual(s.counts(), { requests: 3, shown: 1 });
  assert.equal(s.badges[0].expired, true);
});

test("malformed classification retries with the same bounded backoff", async t => {
  const s = setup(t, undefined, { reportBadge: () => null });
  for (const delay of [450, 5000, 5000]) { t.mock.timers.tick(delay); await flush(); }
  assert.deepEqual(s.counts(), { requests: 3, shown: 0 });
  t.mock.timers.tick(59999); await flush(); assert.equal(s.counts().requests, 3);
  t.mock.timers.tick(1); await flush(); assert.equal(s.counts().requests, 4);
});

test("expired detail report is rejected before classification", async t => {
  let classifications = 0;
  const s = setup(t, async () => { classifications++; return {}; }, {
    request: () => ({ details: {}, isValid: () => false }),
  });
  t.mock.timers.tick(450); await flush();
  assert.equal(classifications, 0); assert.equal(s.counts().shown, 0);
});

test("unload rejects an in-flight classification and leaves no refresh", async t => {
  let resolve;
  const s = setup(t, () => new Promise(done => { resolve = done; }));
  t.mock.timers.tick(450); await flush(); s.handle.stop(); resolve({}); await flush();
  t.mock.timers.tick(60000); await flush();
  assert.deepEqual(s.counts(), { requests: 1, shown: 0 });
});

for (const change of ["account", "app", "tile", "status", "running"]) {
  test(`late classification rejects changed ${change} binding`, async t => {
    let resolve;
    const s = setup(t, () => new Promise(done => { resolve = done; }));
    t.mock.timers.tick(450); await flush();
    if (change === "account") s.setAccount("next-account");
    if (change === "app") s.store.GetAppOverviewByAppID = () => ({ display_status: 0 });
    if (change === "tile") s.tile.id = 456;
    if (change === "status") s.app.display_status = 6;
    if (change === "running") s.router.RunningApps = undefined;
    resolve({}); await flush(); assert.equal(s.counts().shown, 0);
  });
}

test("focus loss and unload cancel pending retries", async t => {
  const s = setup(t, async () => { throw Error("temporary"); });
  t.mock.timers.tick(450); await flush();
  s.document.activeElement = null; s.observers[0].callback();
  t.mock.timers.tick(60000); await flush(); assert.equal(s.counts().requests, 1);
  s.document.activeElement = s.tile; s.listeners.get("focusin")({ type: "focusin", target: s.tile });
  t.mock.timers.tick(450); await flush(); s.handle.stop();
  t.mock.timers.tick(60000); await flush(); assert.equal(s.counts().requests, 2);
});
