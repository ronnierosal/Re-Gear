import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const transpile = name => ts.transpileModule(readFileSync(new URL('../src/' + name, import.meta.url), 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const model = {};
new Function('exports', transpile('whole-dock-control-model.ts'))(model);
const request = 'f3748623155e46b0ad40567847a03a18';
const key = 'regear.whole-dock.pending-request';
// Saved golden180 terminal shape, including the omitted software_down field.
const captured = () => ({ schema_version: 1, request_id: request, code: 'dock_power.disconnect_unverified',
  busy: false, in_flight: false, ok: false, safe_to_unplug: false, power_action: 'shutdown',
  power_requested: false, route_action: 'whole_dock_shutdown', claim_stage: 'tunnel_remove_intent',
  phase: 'dock_teardown', release_stage: 'removed',
  release: { code: 'live_disconnect.removed', released: true, display_released: true, filter_disarmed: true },
  teardown: { code: 'dock_teardown.unresolved', tunnel_stage: 'settle',
    tunnel_code: 'dock_teardown.tunnel_settle_unverified', tunnel_reason: 'dock_teardown.tunnel_settle_timeout',
    remaining_pci: { bridges: 6, endpoints: 0, unreadable: 0 } } });
function harness(status = captured()) {
  const values = new Map(), reads = [], writes = [], exports = {};
  const storage = { getItem: k => values.get(k) ?? null, setItem: (k, v) => values.set(k, v) };
  const imports = { './whole-dock-control-model': model, '@decky/api': { callable: name => (...args) => {
    if (name !== 'get_egpu_disconnect_status') { writes.push(args); throw Error('unexpected mutation'); }
    reads.push(args); return Promise.resolve(typeof status === 'function' ? status() : status);
  } } };
  new Function('exports', 'require', transpile('whole-dock-control.tsx'))(exports, name => imports[name] ?? {});
  return { values, reads, writes, storage, recover: () => exports.recoverTerminalDockReceipt(storage) };
}
test('saved shutdown timeout restores only its exact presentation receipt', async () => {
  const h = harness();
  assert.equal(model.dockRequestSettled(captured(), request, 'shutdown'), true);
  assert.deepEqual(await h.recover(), { intent: 'shutdown', request });
  assert.equal(h.values.get(key), `v2:shutdown:backend-terminal:${request}`);
  assert.deepEqual(h.reads, [['whole_dock_trial']]); assert.deepEqual(h.writes, []);
});
test('shutdown recovery rejects nonterminal, unsafe, malformed and mismatched results', async () => {
  for (const delta of [{ schema_version: 2 }, { request_id: 'bad' }, { busy: true }, { in_flight: true },
    { ok: true }, { safe_to_unplug: true }, { software_down: true }, { software_down: 'false' },
    { power_action: 'sleep' }, { power_requested: true }, { power_requested: 'false' },
    { route_action: 'whole_dock_sleep' }, { claim_stage: 'software_down' }, { phase: 'power_verification' },
    { release_stage: 'armed' }, { release: { released: true } },
    { teardown: { tunnel_reason: 'dock_teardown.tunnel_settle_timeout' } }]) {
    const h = harness({ ...captured(), ...delta });
    assert.equal(await h.recover(), null); assert.equal(h.values.size, 0); assert.deepEqual(h.writes, []);
  }
});
test('existing receipt prevents a read or replacement', async () => {
  const h = harness(); h.values.set(key, 'v2:sleep:other:' + 'a'.repeat(32));
  assert.equal(await h.recover(), null); assert.equal(h.reads.length, 0); assert.deepEqual(h.writes, []);
});
test('receipt created during backend read is preserved', async () => {
  let resolve; const response = new Promise(done => { resolve = done; }); const h = harness(() => response);
  const answer = h.recover(), other = 'v2:sleep:other:' + 'a'.repeat(32);
  h.values.set(key, other); resolve(captured());
  assert.equal(await answer, null); assert.equal(h.values.get(key), other); assert.deepEqual(h.writes, []);
});
test('failed read or storage write cannot fabricate a receipt or dispatch', async () => {
  for (const failRead of [true, false]) {
    const h = harness(() => { if (failRead) throw Error('read unavailable'); return captured(); });
    h.storage.setItem = () => { throw Error('storage unavailable'); };
    assert.equal(await h.recover(), null); assert.equal(h.values.size, 0); assert.deepEqual(h.writes, []);
  }
});
