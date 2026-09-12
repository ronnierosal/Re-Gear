import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import ts from "typescript";
const js=ts.transpileModule(readFileSync(new URL('../src/quick-access/expanded-command-center/utility-layout.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ES2022}}).outputText;
const {normalizeUtilityLayout:normalize,defaultUtilityLayout:defaults}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
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
test('intentional empty layout remains empty; order and chosen sides survive',()=>{
 assert.deepEqual(normalize([]),[]);
 const chosen=[{id:'audio',side:'left'},{id:'brightness',side:'right'}];assert.deepEqual(normalize(chosen),chosen);
});
test('invalid and duplicate controls cannot corrupt layout',()=>{
 assert.deepEqual(normalize([{id:'mic',side:'right'},{id:'mic',side:'left'},{id:'fake',side:'left'},null,{id:'volume',side:'elsewhere'}]),[{id:'mic',side:'right'}]);
});