import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const base='../src/quick-access/expanded-command-center/';
const compile=name=>ts.transpileModule(readFileSync(new URL(base+name,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ES2022,target:ts.ScriptTarget.ES2022}}).outputText.replace(/^import .*;$/gm,'').replace(/export /g,'');
const api=new Function(compile('model.ts')+compile('control-registry.ts')+compile('utility-layout.ts')+compile('layout-preferences.ts')+';return {normalizeLayout,loadLayout,saveLayout,projectLayout,replaceSlot};')();
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


test('empty main and right positions persist, support targeted add, and move without compacting',()=>{
 let saved;const storage={getItem:()=>saved??null,setItem:(_,value)=>{saved=value}};
 const tile=id=>({id,title:id,value:'Unavailable',detail:''});const source={quick:['a','b','c'].map(tile),egpu:[tile('sleep')]};
 const initial=api.projectLayout(source,api.loadLayout(storage));assert.equal(initial.view.quick.length,10);
 let prefs=api.normalizeLayout(null);prefs.quick=['quick:a','empty:removed','quick:c',...Array.from({length:7},(_,i)=>`empty:${i}`)];prefs.right=['mic',null,'overlay','recording'];
 api.saveLayout(storage,prefs);prefs=api.loadLayout(storage);assert.equal(prefs.right[1],null);
 let view=api.projectLayout(source,prefs);assert.equal(view.view.quick[1].empty,true);assert.equal(view.view.quick[2].id,'c');assert.ok(!view.view.quick.some(x=>x.id==='b'));
 prefs.quick=api.replaceSlot(prefs.quick,1,'egpu:sleep');api.saveLayout(storage,prefs);prefs=api.loadLayout(storage);
 assert.equal(api.projectLayout(source,prefs).view.quick[1].id,'custom:egpu:sleep');
 prefs.quick=api.replaceSlot(prefs.quick,1,'empty:0');api.saveLayout(storage,prefs);view=api.projectLayout(source,api.loadLayout(storage));assert.equal(view.view.quick[1].empty,true);assert.equal(view.view.quick[3].id,'custom:egpu:sleep');
 assert.equal(api.normalizeLayout({version:2,right:[null,'brightness','wifi','wifi']}).right.filter(x=>x===null).length,3);
});


test('padding never duplicates existing blank identities and withdrawn origins survive other edits',()=>{
 const source={quick:[{id:'a'}],performance:[{id:'manual',value:'18 W'}]};
 let prefs=api.normalizeLayout({quick:['empty:9']});let view=api.projectLayout(source,prefs).view.quick;
 assert.equal(view.length,10);assert.equal(new Set(view.map(x=>x.id)).size,10);
 prefs=api.normalizeLayout({quick:['performance:manual','quick:a']});source.performance=[];
 view=api.projectLayout(source,prefs).view.quick;
 prefs.quick=view.map(tile=>tile.layoutKey??`quick:${tile.id}`);prefs.quick[1]='empty:removed';
 source.performance=[{id:'manual',value:'20 W'}];view=api.projectLayout(source,prefs).view.quick;
 assert.equal(view[0].id,'custom:performance:manual');assert.equal(view[0].value,'20 W');
});
