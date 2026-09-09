import assert from "node:assert/strict";
import test from "node:test";
import { performanceState, acceptResponse, wattsValue, fpsTile } from "../src/quick-access/performance-state.ts";
const status = (over = {}) => ({ enabled: true, can_enable: true, ready: true, current_watts: 15,
  recovery_required: false, auto_tdp_available: true, ...over });
const auto = (over = {}) => ({ can_start: true, running: false, stopping: false, enabled: false, ...over });

test("absent evidence stays unknown and offers module explanation", () => {
  const state = performanceState({status:null});
  assert.equal(state.active,false); assert.equal(state.action,"open");
  assert.equal(state.configuredWatts,null); assert.match(state.reason,/not yet observed/);
});
test("manual writer enabled never means the Auto loop is running", () => {
  for (const autoStatus of [null, auto()]) {
    const state = performanceState({status:status(),autoStatus,configured:true});
    assert.equal(state.active,false); assert.equal(state.action,"open");
  }
});
test("Stop survives absent manual evidence or withdrawn start permission", () => {
  for (const manual of [null,status({can_enable:false,auto_tdp_available:false})]) {
    const state=performanceState({status:manual,autoStatus:auto({running:true,can_start:false}),busy:true});
    assert.equal(state.active,true); assert.equal(state.action,"stop");
  }
});
test("a stopping loop is still active but does not issue duplicate Stop", () => {
  assert.equal(performanceState({status:status(),autoStatus:auto({running:true,stopping:true})}).action,"none");
  assert.equal(performanceState({status:status(),autoStatus:auto({running:true}),stopping:true}).action,"none");
});
test("compact tiles always Configure rather than guessing a start", () => {
  for (const can_enable of [true,false]) for (const can_start of [true,false]) for (const configured of [true,false]) {
    assert.equal(performanceState({status:status({can_enable}),autoStatus:auto({can_start}),configured}).action,"open");
  }
});
test("recovery is explained and configured watts remain a limit", () => {
  const state=performanceState({status:status({recovery_required:true}),autoStatus:auto()});
  assert.match(state.reason,/recovery/); assert.equal(state.configuredWatts,15); assert.equal(state.configuredIsLimit,true);
});
test("ordinary busy requests prevent configure actions while Stop can preempt", () => {
  assert.equal(performanceState({status:status(),autoStatus:auto(),busy:true}).action,"none");
});
test("unknown watts and unsupported FPS invent no values", () => {
  assert.deepEqual(wattsValue(null),{text:"Unknown",known:false});
  assert.deepEqual(wattsValue(NaN),{text:"Unknown",known:false});
  assert.equal(wattsValue(14.6).text,"15 W");
  assert.equal(fpsTile().available,false); assert.doesNotMatch(fpsTile().value.text,/\d/);
});
test("only current response generations are accepted", () => {
  assert.equal(acceptResponse(4,4),true); assert.equal(acceptResponse(3,4),false);
});
