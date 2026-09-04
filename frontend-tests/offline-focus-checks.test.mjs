import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const js = ts.transpileModule(readFileSync(new URL("../src/offline-focus-checks.tsx", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText.replace(/^import .*;\r?\n/gm, "").replace("export function startOfflineFocusChecks", "function startOfflineFocusChecks");

function setup(t, classify = async () => ({})) {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const listeners = new Map();
  const app = { display_status: 0 };
  const store = { GetAppOverviewByAppID: () => app };
  const router = { RunningApps: [] };
  const document = { addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) };
  const view = { document };
  const tile = { id: 123, ownerDocument: { ...document, defaultView: view }, isConnected: true, closest: () => tile };
  tile.ownerDocument = document; document.defaultView = view; document.activeElement = tile;
  let requests = 0; let shown = 0;
  const start = new Function("window", "Router", "routerHook", "callable", "OfflineDetailsSession", "offlineNativeSource", "attachOfflineTileBadge", "exactTileElementAppId", "OFFLINE_TILE_SELECTOR", "offlineReportBadge", "offlineBadgeImages", js + "\nreturn startOfflineFocusChecks;")(
    { appStore: store, DFL: { getGamepadNavigationTrees: () => [{ m_window: view }] } }, router,
    { addPatch: () => ({}), removePatch() {} }, () => classify,
    class { invalidate() {} async request() { requests++; return { details: {}, isValid: () => true }; } },
    () => ({ store, subscribe() {} }), () => { shown++; return { stop() {} }; }, tile => tile.id,
    "tile", () => ({ asset: "offline-verify", label: "Check" }), { "offline-verify": "badge.svg" },
  );
  const handle = start(); t.after(() => handle.stop());
  return { document, tile, app, router, listeners, counts: () => ({ requests, shown }) };
}
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

test("already focused game checks once after settling", async t => {
  const s = setup(t); t.mock.timers.tick(449); assert.equal(s.counts().requests, 0);
  t.mock.timers.tick(1); await flush(); assert.deepEqual(s.counts(), { requests: 1, shown: 1 });
});
test("loss of focus or game start before settling suppresses requests", async t => {
  const s = setup(t); s.document.activeElement = null;
  t.mock.timers.tick(450); await flush(); assert.equal(s.counts().requests, 0);
  s.document.activeElement = s.tile; s.listeners.get("focusin")({ target: s.tile }); s.app.display_status = 4;
  t.mock.timers.tick(450); await flush(); assert.equal(s.counts().requests, 0);
});
test("classification failure is contained and subsequent focus can retry", async t => {
  let calls = 0;
  const s = setup(t, async () => { if (++calls === 1) throw Error("Decky unavailable"); return {}; });
  t.mock.timers.tick(450); await flush(); assert.equal(s.counts().shown, 0);
  s.listeners.get("focusin")({ target: s.tile }); t.mock.timers.tick(450); await flush();
  assert.deepEqual(s.counts(), { requests: 2, shown: 1 });
});
test("late classification cannot show after focus changes", async t => {
  let resolve;
  const s = setup(t, () => new Promise(done => { resolve = done; }));
  t.mock.timers.tick(450); await flush(); s.document.activeElement = null;
  resolve({}); await flush(); assert.equal(s.counts().shown, 0);
});
