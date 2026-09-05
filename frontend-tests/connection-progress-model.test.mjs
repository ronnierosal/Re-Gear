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
 assert.deepEqual(v.rows.map(r=>r.state),["ready","checking","blocked"]);
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
 assert.match(panel,/<ConnectionProgressOverlay \{\.\.\.connectionProgressViewModel\(source\)\}/);
 assert.match(panel,/latest.canSwitch && Date.now\(\) < latest.expiresAt/);
 assert.match(overlay,/<DialogButton[^>]*onClick=\{props.onHide\}/);
 assert.doesNotMatch(overlay,/setInterval|setTimeout|fetch\(|getSnapshot|<button/);
});
