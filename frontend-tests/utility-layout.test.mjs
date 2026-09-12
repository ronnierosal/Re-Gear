import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import ts from "typescript";
const js=ts.transpileModule(readFileSync(new URL('../src/quick-access/expanded-command-center/utility-layout.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ES2022}}).outputText;
const {normalizeUtilityLayout:normalize,defaultUtilityLayout:defaults,commandCenterUtilityIds,quickActionIds,optionalQuickActionIds}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
test('approved command center button groups stay stable',()=>{
 assert.deepEqual([...commandCenterUtilityIds],['brightness','volume']);
 assert.deepEqual([...quickActionIds],['mic','wifi','overlay','recording']);
 assert.deepEqual([...optionalQuickActionIds],['audio']);
});
test('approved default keeps brightness and volume left and thumb actions right',()=>{
 assert.deepEqual(defaults,[
  {id:'brightness',side:'left'},{id:'volume',side:'left'},
  {id:'mic',side:'right'},{id:'wifi',side:'right'},
  {id:'overlay',side:'right'},{id:'recording',side:'right'},
 ]);
});
test('malformed stored preference restores defaults without sharing mutable entries',()=>{
 const actual=normalize(null);assert.deepEqual(actual,defaults);actual[0].side='right';assert.equal(defaults[0].side,'left');
});
test('brightness and volume can never be moved or removed by customization',()=>{
 assert.deepEqual(normalize([]),[{id:'brightness',side:'left'},{id:'volume',side:'left'}]);
 assert.deepEqual(normalize([{id:'brightness',side:'right'},{id:'volume',side:'right'},{id:'mic',side:'right'}]),[
  {id:'brightness',side:'left'},{id:'volume',side:'left'},{id:'mic',side:'right'}
 ]);
});
test('right rail preserves chosen order and accepts supported optional actions only',()=>{
 assert.deepEqual(normalize([{id:'audio',side:'right'},{id:'recording',side:'right'},{id:'wifi',side:'right'}]),[
  {id:'brightness',side:'left'},{id:'volume',side:'left'},
  {id:'audio',side:'right'},{id:'recording',side:'right'},{id:'wifi',side:'right'}
 ]);
});
test('invalid, duplicate and left-side quick actions cannot corrupt layout',()=>{
 assert.deepEqual(normalize([{id:'mic',side:'right'},{id:'mic',side:'right'},{id:'overlay',side:'left'},{id:'fake',side:'right'},null]),[
  {id:'brightness',side:'left'},{id:'volume',side:'left'},{id:'mic',side:'right'}
 ]);
});
