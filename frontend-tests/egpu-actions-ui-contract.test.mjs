import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const actions = readFileSync(new URL('../src/quick-access/expanded-command-center/egpu-actions-ui.tsx', import.meta.url), 'utf8');
const nav = readFileSync(new URL('../src/quick-access/expanded-command-center/navigation-contract.ts', import.meta.url), 'utf8');

test('eGPU quick actions stay stable and use four columns', () => {
  for (const id of ['switch-handheld','safe-disconnect','resolution','disconnect-sleep','disconnect-shutdown','status']) {
    assert.match(actions, new RegExp(`"${id}"`));
    assert.match(nav, new RegExp(`"${id}"`));
  }
  assert.match(actions, /gridTemplateColumns: "repeat\(4,minmax\(0,1fr\)\)"/);
});

test('sleep popup preserves both attached-sleep and disconnect-first choices', () => {
  assert.match(actions, /Sleep with eGPU connected/);
  assert.match(actions, /Keep eGPU connected/);
  assert.match(actions, /Safe Disconnect \+ Sleep/);
  assert.match(actions, /Resume with the existing physical connection still attached/);
});

test('USB authorization popup is explicit and does not invent persistent trust', () => {
  assert.match(actions, /USB authorization required/);
  assert.match(actions, /Allow this USB device\?/);
  assert.match(actions, /Not now/);
  assert.doesNotMatch(actions, /Always allow/);
  assert.doesNotMatch(actions, /Trust forever/);
});

test('power actions keep sleep and shutdown separate from unplug clearance', () => {
  assert.match(actions, /Safe Disconnect \+ Shutdown/);
  assert.match(actions, /physical unplug clearance/);
});
