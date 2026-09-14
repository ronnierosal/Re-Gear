import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const compile=name=>ts.transpileModule(readFileSync(new URL('../src/quick-access/expanded-command-center/'+name,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ES2022,target:ts.ScriptTarget.ES2022}}).outputText.replace(/^import .*;$/gm,'');
const {createRuntimeDetailPublisher}=await import('data:text/javascript;base64,'+Buffer.from(compile('runtime-detail-source.ts')).toString('base64'));
const state=(available,request=()=>{})=>({views:{egpu:'eGPU','egpu-config':'Configuration',diagnostics:'Diagnostics',display:'Display'},handheld:{available,reason:'Current readiness',request}});
test('detail source updates existing nodes and invokes only the current available adapter',()=>{
 const p=createRuntimeDetailPublisher();let calls=0,updates=0;p.source.subscribe(()=>updates++);p.publish(state(true,()=>calls++));p.source.requestHandheld();assert.equal(calls,1);p.publish(state(false,()=>calls++));p.source.requestHandheld();assert.equal(calls,1);assert.equal(updates,2);
});
test('detail navigation and delayed cleanup preserve the current selection',()=>{
 const p=createRuntimeDetailPublisher(),old=p.source.enter('egpu');p.source.navigate('diagnostics');assert.equal(p.source.readSelection().current,'diagnostics');const current=p.source.enter('display');old();assert.equal(p.source.readSelection().current,'display');current();assert.equal(p.source.readSelection(),null);
});
test('plugin stop clears state and rejects late publication, selection and dispatch',()=>{
 const p=createRuntimeDetailPublisher();let calls=0;p.publish(state(true,()=>calls++));p.source.enter('egpu');p.stop();p.publish(state(true,()=>calls++));p.source.navigate('diagnostics');p.source.enter('display');p.source.requestHandheld();assert.equal(p.source.read(),null);assert.equal(p.source.readSelection(),null);assert.equal(calls,0);
});
