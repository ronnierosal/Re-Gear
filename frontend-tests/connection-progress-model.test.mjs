import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
const js = ts.transpileModule(readFileSync(new URL("../src/connection-progress-model.ts", import.meta.url), "utf8"), {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {connectionProgressViewModel: view} = await import("data:text/javascript;base64,"+Buffer.from(js).toString("base64"));
const sample = () => ({phase:"checking",connected:true,expiresAt:200,seconds:90,title:"Waiting for TV HDMI",canSwitch:false,
  rows:[{label:"GPU and driver",state:"ready"},{label:"TV HDMI detected",state:"waiting"},{label:"No game running",state:"blocked"}]});

test("popup uses detected GPU name and generic fallback, never a dock-brand default",()=>{
 const s=sample(); assert.equal(view(s,100).deviceLabel,"eGPU connected");
 s.gpuName="Example GPU 9000"; assert.equal(view(s,100).deviceLabel,"Example GPU 9000 connected");
 s.gpuName="Another GPU 500"; assert.equal(view(s,100).deviceLabel,"Another GPU 500 connected");
 assert.equal(view(s,200).deviceLabel,"eGPU connection");
 assert.equal(view(s,100).keepConnectedMessage,"Keep eGPU connected · Hide keeps docking active.");
});
test("approved overlay preserves monitor evidence and blockers without new readiness inference",()=>{
 const s=sample(); const v=view(s,100);
 assert.equal(v.phase,"connecting"); assert.equal(v.detail,s.title); assert.equal(v.elapsedSeconds,90);
 assert.deepEqual(v.rows.map(r=>r.state),["ready","pending","blocked"]);
 assert.equal(s.rows[1].state,"waiting");
});
test("expired completion cannot leave the approved overlay green",()=>{
 const s={...sample(),phase:"complete"};
 const v=view(s,200); assert.equal(v.phase,"connecting"); assert.ok(v.rows.every(r=>r.state==="pending"));
});
test("switching and completion never promote audio preflight into TV audio verification",()=>{
 const s=sample(); s.phase="switching";
 assert.equal(view(s,100).rows.find(r=>r.key==="audio").state,"pending");
 s.phase="complete";
 const v=view(s,100); assert.equal(v.phase,"ready");
 assert.equal(v.rows.find(r=>r.key==="display").state,"ready");
 assert.equal(v.rows.find(r=>r.key==="audio").state,"pending");
});
test("live renderer wires the approved overlay to the existing store and native Hide",()=>{
 const panel=readFileSync(new URL("../src/connection-live-panel.tsx",import.meta.url),"utf8");
 const overlay=readFileSync(new URL("../src/connection-progress-overlay.tsx",import.meta.url),"utf8");
 assert.match(panel,/useSyncExternalStore\(store.subscribe, store.get\)/);
 assert.match(panel,/<ConnectionProgressOverlay \{\.\.\.connectionProgressViewModel\(status\)\}/);
 assert.match(panel,/latest.canSwitch && Date.now\(\) < latest.expiresAt/);
 assert.match(overlay,/<DialogButton[^>]*onClick=\{props.onHide\}/);
 assert.doesNotMatch(overlay,/setInterval|setTimeout|fetch\(|getSnapshot|<button/);
});

test("connection observation preserves the actual reason without inventing a transition",()=>{
 const s=sample(); s.title="Ready to switch to TV";
 const v=view(s,100);
 assert.equal(v.phase,"connecting");
 assert.equal(v.detail,"Ready to switch to TV");
 assert.equal(v.rows[1].state,"pending");
 s.phase="switching";
 assert.ok(!view(s,100).rows.some(row=>row.label==="Final verification"));
 const stale=view({...s,phase:"complete"},200);
 assert.equal(stale.detail,"Waiting for a fresh status update");
 assert.ok(stale.rows.every(row=>row.state!=="ready"));
});


test("waiting rows are unconfirmed, not active work, and stale rows lose confirmation",()=>{
 const s=sample(); const v=view(s,100);
 assert.equal(v.rows[0].stateLabel,"Confirmed");
 assert.equal(v.rows[1].state,"pending");
 assert.equal(v.rows[1].stateLabel,"Not yet verified");
 assert.equal(v.rows[2].stateLabel,"Needs attention");
 assert.ok(view(s,200).rows.every(r=>r.stateLabel==="Status unavailable"));
});
test("delay guidance starts at one minute and changes at three without promising completion",()=>{
 const s={...sample(),rows:[{label:"GPU and driver",state:"waiting"}]};
 for(const seconds of [0,59,NaN]) assert.equal(view({...s,seconds},100).delayNotice,undefined);
 assert.match(view({...s,seconds:60},100).delayNotice,/Taking longer than expected/);
 assert.match(view({...s,seconds:179},100).delayNotice,/completion is not guaranteed/);
 assert.match(view({...s,seconds:180},100).delayNotice,/after three minutes/);
 assert.equal(view({...s,phase:"complete",seconds:180},100).delayNotice,undefined);
 assert.equal(view({...s,seconds:180},200).delayNotice,undefined);
});


test("activation warning remains until fresh completion, never attachment alone",()=>{
 const s=sample();
 assert.match(view(s,100).activationNotice,/not yet confirmed/);
 assert.match(view({...s,phase:"switching"},100).activationNotice,/not yet confirmed/);
 assert.equal(view({...s,phase:"complete"},100).activationNotice,undefined);
 assert.match(view({...s,phase:"complete"},200).activationNotice,/unavailable/);
});

test('settled eGPU waiting for a TV does not become a connection delay warning',()=>{
 for(const seconds of [60,180,600]){
  const v=view({...sample(),displayPending:true,seconds,title:'eGPU ready — waiting for TV'},100);
  assert.equal(v.delayNotice,undefined);assert.equal(v.phase,'connecting');assert.equal(v.detail,'eGPU ready — waiting for TV');
 }
 const stale=view({...sample(),displayPending:true},200);assert.match(stale.detail,/fresh status/);assert.ok(stale.rows.every(row=>row.state==='pending'));
});


test('switching preserves original prerequisites and setup blockers suppress delay copy',()=>{
 const s=sample();
 const switching=view({...s,phase:'switching'},100);
 for(const original of s.rows)assert.ok(switching.rows.some(row=>row.label===original.label));
 assert.equal(view({...s,seconds:600},100).delayNotice,undefined);
});
