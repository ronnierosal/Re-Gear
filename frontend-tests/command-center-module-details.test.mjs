import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL('../src/quick-access/expanded-command-center/module-details.tsx', import.meta.url), 'utf8');

test('nested module detail compositions exist for all deep tabs', () => {
  for (const name of ['PerformanceDetail','EgpuDetail','ControllerDetail','SettingsDetail']) {
    assert.match(source, new RegExp(`export function ${name}\\b`));
  }
});

test('eGPU detail keeps connection concepts separate and safe disconnect explicit', () => {
  for (const label of ['External GPU','Dock mode','Display output','Render GPU','Connection link','Safe Disconnect']) {
    assert.match(source, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.match(source, /Readiness and unplug clearance are separate/);
});

test('controller detail keeps assignment and dock policy distinct', () => {
  for (const label of ['Player 1','Battery','Built-in controller','Controller priority','TV dock behavior']) {
    assert.match(source, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
});

test('settings detail remains Re-Gear focused', () => {
  for (const label of ['Quick Actions','Shortcut','Appearance','Updates','Diagnostics','About Re-Gear']) {
    assert.match(source, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
});
