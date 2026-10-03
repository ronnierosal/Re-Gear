import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

// Canonical player terminology: docs/UI_DESIGN_SYSTEM.md#player-terminology.
// Every file that names these actions must use the same words, so one
// control never reads differently on two screens.
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const labelSources = [
  'src/quick-access/expanded-command-center/control-registry.ts',
  'src/quick-access/expanded-command-center/test-build-actions.ts',
  'src/quick-access/expanded-command-center/egpu-action-panel.tsx',
  'src/quick-access/expanded-command-center/display-target-action.ts',
  'src/quick-access/expanded-command-center/tile-source.ts',
  'src/quick-access/expanded-command-center/tutorials.tsx',
  'src/quick-access/command-center.ts',
  'src/quick-access/production-egpu-actions.tsx',
  'src/build-profile.ts',
  'src/display-action.ts',
  'src/index.tsx',
];

test('retired ambiguous labels do not return to player-facing label sources', () => {
  const retired = [
    // Does not say what is disconnected.
    /['"`]Disconnect \+ Sleep/, /Safe Disconnect \+ Shutdown/, /Disconnect \+ Shutdown/,
    // Device-specific wording for the handheld screen.
    /Return to Ally/, /returning to the Ally/,
    // Jargon title on a control that is either a status card or an action.
    /title: ?['"]Display Target['"]/, /label:'Display Target'/,
    // Reads as a status, not the action the button performs.
    /['"]Sleep connected['"]/, /['"]Display switch unavailable['"]/, /['"]Switch to handheld['"]/,
    // A second command on the card's status line.
    /value:'Check status'/,
  ];
  for (const path of labelSources) {
    const source = read(path);
    for (const pattern of retired) assert.doesNotMatch(source, pattern, `${path} uses retired wording ${pattern}`);
  }
});

test('each guarded eGPU action has one canonical label everywhere it is defined', () => {
  const registry = read('src/quick-access/expanded-command-center/control-registry.ts');
  const actions = read('src/quick-access/expanded-command-center/test-build-actions.ts');
  const panel = read('src/quick-access/expanded-command-center/egpu-action-panel.tsx');
  const fallback = read('src/build-profile.ts');
  for (const label of ['Disconnect eGPU & Sleep', 'Disconnect eGPU & Shut Down']) {
    for (const [name, source] of [['registry', registry], ['tiles', actions], ['eGPU panel', panel], ['production fallback', fallback]]) {
      assert.ok(source.includes(label), `${name} is missing ${label}`);
    }
  }
  assert.match(registry, /id:'safe-disconnect',[^\n]*label:'Safe Disconnect'/);
  assert.match(registry, /id:'portable-shutdown',[^\n]*label:'Shut Down'/);
});

test('display switching names its destination and keeps one wording for both directions', () => {
  const dashboard = read('src/display-action.ts');
  const tile = read('src/quick-access/expanded-command-center/display-target-action.ts');
  const confirm = read('src/index.tsx');
  for (const source of [dashboard, tile, confirm]) {
    assert.ok(source.includes('"Switch to TV'), 'Switch to TV');
    assert.ok(source.includes('"Switch to Handheld'), 'Switch to Handheld');
  }
  // Unavailable still reads as the action, with the reason in secondary text.
  assert.ok(dashboard.includes('"Switch Display"'));
  assert.ok(tile.includes('"Switch Display"'));
});
