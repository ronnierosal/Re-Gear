import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=['control-registry.ts','button-catalog.ts'].map(name=>readFileSync(new URL('../src/quick-access/expanded-command-center/'+name,import.meta.url),'utf8')).join('\n');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText.replace(/^import .*;$/gm,'');
const {groupedButtonCatalog,catalogMetadata,pickerRows,movePickerFocus}=await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const origin=(tab,id,title=id)=>({key:`${tab}:${id}`,tab,tile:{id,title,value:'Unknown',detail:''}});
test('proven aliases select home entries while leaving full saved-key catalog untouched',()=>{
 const catalog=[origin('quick','manual'),origin('quick','disconnect'),origin('performance','manual'),origin('egpu','disconnect')];
 const before=JSON.stringify(catalog),entries=groupedButtonCatalog(catalog).flatMap(g=>g.entries);
 assert.deepEqual(entries.map(e=>e.origin.key),['performance:manual','egpu:disconnect']);assert.equal(JSON.stringify(catalog),before);
 assert.deepEqual(entries[0].aliases,['quick:manual']);assert.equal(entries[1].kind,'action');
 assert.equal(groupedButtonCatalog([catalog[0]])[0].entries[0].origin.key,'quick:manual','legacy source remains selectable if home is absent');
});
test('lookalike targets, controller assignment and eGPU summaries stay distinct',()=>{
 const catalog=[origin('quick','display','Display'),origin('performance','display','Display'),origin('quick','controller','Controller'),origin('controllers','controller','Controller'),origin('quick','egpu','eGPU Status'),origin('egpu','egpu','eGPU Status')];
 const entries=groupedButtonCatalog(catalog).flatMap(g=>g.entries);assert.equal(entries.length,6);
 assert.equal(entries.find(e=>e.origin.key==='quick:controller').category,'controller');
 assert.equal(entries.find(e=>e.origin.key==='quick:egpu').label,'eGPU Connection');assert.equal(entries.find(e=>e.origin.key==='egpu:egpu').label,'eGPU Overview');
 assert.equal(catalogMetadata(origin('quick','future-device-metric')).category,null);
 assert.equal(catalogMetadata(origin('settings','about')).category,'system');assert.equal(catalogMetadata(origin('offline','offline-sync')).category,'network');
});
test('directional focus crosses short category rows and reaches Remove and Cancel',()=>{
 const rows=pickerRows([['a','b','c','d'],['e','f'],['g']]);assert.deepEqual(rows,[['a','b','c'],['d'],['e','f'],['g'],['choice:remove'],['picker-close']]);
 assert.equal(movePickerFocus(rows,'c','down'),'d');assert.equal(movePickerFocus(rows,'d','down'),'e');assert.equal(movePickerFocus(rows,'d','right'),'e');assert.equal(movePickerFocus(rows,'e','left'),'d');assert.equal(movePickerFocus(rows,'f','down'),'g');assert.equal(movePickerFocus(rows,'g','down'),'choice:remove');assert.equal(movePickerFocus(rows,'choice:remove','down'),'picker-close');assert.equal(movePickerFocus(rows,'picker-close','down'),'picker-close');assert.equal(movePickerFocus(rows,'a','up'),'a');
 const visited=new Set(['a']);for(const id of visited)for(const direction of ['up','down','left','right'])visited.add(movePickerFocus(rows,id,direction));assert.deepEqual([...visited].sort(),rows.flat().sort());
});
