import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const js=ts.transpileModule(readFileSync(new URL('../src/disconnect-progress.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {disconnectProgress}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
const sample=()=>({snapshot:{observed_at:new Date().toISOString(),game_state:'idle',gpus:[{present:true,selected_for_render:true,role:'internal',confidence:'verified'}],displays:[{active:true,kind:'internal',confidence:'verified'}],disconnect_readiness:{applicable:true,ready:true,scan_complete:true,error:'',clients:[],storage_devices:0,storage_in_use:false}}});
test('clean scan never authorizes live unplug or invents release/audio verification',()=>{
 const result=disconnectProgress(sample());assert.equal(result.safeToUnplug,false);
 assert.equal(result.rows[0].state,'ready');assert.equal(result.rows[1].state,'ready');assert.equal(result.rows[3].state,'ready');
 for(const i of [2,4,5])assert.equal(result.rows[i].state,'unavailable');
});
test('stale errors running games and incomplete scans cannot remain ready',()=>{
 const p=sample();p.snapshot.observed_at='invalid';assert.ok(disconnectProgress(p).rows.every(r=>r.state!=='ready'));
 assert.ok(disconnectProgress(sample(),true).rows.every(r=>r.state!=='ready'));
 const q=sample();q.snapshot.game_state='running';q.snapshot.disconnect_readiness.scan_complete=false;
 assert.equal(disconnectProgress(q).rows[0].state,'blocked');assert.equal(disconnectProgress(q).rows[3].state,'waiting');
});
