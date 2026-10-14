import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const transpile = name => ts.transpileModule(
  readFileSync(new URL('../src/' + name, import.meta.url), 'utf8'),
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
    jsx: ts.JsxEmit.ReactJSX } },
).outputText;
const model = {};
new Function('exports', transpile('whole-dock-control-model.ts'))(model);
const request = 'f'.repeat(32);
const waiting = (code = 'dock_power.unplug_required') => ({
  schema_version: 1, request_id: request, code, busy: true, in_flight: true,
  ok: false, software_down: true, safe_to_unplug: false, unplug_required: true,
  power_action: 'shutdown', power_requested: false,
  route_action: 'whole_dock_shutdown', phase: 'power_verification',
});

// Execute the actual recovery function with only its Decky read/storage boundaries replaced.
function harness(status) {
  const values = new Map(), writes = [], exports = {};
  const storage = { getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value) };
  const imports = {
    './whole-dock-control-model': model,
    '@decky/api': { callable: name => (...args) => {
      if (name !== 'get_egpu_disconnect_status') {
        writes.push([name, args]); throw Error('unexpected mutation');
      }
      return Promise.resolve(status);
    } },
  };
  new Function('exports', 'require', transpile('whole-dock-control.tsx'))(
    exports, name => imports[name] ?? {},
  );
  return { recover: () => exports.recoverTerminalDockReceipt(storage), values, writes };
}

for (const code of ['dock_power.unplug_required', 'dock_power.unplug_request_expired',
  'dock_power.unplug_request_cancelled']) {
  test('actual receipt recovery preserves shutdown ' + code + ' without replay', async () => {
    const h = harness(waiting(code));
    assert.deepEqual(await h.recover(), { intent: 'shutdown', request });
    assert.deepEqual(h.writes, []);
    assert.equal(model.dockRequestSettled(waiting(code), request, 'shutdown'), false);
    const view = model.dockIntentControl(waiting(code), null, 'shutdown');
    assert.equal(view.action, null); assert.match(view.message, /unplug/i);
    if (code !== 'dock_power.unplug_required') assert.match(view.message, /will not|cancelled|expired/);
  });
}

test('shutdown waiting recovery rejects unsafe or uncorrelated state', async () => {
  for (const delta of [{ request_id: 'bad' }, { schema_version: 2 }, { busy: false },
    { in_flight: false }, { ok: true }, { software_down: false }, { safe_to_unplug: true },
    { unplug_required: false }, { power_requested: true }, { power_action: 'sleep' },
    { route_action: 'whole_dock_sleep' }, { phase: 'dock_teardown' }]) {
    const h = harness({ ...waiting(), ...delta });
    assert.equal(await h.recover(), null); assert.equal(h.values.size, 0);
    assert.deepEqual(h.writes, []);
  }
});

test('stopped shutdown after verified absence never asks to reconnect or promises poweroff', () => {
  for (const code of ['dock_power.unplug_request_expired', 'dock_power.unplug_request_cancelled']) {
    const status = { ...waiting(code), busy: false, in_flight: false,
      unplug_required: false, physical_absence_verified: true };
    const view = model.dockIntentControl(status, null, 'shutdown');
    assert.equal(view.action, null); assert.match(view.message, /Physical absence was verified/);
    assert.doesNotMatch(view.message, /Keep the cable connected|shutdown was requested/i);
    assert.equal(model.dockRequestSettled(status, request, 'shutdown'), true);
  }
});
