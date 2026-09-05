import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import ts from "typescript";
const js = ts.transpileModule(readFileSync(new URL("../src/connection-live-status.ts", import.meta.url), "utf8"), {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {connectionLiveStatus: status,createLiveStatusStore} = await import("data:text/javascript;base64,"+Buffer.from(js).toString("base64"));
const sample = () => ({snapshot:{observed_at:new Date().toISOString(),game_state:"idle"},inference:{mode:"portable"},connection_readiness:{stage:"ready_idle",window_age_ms:90000,checks_age_ms:0,checks:{gpu:true,link:true,hdmi:true,audio:true,session:true,idle:true}}});
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
 let s=status(p,null,"journal.idle");assert.match(s.title,/G1 detection/);assert.equal(s.seconds,90);assert.equal(s.rows[0].state,"waiting");
 p.connection_readiness.stage="timed_out";s=status(p,null,"journal.idle");assert.equal(s.rows[0].state,"blocked");
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
