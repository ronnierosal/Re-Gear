import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {resolveBuildProfile,buildProfilePlugin} from '../scripts/build_profile_contract.mjs';
import {createHash} from 'node:crypto';
const source=readFileSync(new URL('../src/build-profile.ts',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {productionEgpuTiles,buildAllowsDockIntent}=await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const tile=id=>({id,title:id,value:'Observed',detail:'Existing detail'});

test('production contains only eGPU connection and plain Safe Disconnect',()=>{
 const readings={quick:['fps','manual','egpu','disconnect'].map(tile),egpu:['egpu','disconnect','disconnect-sleep','disconnect-shutdown','switch-handheld'].map(tile),settings:[tile('about')],offline:[tile('sync')]};
 const before=JSON.stringify(readings),view=productionEgpuTiles(readings);
 assert.deepEqual(Object.keys(view),['egpu']);
 assert.deepEqual(view.egpu.map(t=>t.id),['egpu','disconnect']);
 assert.equal(view.egpu[0],readings.egpu[0]);
 assert.equal(JSON.stringify(readings),before);
});
test('missing status cannot fall back to sample values or hidden controls',()=>{
 const view=productionEgpuTiles();
 assert.deepEqual(view.egpu.map(t=>t.value),['Unknown','Unavailable']);
 assert.deepEqual(productionEgpuTiles({settings:[tile('reset')]}),view);
});
test('production denies combined power actions; development keeps them',()=>{
 assert.equal(buildAllowsDockIntent('production','disconnect_only'),true);
 for(const intent of ['sleep','shutdown','disconnect','reconnect','future']){
  assert.equal(buildAllowsDockIntent('production',intent),false);
  assert.equal(buildAllowsDockIntent('development',intent),true);
 }
 assert.equal(buildAllowsDockIntent('unknown','disconnect_only'),false);
});
test('build-time profile is explicit and cannot silently fall back',()=>{
 assert.equal(resolveBuildProfile().profile,'development');
 assert.equal(resolveBuildProfile('production').feature_policy,'stable_allowlist');
 assert.throws(()=>resolveBuildProfile('prod'),/profile_unknown/);
 assert.throws(()=>resolveBuildProfile('development',{}),/profile_contract_invalid/);
});
test('frontend stamp binds selected profile to exact emitted JavaScript',()=>{
 const plugin=buildProfilePlugin('production');
 assert.equal(plugin.load(plugin.resolveId('regear:build-profile')),'export const buildProfile="production";');
 const emitted=[];
 plugin.generateBundle.call({emitFile:file=>emitted.push(file)},null,{'index.js':{type:'chunk',isEntry:true,code:'actual bundle'}});
 const stamp=JSON.parse(emitted[0].source);
 assert.equal(stamp.profile,'production');
 assert.equal(stamp.bundle_sha256,createHash('sha256').update('actual bundle').digest('hex'));
});
