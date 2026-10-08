import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
import { sanitizeTdpStatus, tdpControls, manualPresetOptions } from "../src/tdp-ui.ts";
import { sanitizeAutoTdpStatus, validAutoTdpRange } from "../src/auto-tdp-ui.ts";
const source = readFileSync(new URL("../src/quick-access/use-performance.ts",import.meta.url),"utf8");
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}}).outputText
  .replace(/^import[^;]*;/gm,"").replace(/const backend = [^;]*;/,"const backend = {};");
const {PerformanceController}=new Function("sanitizeTdpStatus","tdpControls","sanitizeAutoTdpStatus","validAutoTdpRange","manualPresetOptions",
  code.replace(/export /g,"")+";return {PerformanceController};")(sanitizeTdpStatus,tdpControls,sanitizeAutoTdpStatus,validAutoTdpRange,manualPresetOptions);
const manual={schema_version:1,enabled:true,can_enable:true,ready:true,code:"tdp.ready",current_watts:15,minimum_watts:7,maximum_watts:30,restore_available:true,recovery_required:false,auto_tdp_available:true,last_result:null};
const off={schema_version:1,can_start:true,enabled:false,running:false,stopping:false,code:"auto_tdp.ready",activity_code:null,target_fps:null,minimum_watts:null,maximum_watts:null};
const running={...off,can_start:false,enabled:true,running:true,target_fps:60,minimum_watts:7,maximum_watts:30};
const deferred=()=>{let resolve; const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function fakeClock() {
  let now=0; const timers=new Set();
  return { now:()=>now, schedule(callback,ms) { const timer={at:now+ms,callback};timers.add(timer);return()=>timers.delete(timer); },
    advance(ms,fire=true) { now+=ms; if(fire) for(const timer of [...timers]) if(timer.at<=now) {timers.delete(timer);timer.callback();} },
    count:()=>timers.size };
}
function setup(over={},time=fakeClock()) {
  const calls=[];
  const port=Object.fromEntries(Object.entries({getTdpStatus:manual,getAutoTdpStatus:off,applyTdpLimit:manual,restoreTdpLimit:manual,setTdpEnabled:manual,startAutoTdp:running,stopAutoTdp:off}).map(([key,value])=>[key,async(...args)=>{calls.push([key,...args]);return value;}]));
  Object.assign(port,over);
  return {controller:new PerformanceController(port,time),calls,port,time};
}
test("one visibility read, no hidden reads or writes, remount refreshes",async()=>{
  const {controller:c,calls}=setup();
  await c.refresh(); await c.stop(); assert.equal(calls.length,0);
  c.setVisible(true); await settle(); c.setVisible(true); await settle();
  assert.deepEqual(calls.map(x=>x[0]),["getTdpStatus","getAutoTdpStatus"]);
  c.setVisible(false); assert.equal(c.snapshot.manual,null); assert.equal(c.snapshot.auto,null);
  await c.apply(20); await c.stop(); assert.equal(calls.length,2);
  c.setVisible(true); await settle(); assert.equal(calls.length,4);
});
test("hidden read never repopulates state; reopen queues fresh read after old transport",async()=>{
  const old=deferred();let reads=0;
  const {controller:c}=setup({getTdpStatus:()=>++reads===1?old.promise:Promise.resolve({...manual,current_watts:20})});
  c.setVisible(true); c.setVisible(false); c.setVisible(true);
  old.resolve(manual); await settle();
  assert.equal(reads,2); assert.equal(c.snapshot.manual.current_watts,20);
});
test("Stop preempts a start; stale start cannot revive loop or release write lock early",async()=>{
  const start=deferred(); const {controller:c,calls}=setup({startAutoTdp:()=>start.promise});
  c.setVisible(true);await settle();
  const pending=c.start(60,7,30); await c.stop();
  assert.equal(c.snapshot.auto.running,false); assert.equal(c.snapshot.busy,true);
  await c.apply(20); assert.equal(calls.some(x=>x[0]==="applyTdpLimit"),false);
  start.resolve(running); await pending;
  assert.equal(c.snapshot.auto.running,false); assert.equal(c.snapshot.busy,false);
});
test("manual writes serialize, validate integer bounds, and refresh loop status",async()=>{
  const apply=deferred();const {controller:c,calls}=setup({applyTdpLimit:()=>apply.promise});
  c.setVisible(true);await settle();
  for(const watts of [NaN,0,31,15.5]) await c.apply(watts);
  const pending=c.apply(20); await c.restore(); await c.setEnabled(false);
  assert.equal(calls.some(x=>["restoreTdpLimit","setTdpEnabled"].includes(x[0])),false);
  apply.resolve({...manual,current_watts:20}); await pending;
  assert.equal(c.snapshot.manual.current_watts,20);assert.equal(c.snapshot.auto.running,false);
});
test("recovery, missing permission, invalid range and malformed status fail closed",async()=>{
  for(const payload of [{...manual,recovery_required:true},null]) {
    const {controller:c,calls}=setup({getTdpStatus:async()=>payload});
    c.setVisible(true);await settle();await c.apply(20);await c.start(60,7,30);await c.restore();
    assert.equal(calls.some(x=>["applyTdpLimit","startAutoTdp","restoreTdpLimit"].includes(x[0])),false);
  }
  const {controller:c,calls}=setup({getAutoTdpStatus:async()=>({...off,can_start:false,code:"auto_tdp.game_or_render_unverified"})});
  c.setVisible(true);await settle();await c.start(60,7,30);assert.equal(calls.some(x=>x[0]==="startAutoTdp"),false);
});
test("manual enabled plus loop off stays independently observable; one failed read does not hide Stop",async()=>{
  const {controller:c,port}=setup();c.setVisible(true);await settle();
  assert.equal(c.snapshot.manual.enabled,true);assert.equal(c.snapshot.auto.running,false);
  port.getTdpStatus=async()=>{throw Error("unavailable");};port.getAutoTdpStatus=async()=>running;
  await c.refresh();assert.equal(c.snapshot.manual,null);assert.equal(c.snapshot.auto.running,true);
});
test("unsubscribed unmounted consumer receives no late callbacks",async()=>{
  const old=deferred();const {controller:c}=setup({getTdpStatus:()=>old.promise});
  let renders=0;const unsubscribe=c.subscribe(()=>renders++);c.setVisible(true);unsubscribe();c.setVisible(false);
  const before=renders;old.resolve(manual);await settle();assert.equal(renders,before);assert.equal(c.snapshot.manual,null);
});
test("visible owner refreshes changed limits without a write; hiding cancels timers",async()=>{
  const {controller:c,port,time,calls}=setup(); c.setVisible(true);await settle();
  port.getTdpStatus=async()=>({...manual,current_watts:22});
  time.advance(3000);await settle();assert.equal(c.snapshot.manual.current_watts,22);
  c.setVisible(false);assert.equal(time.count(),0);const before=calls.length;
  time.advance(30000);await settle();assert.equal(calls.length,before);
});
test("stalled refresh expires old readings and a late response cannot renew them",async()=>{
  const delayed=deferred();const {controller:c,port,time}=setup();c.setVisible(true);await settle();
  port.getTdpStatus=()=>delayed.promise;
  time.advance(3000);await settle();assert.equal(c.snapshot.manual.current_watts,15);
  time.advance(7000);assert.equal(c.snapshot.manual,null);assert.equal(c.snapshot.auto,null);
  time.advance(3000);delayed.resolve({...manual,current_watts:22});await settle();
  assert.equal(c.snapshot.manual,null);assert.equal(c.snapshot.auto,null);
  port.getTdpStatus=async()=>({...manual,current_watts:24});
  time.advance(3000);await settle();assert.equal(c.snapshot.manual.current_watts,24);
});
test("expired availability refuses writes even when timer delivery is suspended",async()=>{
  const {controller:c,time,calls}=setup();c.setVisible(true);await settle();
  time.advance(10000,false);
  await c.apply(20);await c.start(60,7,30);await c.restore();await c.setEnabled(true);
  assert.equal(c.snapshot.manual,null);assert.equal(c.snapshot.auto,null);
  assert.deepEqual(calls.map(call=>call[0]),["getTdpStatus","getAutoTdpStatus"]);
});

test("shared controller refuses all manual mutation during running or either stopping state", async () => {
  for (const state of ["running", "auto-stopping", "owner-stopping"]) {
    const { controller: c, calls } = setup(); c.setVisible(true); await settle();
    c.snapshot = { ...c.snapshot, auto: state === "running" ? running : { ...off, stopping: state === "auto-stopping" }, stopping: state === "owner-stopping" };
    await c.apply(20); await c.restore(); await c.setEnabled(false); await c.setEnabled(true);
    assert.deepEqual(calls.map(x => x[0]), ["getTdpStatus", "getAutoTdpStatus"]);
  }
});

const manualWithPresets = () => ({ ...manual, manual_presets: [{ id: "low", watts: 10, admitted: true }, { id: "balanced", watts: 15, admitted: true }, { id: "high", watts: 25, admitted: true }] });
test("shared preset Apply requires the exact current admission and submits only one existing RPC", async () => {
  const { controller: c, calls } = setup({ getTdpStatus: async () => manualWithPresets() });
  c.setVisible(true); await settle(); const current = c.snapshot.manual;
  await c.apply(10, { id: "low", status: current });
  assert.deepEqual(calls.filter(x => !["getTdpStatus", "getAutoTdpStatus"].includes(x[0])), [["applyTdpLimit", 10]]);
  await c.apply(10, { id: "low", status: current });
  assert.equal(calls.filter(x => x[0] === "applyTdpLimit").length, 1, "old selection cannot survive a new result");
});
test("shared preset dispatch rejects false/malformed/changed/stale evidence without blocking ordinary Manual", async () => {
  for (const mode of ["denied", "missing", "invalid", "wrong-watts", "old-status", "expired", "hidden"]) {
    const { controller: c, calls, time } = setup({ getTdpStatus: async () => manualWithPresets() });
    c.setVisible(true); await settle(); const current = c.snapshot.manual;
    let expected = current, watts = 10;
    if (mode === "denied") current.manual_presets[0].admitted = false;
    if (mode === "missing") delete current.manual_presets;
    if (mode === "invalid") current.manual_presets[0].watts = 11;
    if (mode === "wrong-watts") watts = 20;
    if (mode === "old-status") expected = { ...current };
    if (mode === "expired") time.advance(10000, false);
    if (mode === "hidden") c.setVisible(false);
    await c.apply(watts, { id: "low", status: expected });
    assert.equal(calls.some(x => x[0] === "applyTdpLimit"), false, mode);
    if (!["expired", "hidden"].includes(mode)) {
      await c.apply(20); assert.equal(calls.filter(x => x[0] === "applyTdpLimit").length, 1, "ordinary Manual stays available");
    }
  }
});
