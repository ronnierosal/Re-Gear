import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
const js = ts.transpileModule(readFileSync(new URL("../src/whole-dock-control-model.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { dockControl, dockIntentControl, dockRequestAbandoned, dockRequestSettled, formatPendingRecord,
  parsePendingRecord, shutdownRequested } = await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));
const idle = { schema_version: 3, game_state: "idle", egpu_link: { state: "up" }, observed_at: new Date().toISOString() };
const fresh = { schema_version: 1, busy: false, safe_to_unplug: false, code: "dock_teardown.no_trial", attachment_token: "a".repeat(64)+":"+"b".repeat(64) };
test("initial disconnect requires supported status and idle detected GPU", () => {
  assert.equal(dockControl(fresh, idle).action, "whole_dock_disconnect");
  for (const status of [null, {}, { ...fresh, schema_version: 2 }, { ...fresh, busy: true }, { ...fresh, safe_to_unplug: true }, { ...fresh, code: "unavailable" }]) assert.equal(dockControl(status, idle).action, null);
  for (const snapshot of [null, {}, { ...idle, game_state: "running" }, { ...idle, game_state: "unknown" }, { ...idle, egpu_link: { state: "down" } }]) assert.equal(dockControl(fresh, snapshot).action, null);
});
test("software down never offers reconnect for any intent or game state", () => {
  const down = { ...fresh, code: "dock_teardown.software_down", software_down: true, ok: true };
  for (const intent of ["disconnect", "disconnect_only", "shutdown"])
    for (const game_state of ["idle", "running", "unknown"])
      for (const egpu_link of [null, {state:"up"}, {state:"down"}]) {
        const view=dockIntentControl(down,{...idle,game_state,egpu_link},intent);
        assert.equal(view.action,null);
        assert.doesNotMatch(view.label,/Reconnect/i);
      }
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
function harness(storage = new Map(), intent = "disconnect", startRequest, initialStatus = fresh) {
  const h = {status:{...initialStatus}, reads:[], calls:[], modals:[], timers:new Map(), failStorage:false, intent, snapshot: {...idle, schema_version:3}};
  let slots=[], index=0, effects=[], cleanups=[], serial=0;
  const useState = value => { const slot=index++; if(!(slot in slots)) slots[slot]=value; return [slots[slot], value=>{slots[slot]=typeof value==='function'?value(slots[slot]):value;}]; };
  const useRef = value => {const slot=index++; if(!(slot in slots)) slots[slot]={current:value}; return slots[slot];};
  const useEffect = fn => {const slot=index++; if(!(slot in slots)){slots[slot]=true;effects.push(fn);}};
  const React={createElement:(type,props,...children)=>({type,props:{...props,children}})};
  const callable = name => (...args) => {
    if(name==='get_egpu_disconnect_status') return h.reads.length ? h.reads.shift() : Promise.resolve(h.status);
    h.calls.push(args);
    return h.execute ? h.execute(args) : Promise.resolve({...fresh,code:'dock_teardown.software_down',software_down:true,ok:true,request_id:args.at(-1)});
  };
  const showModal=(view,_unused,options)=>{
    const record={view,closed:false};h.modals.push(record);
    return {Close(){if(record.closed)return;record.closed=true;}};
  };
  const window={localStorage:{getItem:key=>storage.get(key)??null,setItem(key,value){if(h.failStorage)throw Error('storage denied');storage.set(key,value);},removeItem:key=>storage.delete(key)}};
  const Component = new Function('React','useState','useRef','useEffect','callable','DialogButton','showModal','EgpuConfirmModal','dockIntentControl','dockRequestAbandoned','dockRequestSettled','formatPendingRecord','parsePendingRecord','window','crypto','setTimeout','clearTimeout', componentJs+'\nreturn WholeDockControl;')(
    React,useState,useRef,useEffect,callable,'button',showModal,'confirm',dockIntentControl,dockRequestAbandoned,dockRequestSettled,formatPendingRecord,parsePendingRecord,window,
    {randomUUID:()=> '12345678-1234-1234-1234-123456789abc'},
    fn=>{h.timers.set(++serial,fn);return serial;},id=>h.timers.delete(id));
  h.render=()=>{index=0;h.tree=Component({intent:h.intent,readCurrentSnapshot:()=>h.snapshot,startRequest});for(const fn of effects.splice(0))cleanups.push(fn());return h.tree;};
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

test('software-down component has no reconnect confirmation or dispatch on click, poll or remount',async()=>{
  for(const intent of ['disconnect','disconnect_only','shutdown']){
    const down={...fresh,code:'dock_teardown.software_down',software_down:true,ok:true};
    for(const direct of [false,true]){
      for(let cycle=0;cycle<2;cycle++){
        let consumed=false;
        const start=direct?()=>{if(consumed)return false;consumed=true;return true;}:undefined;
        const h=harness(new Map(),intent,start,down);
        await settle();h.poll();await settle();
        if(!direct){
          const button=h.button();assert.equal(button.props.disabled,true);
          assert.doesNotMatch(String(button.props.children[0]),/reconnect/i);
          button.props.onClick();await settle();
        }
        assert.equal(h.modals.length,0);assert.equal(h.calls.length,0);h.unmount();
      }
    }
  }
});

const oneActivation=()=>{let consumed=false;return ()=>{if(consumed)return false;consumed=true;return true;};};
test('explicit one-press activation submits once with no second confirmation or start button',async()=>{
  const activation=oneActivation(), storage=new Map();
  const h=harness(storage,'disconnect_only',activation);await settle();
  assert.equal(h.calls.length,1);assert.equal(h.calls[0][3],'whole_dock_disconnect');
  assert.equal(h.modals.length,0);assert.equal(h.button(),undefined);
  h.poll();await settle();assert.equal(h.calls.length,1);h.unmount();
  const remount=harness(storage,'disconnect_only',activation);await settle();
  assert.equal(remount.calls.length,0);remount.unmount();
});
test('one-press refuses changed attachment and does not retry a later poll',async()=>{
  const h=harness(new Map(),'disconnect_only',oneActivation());
  h.status={...fresh,attachment_token:'c'.repeat(64)+':'+ 'd'.repeat(64)};
  await settle();assert.equal(h.calls.length,0);
  h.poll();await settle();assert.equal(h.calls.length,0);h.unmount();
});
test('one-press recovering a pending request never submits another operation',async()=>{
  const h=harness(new Map([['regear.whole-dock.pending-request','disconnect_only:previous']]),'disconnect_only',oneActivation());
  await settle();assert.equal(h.calls.length,0);assert.equal(h.modals.length,0);h.unmount();
});
test('one-press failure retains correlation and never retries automatically',async()=>{
  const h=harness(new Map(),'disconnect_only',oneActivation());
  h.execute=async()=>{throw Error('interrupted');};
  await settle();assert.equal(h.calls.length,1);assert.equal(h.storage.size,1);
  h.poll();await settle();assert.equal(h.calls.length,1);h.unmount();
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
  reopened.status={...reopened.status,request_id:parsePendingRecord([...storage.values()][0]).request};reopened.poll();await settle();
  assert.equal(storage.size,0);assert.equal(reopened.button().props.disabled,false);reopened.unmount();
});
test('component unmount during confirmation freshness read never dispatches',async()=>{
  const h=harness();await settle();h.click();const pending=deferred();h.reads.push(pending.promise);
  h.modals.at(-1).view.props.onOK();h.unmount();pending.resolve(fresh);await settle();assert.equal(h.calls.length,0);
});
test('component older poll cannot overwrite newer completed command',async()=>{
  const h=harness();await settle();const old=deferred();h.reads.push(old.promise);h.poll();
  h.click();h.modals.at(-1).view.props.onOK();await settle();assert.equal(h.calls.length,1);
  old.resolve(fresh);await settle();assert.equal(h.button().props.children[0],'Software disconnect verified');
  assert.equal(h.button().props.disabled,true);h.unmount();
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
  for (const invalid of [{...snapshot,schema_version:undefined},{...snapshot,schema_version:2},{...snapshot,game_state:"running"},
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
  const request=parsePendingRecord([...storage.values()][0]).request;
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
  for(const intent of ["sleep_connected","bad",null,{},false]) {
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
    "already_consumed","disconnect_unverified","invalid_intent","boot_unverified","busy","sleep_unverified",
    "request_action_changed"]) {
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

test("disconnect-only intent never offers reconnect or power actions",()=>{
  assert.equal(dockIntentControl(fresh,idle,"disconnect_only").action,"whole_dock_disconnect");
  const down={...fresh,code:"dock_teardown.software_down",software_down:true,ok:true};
  assert.equal(dockIntentControl(down,idle,"disconnect_only").action,null);
  assert.equal(dockIntentControl(down,idle,"disconnect_only").label,"Software disconnect verified");
  assert.match(dockIntentControl(down,idle,"disconnect_only").message,/not permission to unplug/);
  assert.equal(dockIntentControl({...down,ok:false},idle,"disconnect_only").action,null);
  assert.equal(dockIntentControl(shutdownAccepted("request"),idle,"disconnect_only").action,null);
  assert.equal(dockIntentControl(down,idle,"disconnect").action,null);
  for(const snapshot of [{...idle,schema_version:2},{...idle,observed_at:new Date(Date.now()-10000).toISOString()},
    {...idle,game_state:"running"}]) assert.equal(dockIntentControl(fresh,snapshot,"disconnect_only").action,null);
});
test("confirmed disconnect-only submits once then stays complete across reload",async()=>{
  const h=harness(new Map(),"disconnect_only");await settle();
  h.execute=args=>Promise.resolve({...fresh,code:"dock_teardown.software_down",software_down:true,ok:true,request_id:args.at(-1)});
  h.click();const ok=h.modals.at(-1).view.props.onOK;ok();ok();await settle();
  assert.equal(h.calls.length,1);assert.equal(h.calls[0][3],"whole_dock_disconnect");
  assert.equal(h.button().props.disabled,true);assert.equal(h.button().props.children[0],"Software disconnect verified");
  const status={...fresh,code:"dock_teardown.software_down",software_down:true,ok:true};h.unmount();
  const reopened=harness(new Map(),"disconnect_only");reopened.status=status;await settle();reopened.poll();await settle();
  assert.equal(reopened.button().props.disabled,true);assert.equal(reopened.calls.length,0);reopened.unmount();
});
test("disconnect-only malformed completion remains pending in another mode",async()=>{
  const storage=new Map(),h=harness(storage,"disconnect_only");await settle();
  h.execute=args=>Promise.resolve({...fresh,code:"dock_teardown.software_down",software_down:true,ok:false,request_id:args.at(-1)});
  h.click();h.modals.at(-1).view.props.onOK();await settle();assert.equal(storage.size,1);h.unmount();
  const request=parsePendingRecord([...storage.values()][0]).request;const next=harness(storage);
  next.status={...fresh,code:"dock_teardown.software_down",software_down:true,ok:false,request_id:request};await settle();next.poll();await settle();
  assert.equal(next.button().props.disabled,true);assert.equal(storage.size,1);assert.equal(next.calls.length,0);next.unmount();
});

test("disconnect-only cancellation and changed attachment never dispatch",async()=>{
  const h=harness(new Map(),"disconnect_only");await settle();h.click();h.modals.at(-1).view.props.onCancel();
  assert.equal(h.calls.length,0);h.click();h.status={...fresh,attachment_token:'c'.repeat(64)+':'+ 'd'.repeat(64)};
  h.modals.at(-1).view.props.onOK();await settle();assert.equal(h.calls.length,0);h.unmount();
});

// ---------------------------------------------------------------------------
// A pending record whose answer can never arrive
//
// Freeing the dock restarts Gaming Mode, which destroys the panel waiting on
// the reply. Its record outlives the answer, and correlation alone can never
// retire it: a backend that restarted too reports no_trial with no request id.
// Before this the control stayed disabled for the life of the install.
// ---------------------------------------------------------------------------

test('a pending record is read back whatever build wrote it', () => {
  assert.deepEqual(parsePendingRecord('v2:shutdown:panel-a:req-1'),
    { intent: 'shutdown', request: 'req-1', panel: 'panel-a' });
  // Older forms carry no panel, which is what makes them recognisably not this
  // panel's -- exactly the record a restart leaves behind.
  assert.deepEqual(parsePendingRecord('shutdown:req-1'),
    { intent: 'shutdown', request: 'req-1', panel: '' });
  assert.deepEqual(parsePendingRecord('disconnect_only:req-1'),
    { intent: 'disconnect_only', request: 'req-1', panel: '' });
  assert.deepEqual(parsePendingRecord('req-1'),
    { intent: 'disconnect', request: 'req-1', panel: '' });
  for (const junk of [null, undefined, '', 'v2:shutdown:panel-a', 'v2:shutdown:panel-a:'])
    assert.equal(parsePendingRecord(junk), null);
  const written = formatPendingRecord('disconnect_only', 'panel-b', 'req-2');
  assert.deepEqual(parsePendingRecord(written),
    { intent: 'disconnect_only', request: 'req-2', panel: 'panel-b' });
});

test('an idle backend retires a record left by a panel that did not survive', () => {
  const idleBackend = { ...fresh, in_flight: false, request_id: 'someone-else' };
  for (const raw of ['old-request', 'shutdown:old-request', 'v2:disconnect:dead-panel:old-request'])
    assert.equal(dockRequestAbandoned(idleBackend, parsePendingRecord(raw), 'live-panel'), true);
});

test('a record this panel is still waiting on is never retired', () => {
  // The race the panel identity closes: a poll landing between writing the
  // record and the backend marking itself busy reads an idle backend, and
  // retiring on that would drop the guard on a request that is still live.
  const idleBackend = { ...fresh, in_flight: false, request_id: 'someone-else' };
  const mine = parsePendingRecord(formatPendingRecord('disconnect', 'live-panel', 'req'));
  assert.equal(dockRequestAbandoned(idleBackend, mine, 'live-panel'), false);
});

test('nothing is retired while the backend says a worker is running', () => {
  // Mid-teardown the operation really is outstanding; waiting is the only safe
  // answer and a second dispatch would race it.
  const record = parsePendingRecord('v2:disconnect:dead-panel:old-request');
  assert.equal(dockRequestAbandoned({ ...fresh, in_flight: true, busy: true }, record, 'live'), false);
  assert.equal(dockRequestAbandoned({ ...fresh, in_flight: true }, record, 'live'), false);
});

test('a backend too old to report in_flight retires nothing', () => {
  // Fail closed: absence of the assertion is not the assertion.
  const record = parsePendingRecord('v2:disconnect:dead-panel:old-request');
  assert.equal(dockRequestAbandoned({ ...fresh, request_id: 'other' }, record, 'live'), false);
  assert.equal(dockRequestAbandoned({ ...fresh, in_flight: undefined }, record, 'live'), false);
  assert.equal(dockRequestAbandoned(null, record, 'live'), false);
  assert.equal(dockRequestAbandoned({ ...fresh, in_flight: false }, null, 'live'), false);
});

test('retiring never depends on, or implies, permission to unplug', () => {
  const record = parsePendingRecord('v2:disconnect:dead-panel:old-request');
  assert.equal(dockRequestAbandoned({ ...fresh, in_flight: false, safe_to_unplug: true }, record, 'live'), false);
  assert.equal(dockRequestAbandoned({ ...fresh, in_flight: false, busy: true }, record, 'live'), false);
  assert.equal(dockRequestAbandoned({ ...fresh, in_flight: false, schema_version: 2 }, record, 'live'), false);
});

test('a correlated reply still settles without being called abandoned', () => {
  // The ordinary path is unchanged: the answer arrived, for this request.
  const done = { ...fresh, in_flight: false, code: 'dock_teardown.software_down',
    software_down: true, ok: true, request_id: 'req' };
  assert.equal(dockRequestSettled(done, 'req', 'disconnect_only'), true);
  const mine = parsePendingRecord(formatPendingRecord('disconnect_only', 'live', 'req'));
  assert.equal(dockRequestAbandoned(done, mine, 'live'), false);
});

test('component stops waiting on an abandoned record and says the result is unconfirmed', async () => {
  // End to end over the component: the record the previous panel left, an idle
  // backend, and one poll. The control must become usable again and must not
  // imply the disconnect happened.
  const storage = new Map([['regear.whole-dock.pending-request', 'v2:disconnect:dead-panel:old-request']]);
  const h = harness(storage);
  h.status = { ...fresh, in_flight: false, request_id: 'someone-else' };
  await settle();
  assert.equal(h.button().props.disabled, true, 'starts disabled by the inherited record');
  h.poll(); await settle();
  assert.equal(storage.size, 0, 'the record is retired');
  assert.equal(h.button().props.disabled, false, 'the control is usable again');
  assert.equal(h.calls.length, 0, 'retiring dispatches nothing');
  const text = JSON.stringify(h.tree);
  assert.match(text, /could not confirm how the previous request ended/i);
  assert.match(text, /Keep the cable connected/i);
  assert.doesNotMatch(text, /safe to unplug|you can unplug/i);
  h.unmount();
});

test("component keeps waiting on the record it wrote itself", async () => {
  // Same idle backend, but the record belongs to this panel: the reply is still
  // coming and the guard must hold.
  const storage = new Map();
  const h = harness(storage);
  await settle();
  h.execute = () => new Promise(() => {});
  h.click(); h.modals.at(-1).view.props.onOK(); await settle();
  assert.equal(storage.size, 1);
  h.status = { ...fresh, in_flight: false, request_id: 'someone-else' };
  h.poll(); await settle();
  assert.equal(storage.size, 1, 'this panel is still waiting on its own request');
  assert.equal(h.button().props.disabled, true);
  h.unmount();
});
