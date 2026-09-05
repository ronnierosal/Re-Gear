import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import ts from "typescript";
const js = ts.transpileModule(readFileSync(new URL("../src/connection-live-status.ts", import.meta.url), "utf8"), {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {connectionLiveStatus: status,createLiveStatusStore} = await import("data:text/javascript;base64,"+Buffer.from(js).toString("base64"));
const sample = () => ({snapshot:{observed_at:new Date().toISOString(),game_state:"idle"},inference:{mode:"portable"},connection_readiness:{stage:"ready_idle",window_age_ms:90000,checks_age_ms:0,checks:{gpu:true,link:true,hdmi:true,audio:true,session:true,idle:true}}});

test("GPU name is fresh unambiguous presentation only, with unknown fallback", () => {
 const p=sample(); const gpu={role:"external",present:true,confidence:"verified",model_name:"Example GPU 9000"};
 p.snapshot.gpus=[gpu];
 assert.equal(status(p,{enabled:false},"journal.idle").gpuName,"Example GPU 9000");
 gpu.model_name="Another GPU 500";
 assert.equal(status(p,{enabled:false},"journal.idle").gpuName,"Another GPU 500");
 const permission=status(p,{enabled:false},"journal.idle").canSwitch;
 for(const name of [undefined,null,42,"","unknown","x".repeat(129),"GPU\u0000name","GPU\u202ename"]) {
  gpu.model_name=name; const result=status(p,{enabled:false},"journal.idle");
  assert.equal(result.gpuName,undefined); assert.equal(result.canSwitch,permission);
 }
 gpu.model_name="Example GPU 9000";
 p.snapshot.gpus=[gpu,{...gpu}]; assert.equal(status(p,null,"journal.idle").gpuName,undefined);
 p.snapshot.gpus=[gpu]; gpu.confidence="unknown"; assert.equal(status(p,null,"journal.idle").gpuName,undefined);
 gpu.confidence="verified"; assert.equal(status(p,null,"journal.idle",true).gpuName,undefined);
 p.connection_readiness.stage="disconnected"; assert.equal(status(p,null,"journal.idle").gpuName,undefined);
});

test("timeout is waiting at two minutes and attention at five without switch permission",()=>{
 const p=sample();p.connection_readiness.stage="timed_out";p.connection_readiness.checks.gpu=false;
 for(const age of [120000,299999,300000,480000]){
  p.connection_readiness.window_age_ms=age;
  const s=status(p,{enabled:false},"journal.idle");
  assert.equal(s.title,age>=300000 ? "Connection hasn’t completed—troubleshooting needed" : "Taking longer than expected—still checking");
  assert.equal(s.rows[0].state,"waiting");assert.equal(s.canSwitch,false);assert.equal(s.phase,"checking");
 }
 p.connection_readiness.checks.gpu=true;
 assert.equal(status(p,{enabled:false},"journal.idle").canSwitch,false);
});
test("real link, game and acknowledgement blockers take priority over elapsed waiting",()=>{
 const p=sample();p.connection_readiness.window_age_ms=400000;p.connection_readiness.checks.link=false;
 for(const stage of ["link_training_failed","action_required"]){
  p.connection_readiness.stage=stage;const s=status(p,{enabled:false},"journal.idle");
  assert.equal(s.rows[1].state,"blocked");assert.match(s.title,/needs attention/);assert.equal(s.canSwitch,false);
 }
 p.connection_readiness.stage="timed_out";p.snapshot.game_state="running";
 assert.equal(status(p,null,"journal.idle").title,"Close the game to continue");
 p.snapshot.game_state="idle";
 const s=status(p,null,"journal.result_required");
 assert.match(s.title,/acknowledgement/);assert.equal(s.rows.at(-1).state,"blocked");
});
test("late recovery replaces attention and stale or failed evidence cannot retain success",()=>{
 const p=sample();p.connection_readiness.stage="timed_out";p.connection_readiness.window_age_ms=400000;
 assert.match(status(p,null,"journal.idle").title,/troubleshooting/);
 p.connection_readiness.stage="stabilizing";p.connection_readiness.window_age_ms=1000;
 assert.equal(status(p,null,"journal.idle").title,"Checking connection stability");
 p.connection_readiness.stage="ready_idle";
 assert.equal(status(p,{enabled:true,stage:"switching"},"journal.idle").phase,"switching");
 p.inference.mode="docked_egpu";
 assert.equal(status(p,{stage:"docked"},"journal.idle").phase,"complete");
 for(const failed of [true,false]){
  if(!failed)p.connection_readiness.checks_age_ms=15000;
  const s=status(p,{stage:"docked"},"journal.idle",failed);
  assert.equal(s.phase,"checking");assert.equal(s.canSwitch,false);assert.ok(s.rows.every(r=>r.state==="waiting"));
  assert.equal(s.title,"Waiting for a fresh status update");
 }
});
test("all independent checks and clear journal permit manual switch only with automatic off",()=>{
 const p=sample(); assert.equal(status(p,{enabled:false},"journal.idle").canSwitch,true);
 assert.equal(status(p,{enabled:true},"journal.idle").canSwitch,false);
 assert.equal(status(p,null,"journal.idle").canSwitch,false);
 for(const key of Object.keys(p.connection_readiness.checks)){const q=sample();q.connection_readiness.checks[key]=false;assert.equal(status(q,{enabled:false},"journal.idle").canSwitch,false);}
 assert.equal(status(p,{enabled:false},"journal.result_required").canSwitch,false);
});
test("stale and failed evidence cannot show green or authorize a switch",()=>{
 for(const mutation of [p=>p.connection_readiness.checks_age_ms=16000,p=>p.snapshot.observed_at="invalid",p=>p.snapshot.observed_at=new Date(Date.now()-16000).toISOString()]){
 const p=sample();mutation(p);const s=status(p,{enabled:false},"journal.idle");assert.equal(s.canSwitch,false);assert.ok(s.rows.every(r=>r.state==="waiting"));}
 assert.ok(status(sample(),null,"journal.idle",true).rows.every(r=>r.state==="waiting"));
});
test("waiting, timeout and switching are distinct and backend age is displayed",()=>{
 const p=sample();p.connection_readiness.stage="waiting_for_pci";p.connection_readiness.checks.gpu=false;
 let s=status(p,null,"journal.idle");assert.match(s.title,/eGPU detection/);assert.equal(s.seconds,90);assert.equal(s.rows[0].state,"waiting");
 p.connection_readiness.stage="timed_out";s=status(p,null,"journal.idle");assert.equal(s.rows[0].state,"waiting");
 assert.match(status(p,{stage:"switching"},"journal.idle").title,/checking picture and audio/);
});
test("live store publishes and unsubscribes without accumulating listeners",()=>{
 const store=createLiveStatusStore();let count=0;const off=store.subscribe(()=>count++);store.set(status(sample(),null,"journal.idle"));assert.equal(count,1);off();store.set(status(null,null,undefined));assert.equal(count,1);
});

test("a newer running-game snapshot overrides an earlier idle observation",()=>{
 const p=sample();p.snapshot.game_state="running";const s=status(p,{enabled:false},"journal.idle");
 assert.equal(s.canSwitch,false);assert.equal(s.rows.find(r=>r.label==="No game running").state,"blocked");
 p.snapshot.game_state="unknown";assert.equal(status(p,{enabled:false},"journal.idle").canSwitch,false);
});
test("completion presentation requires fresh docked backend and display evidence",()=>{
 const p=sample();
 assert.equal(status(p,{stage:"switching"},"journal.idle").phase,"switching");
 assert.equal(status(p,{stage:"docked"},"journal.idle").phase,"checking");
 p.inference.mode="docked_egpu";
 assert.equal(status(p,{stage:"docked"},"journal.idle").phase,"complete");
 p.snapshot.observed_at=new Date(Date.now()-16000).toISOString();
 assert.equal(status(p,{stage:"docked"},"journal.idle").phase,"checking");
});
