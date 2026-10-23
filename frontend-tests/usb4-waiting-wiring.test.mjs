import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=readFileSync(new URL('../src/index.tsx',import.meta.url),'utf8');
const tree=ts.createSourceFile('index.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const node=tree.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='createUsb4WaitingSnapshotReader');
assert.ok(node,'production index owns a direct snapshot reader');
const code=ts.transpileModule(node.getText(tree),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const create=new Function(`${code};return createUsb4WaitingSnapshotReader;`)();
function harness(){
 let clock=Date.parse('2026-10-10T01:00:00Z'),nextTimer=0;
 const replies=[],seen=[],timers=new Map(),owner={active:true,generation:1,stopped:false};let withdrawals=0;
 const runtime={observe:r=>seen.push(r),withdraw:()=>withdrawals++};
 const reader=create({owner,runtime,read:()=>new Promise((resolve,reject)=>replies.push({resolve,reject})),now:()=>clock,
  setTimeout:(fn,delay)=>{timers.set(++nextTimer,{fn,at:clock+delay});return nextTimer;},clearTimeout:id=>timers.delete(id)});
 const payload=(admission='observation-only',stamp=clock)=>({snapshot:{schema_version:3,observed_at:new Date(stamp).toISOString()},runtime_admission:{schema_version:1,sleep_interceptor_admission:admission,mode:'observation-only',mutation_allowed:false},usb4_waiting:{schema_version:1,state:'unauthorized',notice_key:'uw-'+ 'a'.repeat(32)}});
 return {reader,runtime,owner,replies,seen,timers,payload,get withdrawals(){return withdrawals;},advance(ms){clock+=ms;for(const [id,t]of timers)if(t.at<=clock){timers.delete(id);t.fn();}},clock:()=>clock};
}
test('fresh direct same-response receipt, expiry and no additional requests',async()=>{
 const h=harness(),p=h.reader.read(),wire=h.payload();h.replies[0].resolve(wire);assert.equal(await p,wire);
 assert.equal(h.replies.length,1);assert.equal(h.seen.length,1);assert.equal(h.seen[0].payload,wire);assert.ok(Object.isFrozen(h.seen[0]));
 h.advance(9999);assert.equal(h.withdrawals,0);h.advance(1);assert.equal(h.withdrawals,1);
});
test('a pending newer request cannot extend the previous receipt expiry',async()=>{
 const h=harness(),first=h.reader.read();h.replies[0].resolve(h.payload());await first;
 const pending=h.reader.read();h.advance(10000);assert.equal(h.withdrawals,1);
 h.replies[1].resolve(h.payload());await pending;assert.equal(h.seen.length,1);
});
test('latest-started reply wins; older invalid/error cannot withdraw newer receipt',async()=>{
 for(const fail of [false,true]){const h=harness(),a=h.reader.read(),b=h.reader.read();h.replies[1].resolve(h.payload());await b;
 if(fail)h.replies[0].reject(Error('old'));else h.replies[0].resolve({});await a.catch(()=>{});assert.equal(h.seen.length,1);assert.equal(h.withdrawals,0);}
});
test('fresh older supported reply latches lifetime and suppresses later observation-only',async()=>{
 const h=harness(),a=h.reader.read(),b=h.reader.read();h.replies[1].resolve(h.payload());await b;h.replies[0].resolve(h.payload('supported-runtime'));await a;
 assert.equal(h.withdrawals,1);h.owner.generation++;const c=h.reader.read();h.replies[2].resolve(h.payload());await c;assert.equal(h.seen.length,1);
});
test('future, malformed, expired and exact ten-second replies never admit',async()=>{
 for(const kind of ['future','expired','request','missing','accessor','inherited']){const h=harness(),p=h.reader.read();let wire=h.payload();
 if(kind==='future')wire=h.payload('observation-only',h.clock()+1);
 if(kind==='expired')wire=h.payload('observation-only',h.clock()-10000);
 if(kind==='request'){h.advance(10000);wire=h.payload();}
 if(kind==='missing')delete wire.runtime_admission;
 if(kind==='accessor')Object.defineProperty(wire,'runtime_admission',{get(){throw Error('must not execute');}});
 if(kind==='inherited')wire=Object.create(wire);
 h.replies[0].resolve(wire);await p;assert.equal(h.seen.length,0,kind);assert.equal(h.withdrawals,1,kind);}
});
test('unknown admission cannot latch; supported latch requires fresh literal provenance',async()=>{
 const h=harness();for(const wire of [h.payload('unknown'),h.payload('supported-runtime',h.clock()-10000),h.payload()]){const p=h.reader.read();h.replies.at(-1).resolve(wire);await p;}assert.equal(h.seen.length,1);
});
test('unknown then supported then observation-only remains suppressed across remount',async()=>{
 const h=harness();for(const admission of ['unknown','supported-runtime','observation-only']){
 const p=h.reader.read();h.replies.at(-1).resolve(h.payload(admission));await p;
 }assert.equal(h.seen.length,0);h.reader.withdraw();h.owner.generation++;
 const p=h.reader.read();h.replies.at(-1).resolve(h.payload());await p;assert.equal(h.seen.length,0);
 const fresh=harness(),q=fresh.reader.read();fresh.replies[0].resolve(fresh.payload());await q;assert.equal(fresh.seen.length,1);
});
test('error, generation change, inactive owner and stop retire without stale publication',async()=>{
 for(const kind of ['error','generation','inactive','stop']){const h=harness(),p=h.reader.read();if(kind==='error')h.replies[0].reject(Error('read'));else{if(kind==='generation')h.owner.generation++;if(kind==='inactive')h.owner.active=false;if(kind==='stop')h.reader.stop();h.replies[0].resolve(h.payload());}await p.catch(()=>{});assert.equal(h.seen.length,0,kind);assert.ok(h.withdrawals>=1,kind);assert.equal(h.timers.size,0,kind);}
});
test('synchronous presentation disposal cannot retain an expiry timer',async()=>{
 const h=harness();h.runtime.observe=()=>h.reader.stop();const p=h.reader.read();h.replies[0].resolve(h.payload());await p;assert.equal(h.timers.size,0);
});
test('presentation failure cannot turn a successful snapshot into a rejected RPC',async()=>{
 for(const port of ['observe','withdraw']){const h=harness();h.runtime[port]=()=>{throw Error('native presentation failure');};
 const p=h.reader.read(),wire=port==='observe'?h.payload():h.payload('supported-runtime');h.replies[0].resolve(wire);assert.equal(await p,wire);assert.equal(h.timers.size,0);}
});
test('all three existing production snapshot callers use shared reader and cleanup',()=>{
 assert.match(source,/getSnapshot as getSnapshotRPC/);assert.match(source,/snapshotReader=\{usb4SnapshotReader\.read\}/);
 assert.match(source,/const getSnapshot = usb4SnapshotReader\.read;/);
 assert.match(source,/Promise\.all\(\[getSnapshot\(\), getTransitionJournalStatus\(\)\]/);
 assert.match(source,/getSnapshot\(\), getAutomaticDockStatus\(\)/);
 assert.match(source,/usb4SnapshotReader\.stop\(\)/);assert.match(source,/withdrawUsb4Waiting\?\.\(\)/);
 assert.ok(source.includes("<Usb4WaitingStatus source={usb4WaitingSource}/>"));
});

test('production snapshot reader drives the actual passive notice runtime and withdraws at expiry',async()=>{
 const modelExports={},runtimeExports={};
 const modelCode=ts.transpileModule(readFileSync(new URL('../src/usb4-waiting-model.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 new Function('exports',modelCode)(modelExports);
 const runtimeCode=ts.transpileModule(readFileSync(new URL('../src/usb4-waiting-runtime.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 // No native host or security adapter is loaded. This executes the shipped
 // receipt/model/runtime composition with only its native show port substituted.
 const jsx=(type,props)=>({type,props});
 const require=(name)=>name==='./usb4-waiting-model'?modelExports:name==='react'?{useSyncExternalStore:(_subscribe,read)=>read()}:name==='react/jsx-runtime'?{jsx,jsxs:jsx}:name==='./quick-access/readable-block'?{ReadableBlock:'readonly-block'}:{};
 new Function('exports','require',runtimeCode)(runtimeExports,require);
 let clock=Date.parse('2026-10-10T01:00:00Z'),shown=0,closed=0,timer;
 const runtime=runtimeExports.createUsb4WaitingRuntime({now:()=>clock,show:()=>{shown++;return{close(){closed++;}};}});
 const payload={snapshot:{schema_version:3,observed_at:new Date(clock).toISOString()},runtime_admission:{schema_version:1,sleep_interceptor_admission:'observation-only',mode:'observation-only',mutation_allowed:false},usb4_waiting:{schema_version:1,state:'unauthorized',notice_key:'uw-'+ 'b'.repeat(32)}};
 const reader=create({owner:{active:true,generation:1,stopped:false},runtime,read:async()=>payload,now:()=>clock,setTimeout:fn=>{timer=fn;return 1;},clearTimeout:()=>{timer=undefined;}});
 await reader.read();assert.equal(shown,1);assert.equal(runtime.source.read()?.state,'unauthorized');
 const rendered=runtimeExports.Usb4WaitingStatus({source:runtime.source});
 assert.equal(rendered.type,'readonly-block');assert.equal(rendered.props.children.props.role,'status');
 assert.equal(rendered.props.children.props.children,modelExports.USB4_WAITING_TEXT);
 assert.equal(rendered.props.onClick,undefined);assert.equal(rendered.props.children.props.onClick,undefined);
 clock+=10000;timer();assert.equal(closed,1);assert.equal(runtime.source.read(),null);assert.equal(runtimeExports.Usb4WaitingStatus({source:runtime.source}),null);
 payload.snapshot.observed_at=new Date(clock).toISOString();await reader.read();assert.equal(shown,1,'same key cannot reprompt after expiry');
 reader.stop();runtime.stop();assert.equal(runtime.source.read(),null);
});
