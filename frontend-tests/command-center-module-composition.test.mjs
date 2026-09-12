import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import ts from "typescript";

const source=readFileSync(new URL('../src/quick-access/expanded-command-center/model.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ES2022}}).outputText;
const {sampleTiles}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));

const ids=tab=>sampleTiles[tab].map(tile=>tile.id);

test('Quick Access keeps the approved action/status hierarchy',()=>{
  assert.deepEqual(ids('quick'),['fps','manual','auto','display','egpu','controller','disconnect']);
  assert.equal(sampleTiles.quick.at(-1).wide,true);
});

test('Performance keeps six compact tuning entry points',()=>{
  assert.deepEqual(ids('performance'),['profile','fps','manual','auto','display','refresh']);
});

test('eGPU keeps connection, output, render and safety concepts separate',()=>{
  assert.deepEqual(ids('egpu'),['device','dock','display','render','link','disconnect']);
  assert.equal(sampleTiles.egpu.at(-1).wide,true);
});

test('Controllers keeps assignment, battery and dock policy distinct',()=>{
  assert.deepEqual(ids('controllers'),['controller','battery','builtin','priority','tv-controller','controller-settings']);
});

test('Settings stays focused on Re-Gear preferences and support',()=>{
  assert.deepEqual(ids('settings'),['quick-actions','shortcut','appearance','updates','diagnostics','about']);
});

test('module samples never add extra top-level surfaces',()=>{
  assert.deepEqual(Object.keys(sampleTiles),['quick','performance','egpu','controllers','settings']);
});
