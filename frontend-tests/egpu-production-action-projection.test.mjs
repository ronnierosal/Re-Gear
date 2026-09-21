import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const root = new URL('../src/quick-access/expanded-command-center/', import.meta.url);
const projectionSource = readFileSync(new URL('test-build-actions.ts', root), 'utf8')
  .replace(/^import .*?;\r?\n/gm, '');
const compiled = ts.transpileModule(projectionSource, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const projection = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'));
const nativeSource = readFileSync(new URL('native.tsx', root), 'utf8');

const input = {
  quick:[{id:'disconnect',title:'Safe Disconnect',value:'Unavailable',detail:'No current observation',tone:'unavailable'}],
  egpu:[{id:'link',title:'Connection Link',value:'Unavailable',detail:'No current observation',tone:'unavailable'}],
};

test('live eGPU actions do not inherit an unavailable overview reading as their action gate', () => {
  const view = projection.testBuildTiles(input);
  assert.deepEqual(view.egpu.map(tile=>tile.id), ['switch-handheld','disconnect','resolution','egpu','disconnect-sleep','disconnect-shutdown']);
  assert.equal(view.egpu[0].title,'Switch to Handheld');
  assert.equal(view.egpu[2].value,'Unavailable');
  assert.equal(view.egpu[3].title,'eGPU Status');
  for(const id of ['disconnect','disconnect-shutdown']){
    const tile=view.egpu.find(item=>item.id===id);
    assert.equal(tile.value,'Check readiness');
    assert.equal(tile.tone,'warning');
    assert.match(tile.detail,/evaluate current teardown conditions/);
  }
  const connectedSleep=view.egpu.find(item=>item.id==='disconnect-sleep');
  assert.equal(connectedSleep.title,'Sleep — Keep eGPU Connected');
  assert.match(connectedSleep.detail,/Normal sleep keeps the eGPU connected/);
  assert.equal(view.quick[0].value,'Check readiness');
});

test('native adapter preserves verified providers and only Resolution is fixed unavailable', () => {
  assert.match(nativeSource,/tone:runtimeState\?\.handheld\.available\?"quiet" as const:"unavailable" as const/);
  assert.match(nativeSource,/if\(tile\.id==="disconnect-sleep"\)\{runtimeDetails\?\.requestSleepConnected\(\);return true;\}/);
  assert.doesNotMatch(nativeSource,/disconnect\("sleep"\)/);
  assert.match(nativeSource,/if\(tile\.id==="disconnect-shutdown"\)\{disconnect\("shutdown"\);return true;\}/);
  assert.match(nativeSource,/if\(tile\.id==="switch-handheld"\)\{runtimeDetails\?\.requestHandheld\(\);return true;\}/);
  assert.deepEqual(projection.unavailableTestActions,{"switch-handheld":"Display integration pending",resolution:"Display integration pending"});
});
