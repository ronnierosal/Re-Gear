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
  assert.equal(sampleTiles.quick.at(-1).tone,'warning');
});

test('Performance keeps six compact tuning entry points',()=>{
  assert.deepEqual(ids('performance'),['profile','fps','manual','auto','display','refresh']);
  assert.equal(sampleTiles.performance.length,6);
  assert.equal(sampleTiles.performance.some(tile=>tile.wide),false,'Performance must not grow a hero/banner card');
});

test('eGPU keeps connection, output, render and safety concepts separate',()=>{
  assert.deepEqual(ids('egpu'),['device','dock','display','render','link','disconnect']);
  assert.equal(sampleTiles.egpu.at(-1).wide,true);
  assert.equal(sampleTiles.egpu.at(-1).tone,'warning');
  assert.equal(sampleTiles.egpu.find(tile=>tile.id==='render').tone,'unavailable','unverified render GPU stays explicit');
});

test('Controllers keeps assignment, battery and dock policy distinct',()=>{
  assert.deepEqual(ids('controllers'),['controller','battery','builtin','priority','tv-controller','controller-settings']);
  assert.equal(sampleTiles.controllers.find(tile=>tile.id==='battery').tone,'unavailable');
  assert.equal(sampleTiles.controllers.some(tile=>tile.wide),false);
});

test('Settings stays focused on Re-Gear preferences and support',()=>{
  assert.deepEqual(ids('settings'),['quick-actions','shortcut','appearance','updates','diagnostics','about']);
  assert.equal(sampleTiles.settings.find(tile=>tile.id==='updates').tone,'unavailable');
  assert.equal(sampleTiles.settings.some(tile=>tile.wide),false);
});

test('module samples never add extra top-level surfaces',()=>{
  assert.deepEqual(Object.keys(sampleTiles),['quick','performance','egpu','controllers','settings']);
});

test('only approved safety actions use wide cards',()=>{
  const wide=Object.entries(sampleTiles).flatMap(([tab,tiles])=>tiles.filter(tile=>tile.wide).map(tile=>`${tab}:${tile.id}`));
  assert.deepEqual(wide,['quick:disconnect','egpu:disconnect']);
});

test('overview cards keep one primary value and concise supporting detail',()=>{
  for(const [tab,tiles] of Object.entries(sampleTiles)) for(const tile of tiles){
    assert.ok(tile.title.trim().length>0,`${tab}:${tile.id} title`);
    assert.ok(tile.value.trim().length>0,`${tab}:${tile.id} value`);
    assert.ok(tile.detail.trim().length>0,`${tab}:${tile.id} detail`);
    assert.ok(tile.detail.length<120,`${tab}:${tile.id} detail should stay overview-sized`);
  }
});
