import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
const js = ts.transpileModule(readFileSync(new URL("../src/whole-dock-control-model.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { dockControl, dockIntentControl, dockRequestSettled, shutdownRequested } = await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));
const idle = { game_state: "idle", egpu_link: { state: "up" }, observed_at: new Date().toISOString() };
const fresh = { schema_version: 1, busy: false, safe_to_unplug: false, code: "dock_teardown.no_trial", attachment_token: "a".repeat(64)+":"+"b".repeat(64) };
test("initial disconnect requires supported status and idle detected GPU", () => {
  assert.equal(dockControl(fresh, idle).action, "whole_dock_disconnect");
  for (const status of [null, {}, { ...fresh, schema_version: 2 }, { ...fresh, busy: true }, { ...fresh, safe_to_unplug: true }, { ...fresh, code: "unavailable" }]) assert.equal(dockControl(status, idle).action, null);
  for (const snapshot of [null, {}, { ...idle, game_state: "running" }, { ...idle, game_state: "unknown" }, { ...idle, egpu_link: { state: "down" } }]) assert.equal(dockControl(fresh, snapshot).action, null);
});
test("only verified software down offers reconnect, without GPU-present requirement", () => {
  const down = { ...fresh, code: "dock_teardown.software_down", software_down: true };
  assert.equal(dockControl(down, { ...idle, egpu_link: null }).action, "whole_dock_reconnect");
  assert.equal(dockControl({ ...down, software_down: "true" }, idle).action, null);
  assert.equal(dockControl(down, { game_state: "running" }).action, null);
  assert.match(dockControl(down, idle).message, /Keep the cable connected/);
});
test("partial and interrupted results cannot enable another write", () => {
  for (const code of ["dock_teardown.trial_unresolved", "dock_reconnect.timeout", "dock_reconnect.unresolved", "dock_teardown.trial_running"]) assert.equal(dockControl({ ...fresh, code }, idle).action, null);
});
test("stale, future and missing observations fail closed", () => {
  for (const observed_at of [undefined, "bad", new Date(Date.now()-20000).toISOString(), new Date(Date.now()+20000).toISOString()]) assert.equal(dockControl(fresh, {...idle, observed_at}).action, null);
});
test("reconnected result requires exact verified fields", () => {
  const restored = { ...fresh, code: "dock_reconnect.software_reconnected", software_reconnected: true, ok: true };
  assert.equal(dockControl(restored, idle).action, "whole_dock_disconnect");
  assert.equal(dockControl({ ...restored, ok: false }, idle).action, null);
  assert.match(dockControl(restored, idle).message, /picture, audio and controls/);
});

// Execute the actual TSX with deterministic hook slots and Decky boundaries.
// This verifies event behavior, not source-string patterns or native rendering.
const componentJs = ts.transpileModule(readFileSync(new URL("../src/whole-dock-control.tsx", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022, jsx: ts.JsxEmit.React },
}).outputText.replace(/^import .*;\r?$/gm, "").replace(/export function WholeDockControl/, "function WholeDockControl");
const deferred = () => { let resolve, reject; const promise = new Promise((yes,no) => {resolve=yes;reject=no;}); return {promise,resolve,reject}; };
const settle = async () => { for(let n=0;n<12;n++) await Promise.resolve(); };
function harness(storage = new Map(), intent = "disconnect") {
  const h = {status:{...fresh}, reads:[], calls:[], modals:[], timers:new Map(), failStorage:false, intent, snapshot: {...idle, schema_version:3}};
  let slots=[], index=0, effects=[], cleanups=[], serial=0;
  const useState = value => { const slot=index++; if(!(slot in slots)) slots[slot]=value; return [slots[slot], value=>{slots[slot]=typeof value==='function'?value(slots[slot]):value;}]; };
  const useRef = value => {const slot=index++; if(!(slot in slots)) slots[slot]={current:value}; return slots[slot];};
  const useEffect = fn => {const slot=index++; if(!(slot in slots)){slots[slot]=true;effects.push(fn);}};
  const React={createElement:(type,props,...children)=>({type,props:{...props,children}})};
  const callable = name => (...args) => {
    if(name==='get_egpu_disconnect_status') return h.reads.length ? h.reads.shift() : Promise.resolve(h.status);
    h.calls.push(args);
    return h.execute ? h.execute(args) : Promise.resolve({...fresh,code:'dock_teardown.software_down',software_down:true,request_id:args.at(-1)});
  };
  const showModal=(view,_unused,options)=>{
    const record={view,closed:false};h.modals.push(record);
    return {Close(){if(record.closed)return;record.closed=true;}};
  };
  const window={localStorage:{getItem:key=>storage.get(key)??null,setItem(key,value){if(h.failStorage)throw Error('storage denied');storage.set(key,value);},removeItem:key=>storage.delete(key)}};
  const Component = new Function('React','useState','useRef','useEffect','callable','DialogButton','showModal','EgpuConfirmModal','dockIntentControl','dockRequestSettled','window','crypto','setTimeout','clearTimeout', componentJs+'\nreturn WholeDockControl;')(
    React,useState,useRef,useEffect,callable,'button',showModal,'confirm',dockIntentControl,dockRequestSettled,window,
    {randomUUID:()=> '12345678-1234-1234-1234-123456789abc'},
    fn=>{h.timers.set(++serial,fn);return serial;},id=>h.timers.delete(id));
  h.render=()=>{index=0;h.tree=Component({intent:h.intent,readCurrentSnapshot:()=>h.snapshot});for(const fn of effects.splice(0))cleanups.push(fn());return h.tree;};
  h.button=()=>h.render().props.children.find(child=>child?.type==='button');
  h.click=()=>{const button=h.button();assert.equal(button.props.disabled,false);button.props.onClick();};
  h.poll=()=>{const [id,fn]=h.timers.entries().next().value;h.timers.delete(id);fn();};
  h.unmount=()=>{for(const cleanup of cleanups.splice(0))cleanup?.();};
  h.storage=storage;h.render();return h;
}

test('component mount and canceled confirmation never mutate', async()=>{
  const h=harness();await settle();assert.equal(h.calls.length,0);
  h.click();h.modals.at(-1).view.props.onCancel();await settle();
  assert.equal(h.calls.length,0);assert.equal(h.button().props.disabled,false);h.unmount();
});
test('component same-tick double confirmation submits exactly once',async()=>{
  const h=harness();await settle();h.click();const ok=h.modals.at(-1).view.props.onOK;
  ok();ok();await settle();assert.equal(h.calls.length,1);assert.equal(h.calls[0][3],'whole_dock_disconnect');h.unmount();
});
test('component attachment replacement while modal open cancels dispatch',async()=>{
  const h=harness();await settle();h.click();h.status={...fresh,attachment_token:'c'.repeat(64)+':'+ 'd'.repeat(64)};
  h.modals.at(-1).view.props.onOK();await settle();assert.equal(h.calls.length,0);h.unmount();
});
test('component persistent request storage failure prevents RPC',async()=>{
  const h=harness();await settle();h.click();h.failStorage=true;
  h.modals.at(-1).view.props.onOK();await settle();assert.equal(h.calls.length,0);h.unmount();
});
test('component interrupted request survives remount and stale prior terminal status',async()=>{
  const storage=new Map();const h=harness(storage);await settle();
  h.execute=()=>Promise.reject(Error('connection lost'));h.click();h.modals.at(-1).view.props.onOK();await settle();
  assert.equal(h.calls.length,1);assert.equal(storage.size,1);h.unmount();
  const reopened=harness(storage);reopened.status={...fresh,code:'dock_reconnect.software_reconnected',software_reconnected:true,ok:true,request_id:'old-request'};
  await settle();reopened.poll();await settle();assert.equal(reopened.button().props.disabled,true);assert.equal(storage.size,1);assert.equal(reopened.calls.length,0);
  reopened.status={...reopened.status,request_id:[...storage.values()][0]};reopened.poll();await settle();
  assert.equal(storage.size,0);assert.equal(reopened.button().props.disabled,false);reopened.unmount();
});
test('component unmount during confirmation freshness read never dispatches',async()=>{
  const h=harness();await settle();h.click();const pending=deferred();h.reads.push(pending.promise);
  h.modals.at(-1).view.props.onOK();h.unmount();pending.resolve(fresh);await settle();assert.equal(h.calls.length,0);
});
test('component older poll cannot overwrite newer completed command',async()=>{
  const h=harness();await settle();const old=deferred();h.reads.push(old.promise);h.poll();
  h.click();h.modals.at(-1).view.props.onOK();await settle();assert.equal(h.calls.length,1);
  old.resolve(fresh);await settle();assert.equal(h.button().props.children[0],'Reconnect eGPU');h.unmount();
});
test("known refusal explains cause without enabling another operation", () => {
  const result = dockControl({ ...fresh, code: "dock_teardown.usb_peripherals_or_unknown" }, idle);
  assert.equal(result.action, null);
  assert.match(result.message, /USB accessories or incomplete hub information/);
  assert.match(result.message, /Keep the cable connected/);
  assert.doesNotMatch(dockControl({...fresh, code: "private-path"}, idle).message, /private-path/);
});

test("release refusal and unverified dock completion remain distinct", () => {
  const blocked = dockControl({...fresh, code:"dock_teardown.gpu_release_unverified",
    release_stage:"release_refused", arm_code:"arm_sequence.unapproved_holder"}, idle);
  assert.equal(blocked.action, null);
  assert.match(blocked.message, /Device removal did not start/);
  const incomplete = dockControl({...fresh, code:"dock_teardown.unresolved",
    release_stage:"removed", phase:"dock_teardown"}, idle);
  assert.equal(incomplete.action, null);
  assert.match(incomplete.message, /GPU release completed/);
  assert.match(incomplete.message, /could not be verified/);
});

const shutdownAccepted = request_id => ({ schema_version:1, busy:false, safe_to_unplug:false,
  code:"dock_power.request_accepted_unverified", power_action:"shutdown", power_requested:true, ok:true, request_id });
test("shutdown intent requires live schema3 readiness; capability metadata cannot enable it", () => {
  const snapshot={...idle,schema_version:3};
  assert.equal(dockIntentControl(fresh,snapshot,"shutdown").action,"whole_dock_shutdown");
  for (const invalid of [idle,{...snapshot,schema_version:2},{...snapshot,game_state:"running"},
    {...snapshot,observed_at:new Date(Date.now()-20000).toISOString()},{...snapshot,egpu_link:{state:"down"}}])
    assert.equal(dockIntentControl(fresh,invalid,"shutdown").action,null);
  assert.equal(dockIntentControl({schema_version:1,code:"dock_power.capabilities",authorizes_action:false,
    actions:{shutdown:{implementation:"implemented",actionable:false}}},snapshot,"shutdown").action,null);
  assert.equal(dockIntentControl({...fresh,software_down:true,code:"dock_teardown.software_down"},snapshot,"shutdown").action,null);
});
test("shutdown accepted wording requires exact fields and never offers another action", () => {
  const accepted=shutdownAccepted("request");
  assert.equal(dockIntentControl(accepted,null,"shutdown").label,"Shutdown requested");
  assert.equal(dockIntentControl(accepted,null,"shutdown").action,null);
  for(const [key,value] of Object.entries({schema_version:2,busy:true,safe_to_unplug:true,code:"other",
    power_action:"sleep",power_requested:"true",ok:false})) {
    assert.equal(shutdownRequested({...accepted,[key]:value}),false);
    assert.equal(dockRequestSettled({...accepted,[key]:value},"request","shutdown"),false);
  }
  assert.equal(dockRequestSettled(accepted,"different","shutdown"),false);
  assert.match(dockIntentControl(accepted,null,"shutdown").message,/Completion is not confirmed/);
});
test("shutdown confirmation cancels cleanly and dispatches exact original intent once",async()=>{
  const h=harness(new Map(),"shutdown");await settle();h.click();
  assert.match(h.modals.at(-1).view.props.strDescription,/Save your work/);
  h.modals.at(-1).view.props.onCancel();assert.equal(h.calls.length,0);
  h.execute=args=>Promise.resolve(shutdownAccepted(args.at(-1)));
  h.click();const ok=h.modals.at(-1).view.props.onOK;ok();ok();await settle();
  assert.equal(h.calls.length,1);const args=h.calls[0];
  assert.deepEqual(args.slice(0,6),[true,"","disconnect","whole_dock_shutdown",true,fresh.attachment_token]);
  assert.match(args[6],/^[a-f0-9]{32}$/);assert.equal(h.storage.size,0);
  assert.equal(h.button().props.disabled,true);assert.equal(h.button().props.children[0],"Shutdown requested");h.unmount();
});
test("shutdown refuses changed attachment, changed intent, stale snapshot and unavailable storage",async()=>{
  for(const change of [h=>{h.status={...fresh,attachment_token:'c'.repeat(64)+':'+ 'd'.repeat(64)};},
    h=>{h.intent="disconnect";h.render();},h=>{h.snapshot={...h.snapshot,observed_at:"bad"};},h=>{h.failStorage=true;}]) {
    const h=harness(new Map(),"shutdown");await settle();h.click();change(h);
    h.modals.at(-1).view.props.onOK();await settle();assert.equal(h.calls.length,0);h.unmount();
  }
});
test("shutdown malformed acceptance stays pending across remount in disconnect mode",async()=>{
  const storage=new Map(), h=harness(storage,"shutdown");await settle();
  h.execute=args=>Promise.resolve({...shutdownAccepted(args.at(-1)),power_requested:"true"});
  h.click();h.modals.at(-1).view.props.onOK();await settle();
  assert.equal(h.calls.length,1);assert.equal(storage.size,1);assert.equal(h.button().props.disabled,true);h.unmount();
  const request=[...storage.values()][0].replace(/^shutdown:/,"");
  const next=harness(storage);next.status={...fresh,request_id:request};await settle();next.poll();await settle();
  assert.equal(storage.size,1);assert.equal(next.button().props.disabled,true);assert.equal(next.calls.length,0);
  next.status=shutdownAccepted(request);next.poll();await settle();assert.equal(storage.size,0);next.unmount();
});
test("shutdown unmount or intent change during fresh read never submits",async()=>{
  for(const change of [h=>h.unmount(),h=>{h.intent="disconnect";h.render();}]) {
    const h=harness(new Map(),"shutdown");await settle();h.click();const read=deferred();h.reads.push(read.promise);
    h.modals.at(-1).view.props.onOK();change(h);read.resolve(fresh);await settle();assert.equal(h.calls.length,0);h.unmount();
  }
});
test("shutdown interrupted transport never retries and shared pending guard blocks another mode",async()=>{
  const storage=new Map(), h=harness(storage,"shutdown"), other=harness(storage);await settle();
  other.click();h.execute=()=>Promise.reject(Error("lost"));h.click();h.modals.at(-1).view.props.onOK();await settle();
  other.modals.at(-1).view.props.onOK();await settle();assert.equal(other.calls.length,0);
  assert.equal(h.calls.length,1);assert.equal(storage.size,1);h.unmount();other.unmount();
  const reopened=harness(storage,"shutdown");await settle();assert.equal(reopened.button().props.disabled,true);
  assert.equal(reopened.calls.length,0);reopened.unmount();
});

test("unknown runtime intent fails closed rather than selecting shutdown",()=>{
  for(const intent of ["sleep","bad",null,{},false]) {
    assert.equal(dockIntentControl(fresh,{...idle,schema_version:3},intent).action,null);
    assert.equal(dockRequestSettled(shutdownAccepted("request"),"request",intent),false);
  }
});
test("shutdown wrong request acceptance cannot display a requested result",async()=>{
  const h=harness(new Map(),"shutdown");await settle();h.execute=()=>Promise.resolve(shutdownAccepted("other"));
  h.click();h.modals.at(-1).view.props.onOK();await settle();
  assert.equal(h.button().props.disabled,true);assert.equal(h.storage.size,1);
  assert.equal(h.button().props.children[0],"Checking previous request");h.unmount();
});
test("shutdown refuses all power failure categories without another action",()=>{
  for(const code of ["preflight_changed","intent_not_recorded","request_unverified","unresolved",
    "already_consumed","disconnect_unverified","invalid_intent","boot_unverified","busy","sleep_unverified"]) {
    const status={...fresh,code:"dock_power."+code,ok:false,power_requested:false,power_action:"shutdown",request_id:"request"};
    assert.equal(dockIntentControl(status,{...idle,schema_version:3},"shutdown").action,null);
    assert.equal(dockRequestSettled(status,"request","shutdown"),true);
  }
});

test("malformed or unknown refusal cannot clear shutdown retry guard",()=>{
  const refusal={...fresh,ok:false,request_id:"request"};
  for(const code of ["dock_teardown.no_trial","dock_teardown.unknown_new_code","dock_mutation.malformed"])
    assert.equal(dockRequestSettled({...refusal,code},"request","shutdown"),false);
  assert.equal(dockRequestSettled({...refusal,code:"dock_power.unresolved",power_requested:"false"},"request","shutdown"),false);
});
