import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const js = ts.transpileModule(readFileSync(new URL('../src/display-action.ts', import.meta.url), 'utf8'), {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {displayAction} = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));
const action = (mode, ...flags) => displayAction(mode, ...[false,false,false,false].map((v,i)=>flags[i]??v));
test('actual domain TV mode exposes return to handheld and Portable exposes TV', () => {
  for (const mode of ['tv_docked', 'docked_egpu']) {
    assert.equal(action(mode).target, 'ally');
    assert.equal(action(mode).title, 'Switch to handheld');
    assert.equal(action(mode).disabled, false);
  }
  assert.equal(action('portable').target, 'tv');
  assert.equal(action('portable').title, 'Switch to TV');
});
test('unknown, degraded and boosted modes do not acquire a transition', () => {
  for (const mode of [undefined, 'unknown', 'degraded', 'boosted_handheld']) {
    assert.equal(action(mode).target, null);
    assert.equal(action(mode).disabled, true);
    assert.match(action(mode).description, /unverified/);
  }
});
test('TV return retains acknowledgement and journal gates with actionable explanations', () => {
  assert.equal(action('tv_docked',false,true).disabled, true);
  assert.match(action('tv_docked',false,true).description, /Acknowledge/);
  assert.equal(action('tv_docked',false,false,true).disabled, true);
  assert.match(action('tv_docked',false,false,true).description, /prior operation/);
  assert.equal(action('tv_docked',true).disabled, true);
  assert.match(action('tv_docked',true).description, /Wait/);
});
