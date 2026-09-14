import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=readFileSync(new URL('../src/quick-access/expanded-command-center/control-registry.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {controlRegistry,controlForKey,controlDomains,controlTypes,uniqueControlSlots,replaceControlSlot,registryNativeTiles}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
test('registry separates explicit domain, interaction and native membership',()=>{
 assert.deepEqual(controlDomains,['general','performance','egpu','display','controller','power','battery','storage','network','system']);
 assert.deepEqual(controlTypes,['action','toggle','slider','status','widget','navigation']);
 assert.equal(new Set(controlRegistry.map(x=>x.id)).size,controlRegistry.length);
 const keys=controlRegistry.flatMap(x=>x.sourceKeys);assert.equal(new Set(keys).size,keys.length);
 assert.equal(controlForKey('performance:display').domain,'display');assert.equal(controlForKey('performance:display').nativeTab,'performance');
 assert.equal(controlForKey('performance:auto').type,'navigation');
 assert.equal(controlForKey('utility:brightness').rightEligible,false);
 assert.equal(controlForKey('performance:future-fps'),undefined);
});
test('legacy aliases occupy one stable slot without compacting or losing unknown identities',()=>{
 const keys=['quick:manual','performance:manual','quick:display','performance:display','future:metric','empty:user'];
 const normalized=uniqueControlSlots(keys);assert.equal(normalized.length,keys.length);assert.equal(normalized[0],keys[0]);assert.match(normalized[1],/^empty:duplicate:/);assert.deepEqual(normalized.slice(2),keys.slice(2));assert.deepEqual(uniqueControlSlots(normalized),normalized);
 const swapped=replaceControlSlot(normalized,5,'performance:manual');assert.equal(swapped[0],'empty:user');assert.equal(swapped[5],'performance:manual');assert.equal(swapped.filter(x=>controlForKey(x)?.id==='manual-tdp').length,1);
 for(const pair of [['quick:display','performance:display'],['quick:controller','controllers:controller'],['quick:egpu','egpu:egpu']])assert.deepEqual(uniqueControlSlots(pair),pair);
});
test('native membership includes About and diagnostics, preserves unknown producers, and excludes landing-only entries',()=>{
 const tiles=['shortcut','diagnostics','about','help-guides','future-setting'].map(id=>({id,title:id,value:'Unknown',detail:''}));
 assert.deepEqual(registryNativeTiles({settings:tiles}).settings.map(x=>x.id),['diagnostics','about','future-setting']);
});
