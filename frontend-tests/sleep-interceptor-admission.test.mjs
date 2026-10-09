import assert from 'node:assert/strict';
import test from 'node:test';
import { SleepPreflightCoordinator } from '../src/sleep-preflight.ts';

const now = Date.parse('2026-10-09T04:00:00Z');
const snapshot = (admission = 'observation-only', offset = 0) => ({
  runtime_admission: { schema_version: 1, sleep_interceptor_admission: admission },
  snapshot: { schema_version: 3, observed_at: new Date(now + offset).toISOString() },
});
const absent = {kind:'fresh',guardRequired:false,guardConfidence:'verified',gameState:'idle',gameUsesEgpu:false};
function setup(options = {}) {
  const counts = {acquire:0,release:0,patch:0,unpatch:0,warn:0,retire:0};
  let saved;
  let coordinator;
  const adapter = {
    acquireBlocker() { counts.acquire++; return () => { counts.release++; options.release?.(coordinator, saved); }; },
    observeSuspendRequests(handler) { counts.patch++; saved=handler; return () => { counts.unpatch++; options.unpatch?.(coordinator, saved); }; },
  };
  coordinator = new SleepPreflightCoordinator(adapter, () => counts.warn++, () => { counts.retire++; options.retire?.(); });
  coordinator.start();
  return {coordinator,counts,request:()=>saved()};
}

test('190 Mini regression: explicit fresh observation-only retires startup protection permanently', () => {
  const {coordinator:c,counts,request}=setup();
  assert.equal(c.status().blocking,true);
  const status=c.admitSnapshot(snapshot(),now,10000);
  assert.equal(status.state,'retired'); assert.equal(status.reason,'observation_only'); assert.equal(status.blocking,false);
  c.reconcile({kind:'unavailable'}); c.start(); c.admitSnapshot(snapshot('supported-runtime'),now,10000); request(); c.stop(); c.stop();
  assert.deepEqual(counts,{acquire:1,release:1,patch:1,unpatch:1,warn:0,retire:1});
});

test('supported first admission preserves unknown protection, normal absence release and reacquisition',()=>{
  const {coordinator:c,counts}=setup();
  c.admitSnapshot(snapshot('supported-runtime'),now,10000);
  c.admitSnapshot(snapshot(),now,10000);
  assert.equal(c.reconcile({kind:'unavailable'}).blocking,true);
  assert.equal(c.reconcile(absent).blocking,false);
  assert.equal(c.reconcile({kind:'stale'}).blocking,true);
  assert.equal(counts.acquire,2); assert.equal(counts.release,1); assert.equal(counts.retire,0);
  c.stop();
});

test('missing, malformed, stale and even one millisecond future admission never releases',()=>{
  const {coordinator:c,counts}=setup();
  for(const p of [null,{},snapshot('UNKNOWN'),snapshot('observation-only',1),snapshot('observation-only',-10000),snapshot('observation-only',-10001),
    {...snapshot(),runtime_admission:{schema_version:'1',sleep_interceptor_admission:'observation-only'}},
    {...snapshot(),snapshot:{schema_version:2,observed_at:new Date(now).toISOString()}}]) {
    assert.equal(c.admitSnapshot(p,now,10000).blocking,true);
  }
  assert.equal(counts.release,0); c.stop();
});

test('unresolved native adapter can retire without inventing a lease or safety receipt',()=>{
  const c=new SleepPreflightCoordinator(null,()=>{throw Error('warning');});c.start();
  assert.equal(c.admitSnapshot(snapshot(),now,10000).state,'retired');
  assert.equal(c.status().reason,'observation_only');c.stop();
});

test('delayed and rejected admission retains immediate supported startup protection',async()=>{
  const {coordinator:c,counts,request}=setup();
  let respond;const pending=new Promise(resolve=>{respond=resolve;});
  request();assert.equal(c.status().blocking,true);assert.equal(counts.warn,1);
  await Promise.reject(Error('read failed')).catch(()=>c.reconcile({kind:'unavailable'}));
  request();assert.equal(c.status().blocking,true);
  respond(snapshot('supported-runtime'));c.admitSnapshot(await pending,now,10000);
  assert.equal(c.status().blocking,true);c.stop();
});

test('own-data validation never invokes accessor or trusts inherited admission/snapshot fields',()=>{
  const {coordinator:c,counts}=setup(); let reads=0;
  const getter=()=>{reads++;throw Error('must not read');};
  const a=snapshot();Object.defineProperty(a,'runtime_admission',{get:getter});
  const b=snapshot();Object.defineProperty(b.runtime_admission,'schema_version',{get:getter});
  const d=snapshot();Object.defineProperty(d.snapshot,'observed_at',{get:getter});
  for(const p of [a,b,d,Object.create(snapshot()),{...snapshot(),runtime_admission:Object.create(snapshot().runtime_admission)}]) c.admitSnapshot(p,now,10000);
  assert.equal(reads,0);assert.equal(counts.release,0);c.stop();
});

test('terminal retirement precedes reentrant unpatch and release callbacks',()=>{
  const reenter=(c,saved)=>{saved();c.reconcile({kind:'unavailable'});c.start();c.stop();};
  const {coordinator:c,counts}=setup({unpatch:reenter,release:reenter});
  c.admitSnapshot(snapshot(),now,10000);
  assert.deepEqual(counts,{acquire:1,release:1,patch:1,unpatch:1,warn:0,retire:1});
});

test('throwing modal retirement and unpatch never prevent native release; uncertainty stays visible',()=>{
  const {coordinator:c,counts,request}=setup({retire:()=>{throw Error('modal');},unpatch:()=>{throw Error('unpatch');}});
  const s=c.admitSnapshot(snapshot(),now,10000);request();c.stop();
  assert.equal(s.state,'unavailable');assert.match(s.error,/modal|unpatch/);assert.equal(counts.release,1);assert.equal(counts.unpatch,1);assert.equal(counts.warn,0);
});

test('throwing native release is unknown blocking, not successful retirement, and is never blindly retried',()=>{
  const {coordinator:c,counts}=setup({release:()=>{throw Error('native release');}});
  const s=c.admitSnapshot(snapshot(),now,10000);
  assert.equal(s.state,'unavailable');assert.equal(s.blocking,null);assert.match(s.error,/native release/);
  c.stop();c.reconcile({kind:'unavailable'});c.admitSnapshot(snapshot(),now,10000);
  assert.equal(counts.release,1);assert.equal(counts.acquire,1);
});

test('disposed pending admission cannot retire, warn, or reacquire a new lifetime',()=>{
  const {coordinator:c,counts,request}=setup();c.stop();c.admitSnapshot(snapshot(),now,10000);request();c.start();
  assert.equal(counts.retire,0);assert.equal(counts.release,1);assert.equal(counts.warn,0);assert.equal(counts.acquire,1);
  const next=setup();assert.equal(next.coordinator.status().blocking,true);next.coordinator.stop();
});
