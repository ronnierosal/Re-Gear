import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const compile = file => ts.transpileModule(readFileSync(new URL('../src/'+file, import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const url = text => 'data:text/javascript;base64,'+Buffer.from(text).toString('base64');
const source = compile('connection-monitor.ts').replace('"./connection-live-status"',JSON.stringify(url(compile('connection-live-status.ts'))));
const {startConnectionMonitor} = await import(url(source));
const sample = (connected, age=0) => ({payload:{snapshot:{observed_at:new Date(Date.now()-age).toISOString(),game_state:'idle'},inference:{mode:'portable'},connection_readiness:{stage:connected?'waiting_for_pci':'disconnected',checks_age_ms:0}},automatic:{enabled:true},journal:'journal.idle'});
const settle = () => new Promise(resolve=>setImmediate(resolve));
function harness(initial) {
 let value=initial, next, opened=0, closed=0;
 const monitor=startConnectionMonitor({read:async()=>{if(value instanceof Error)throw value;return value;},show:()=>{opened++;return {Close(){closed++;}};},schedule:cb=>{next=cb;return 1;},cancel:()=>{next=null;}});
 return {monitor,get opened(){return opened;},get closed(){return closed;},async step(v){value=v;next();await settle();}};
}
test('background connection opens once without any panel mount; disconnect rearms',async()=>{
 const h=harness(sample(false));await settle();assert.equal(h.opened,0);
 await h.step(sample(true));assert.equal(h.opened,1);
 await h.step(sample(true));assert.equal(h.opened,1);
 await h.step(sample(false));assert.equal(h.closed,1);
 await h.step(sample(true));assert.equal(h.opened,2);h.monitor.stop();
});
test('attached startup and stale absence do not create a new connection',async()=>{
 const h=harness(sample(true));await settle();assert.equal(h.opened,0);
 await h.step(sample(false,20000));await h.step(sample(true));assert.equal(h.opened,0);
 await h.step(new Error('offline'));await h.step(sample(true));assert.equal(h.opened,0);h.monitor.stop();
});
test('late RPC completion after plugin unload cannot open a modal',async()=>{
 let resolve;let opened=0;let scheduled=0;
 const h=startConnectionMonitor({read:()=>new Promise(r=>resolve=r),show:()=>{opened++;return {Close(){}};},schedule:()=>{scheduled++;return 1;}});
 h.stop();resolve(sample(true));await settle();assert.equal(opened,0);assert.equal(scheduled,0);
});
