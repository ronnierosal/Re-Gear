import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const compile=name=>ts.transpileModule(readFileSync(new URL('../src/quick-access/expanded-command-center/'+name,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ES2022,target:ts.ScriptTarget.ES2022}}).outputText.replace(/^import .*;$/gm,'');
const {createRuntimeDetailPublisher}=await import('data:text/javascript;base64,'+Buffer.from(compile('runtime-detail-source.ts')).toString('base64'));
const state=(available,request=()=>{},target='ally')=>({views:{egpu:'eGPU','egpu-config':'Configuration',diagnostics:'Diagnostics',display:'Display'},displayAction:{target,available,reason:'Current readiness',request}});
test('detail source updates existing nodes and invokes only the current available adapter',()=>{
 const p=createRuntimeDetailPublisher();let calls=0,updates=0;p.source.subscribe(()=>updates++);p.publish(state(true,()=>calls++));p.source.requestDisplayTarget();assert.equal(calls,1);p.publish(state(false,()=>calls++));p.source.requestDisplayTarget();assert.equal(calls,1);assert.equal(updates,2);
 p.publish(state(true,()=>calls++,'tv'));p.source.requestHandheld();assert.equal(calls,1);p.source.requestDisplayTarget();assert.equal(calls,2);
});
test('detail navigation and delayed cleanup preserve the current selection',()=>{
 const p=createRuntimeDetailPublisher(),old=p.source.enter('egpu');p.source.navigate('diagnostics');assert.equal(p.source.readSelection().current,'diagnostics');const current=p.source.enter('display');old();assert.equal(p.source.readSelection().current,'display');current();assert.equal(p.source.readSelection(),null);
});
test('plugin stop clears state and rejects late publication, selection and dispatch',()=>{
 const p=createRuntimeDetailPublisher();let calls=0;p.publish(state(true,()=>calls++));p.source.enter('egpu');p.stop();p.publish(state(true,()=>calls++));p.source.navigate('diagnostics');p.source.enter('display');p.source.requestDisplayTarget();assert.equal(p.source.read(),null);assert.equal(p.source.readSelection(),null);assert.equal(calls,0);
});

test('shutdown uses only the current available adapter and stops on owner loss',()=>{
 const p=createRuntimeDetailPublisher();let calls=0;
 p.source.requestShutdown();p.publish(state(true));p.source.requestShutdown();assert.equal(calls,0);
 const next={...state(true),shutdown:{available:true,reason:'Portable',pending:false,message:'',request:()=>calls++}};
 p.publish(next);p.source.requestShutdown();assert.equal(calls,1);
 p.publish({...next,shutdown:{...next.shutdown,available:false}});p.source.requestShutdown();assert.equal(calls,1);
 p.publish(next);p.stop();p.source.requestShutdown();assert.equal(calls,1);
});

test('connection fact is optional presentation data and withdrawal preserves action ownership',()=>{
 const p=createRuntimeDetailPublisher();let calls=0;
 p.publish(state(true,()=>calls++));assert.equal(p.source.read().displayAction.egpuConnected,undefined);
 p.publish({...state(false,()=>calls++),displayAction:{...state(false).displayAction,egpuConnected:true,request:()=>calls++}});
 assert.equal(p.source.read().displayAction.egpuConnected,true);p.source.requestDisplayTarget();assert.equal(calls,0);
 p.publish({...state(true,()=>calls++),displayAction:{...state(true).displayAction,egpuConnected:null,request:()=>calls++}});
 assert.equal(p.source.read().displayAction.egpuConnected,null);p.source.requestDisplayTarget();assert.equal(calls,1);
 p.publish(null);assert.equal(p.source.read(),null);p.source.requestDisplayTarget();assert.equal(calls,1);
 p.publish({...state(true),displayAction:{...state(true).displayAction,egpuConnected:true}});p.stop();assert.equal(p.source.read(),null);
});
