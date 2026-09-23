import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('physical Ally cards use concise eGPU copy and never split words in artwork tiles', () => {
  const actions = read('src/quick-access/expanded-command-center/test-build-actions.ts');
  const tiles = read('src/quick-access/expanded-command-center/regear-tile.tsx');
  assert.match(actions, /unavailable\('switch-handheld','Handheld'\)/);
  assert.match(actions, /value:'Check status'/);
  assert.match(actions, /title:'Disconnect \+ Shutdown'/);
  assert.match(tiles, /rg-v3-tile-copy \.rg-expanded-value\{[^}]*overflow-wrap:normal[^}]*word-break:normal[^}]*hyphens:none/);
  assert.doesNotMatch(tiles, /rg-v3-tile-copy \.rg-expanded-value\{[^}]*overflow-wrap:anywhere/);
});

test('initial connection popup uses compact waiting copy and constrained footer actions', () => {
  const model = read('src/connection-progress-model.ts');
  const frame = read('src/popup-frame.tsx');
  assert.match(model, /"Waiting for eGPU detection": "Detecting eGPU"/);
  assert.match(model, /row\.state === "waiting" \? "Waiting"/);
  assert.match(model, /status\.gpuName \?\? "eGPU"} detected/);
  assert.match(model, /!fresh \? "eGPU status unavailable"/);
  assert.match(model, /: "Waiting for eGPU"/);
  assert.match(frame, /rg-flow-node small\{display:none}/);
  assert.match(frame, /rg-compact \.rg-popup-footer button\{[^}]*width:auto!important[^}]*flex:0 0 auto!important/);
});
