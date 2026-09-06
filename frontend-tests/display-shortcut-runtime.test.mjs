import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
const compile = name => ts.transpileModule(readFileSync(new URL(`../src/${name}.ts`, import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const url = js => "data:text/javascript;base64," + Buffer.from(js).toString("base64");
const source = compile("display-shortcut-runtime").replace('"./controller-safe-disconnect"', JSON.stringify(url(compile("controller-safe-disconnect"))));
const { createDisplayShortcutRuntime } = await import(url(source));
const flush = async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); };
function setup(t, approve = async () => ({ approval_token: "token", blockers: [] })) {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let input, confirm, shown = 0, executed = 0, removed = 0;
  const runtime = createDisplayShortcutRuntime({
    input: {
      RegisterForControllerInputMessages(fn) { input = fn; return { unregister() { removed++; } }; },
      RegisterForControllerListChanges() { return { unregister() { removed++; } }; },
    },
    readContext: async () => ({ snapshot: { delivery_schema_version: 2, inference: { mode: "portable" }, snapshot: {
      schema_version: 3, observed_at: new Date().toISOString(), game_state: "idle", support_tier: "certified",
      gamescope: { running: true }, disconnect_readiness: { applicable: true },
      gpus: [{ role: "external", present: true, confidence: "verified" }],
    } }, journal: { code: "journal.idle" } }),
    show(target, ok) { assert.equal(target, "tv"); shown++; confirm = ok; return { Close() {} }; },
    approve, execute: async () => { executed++; return { accepted: true, code: "accepted" }; }, report() {},
  });
  return { runtime, input: (...args) => input(...args), confirm: () => confirm(), counts: () => ({shown, executed, removed}) };
}
test("plugin listener completes hold without mounting a panel and requires confirmation", async t => {
  const s = setup(t); s.input(0, 9, true); s.input(0, 3, true); await flush();
  t.mock.timers.tick(3000); await flush();
  assert.equal(s.counts().shown, 1); assert.equal(s.counts().executed, 0);
  s.confirm(); await flush(); assert.equal(s.counts().executed, 1);
  s.runtime.stop(); assert.equal(s.counts().removed, 2);
});
test("plugin unload cancels hold", async t => {
  const s = setup(t); s.input(0, 9, true); s.input(0, 3, true); s.runtime.stop();
  t.mock.timers.tick(4000); await flush(); assert.equal(s.counts().shown, 0);
});
test("unload while approval is pending prevents execution", async t => {
  let resolve;
  const s = setup(t, () => new Promise(r => { resolve = r; }));
  s.runtime.request("tv"); s.confirm(); s.runtime.stop();
  resolve({ approval_token: "token", blockers: [] }); await flush(); assert.equal(s.counts().executed, 0);
});
test("shared panel execution lock blocks global hotkey confirmation", t => {
  const s = setup(t); s.runtime.portableBusy.current = true; s.runtime.request("tv");
  assert.equal(s.counts().shown, 0); s.runtime.stop();
});
test("backend blocker never executes", async t => {
  const s = setup(t, async () => ({ approval_token: "token", blockers: ["running_game"] }));
  s.runtime.request("tv"); s.confirm(); await flush(); assert.equal(s.counts().executed, 0); s.runtime.stop();
});
