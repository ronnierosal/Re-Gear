import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const base='../src/quick-access/expanded-command-center/';
const compile=name=>ts.transpileModule(readFileSync(new URL(base+name,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ES2022,target:ts.ScriptTarget.ES2022}}).outputText.replace(/^import .*;$/gm,'').replace(/export /g,'');
const api=new Function(compile('model.ts')+compile('utility-layout.ts')+compile('layout-preferences.ts')+';return {normalizeLayout,loadLayout,saveLayout,projectLayout,replaceSlot};')();
test('layout storage keeps four valid distinct right slots and recovers malformed preferences',()=>{
 for(const raw of [null,{}, {right:[]},{right:['brightness','wifi','wifi','bad']},{right:['audio','wifi','mic','recording','overlay']}]){
  const p=api.normalizeLayout(raw);assert.equal(p.right.length,4);assert.equal(new Set(p.right).size,4);assert.ok(!p.right.includes('brightness'));
 }
 assert.deepEqual(api.loadLayout({getItem(){throw Error()}}),api.normalizeLayout(null));
 assert.throws(()=>api.saveLayout({setItem(){throw Error('full')}},api.normalizeLayout(null)),/full/);
});
test('source qualified selection reprojects fresh origin readings without mixing equal IDs',()=>{
 const source={quick:[{id:'display',title:'Target',value:'Internal',detail:''},{id:'disconnect',title:'Safe Disconnect',value:'Unknown',detail:''}],performance:[{id:'display',title:'Resolution',value:'1920',detail:'readback'}]};
 const prefs=api.normalizeLayout({quick:['performance:display','quick:disconnect']});
 const a=api.projectLayout(source,prefs);assert.equal(a.view.quick[0].title,'Resolution');assert.equal(a.resolve('quick',a.view.quick[0].id).tab,'performance');
 source.performance[0]={...source.performance[0],value:'1280'};
 assert.equal(api.projectLayout(source,prefs).view.quick[0].value,'1280');
 assert.deepEqual(api.replaceSlot(['a','b','c'],0,'c'),['c','b','a']);
});
test('other tabs reorder only and stored payload contains no readings',()=>{
 const prefs=api.normalizeLayout({order:{performance:['b','a']},quick:['quick:a']});
 let data;api.saveLayout({setItem(_,value){data=value}},prefs);assert.ok(!data.includes('value'));
 const source={performance:[{id:'a',value:'one'},{id:'b',value:'two'}]};
 assert.deepEqual(api.projectLayout(source,prefs).view.performance.map(x=>x.id),['b','a']);
});
