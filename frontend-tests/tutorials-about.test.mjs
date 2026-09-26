import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const read=name=>readFileSync(new URL('../'+name,import.meta.url),'utf8');
const notices=read('THIRD_PARTY_NOTICES.md'),license=read('LICENSE');
const code=ts.transpileModule(read('src/project-credits.ts'),{compilerOptions:{module:ts.ModuleKind.ES2022,target:ts.ScriptTarget.ES2022}}).outputText.replace(/^import .*;$/gm,'');
const {parseProjectDocuments,projectDocuments}=await import('data:text/javascript;base64,'+Buffer.from('const noticesText='+JSON.stringify(notices)+';const licenseText='+JSON.stringify(license)+';'+code).toString('base64'));
test('About reads every notices heading and the exact project license',()=>{
 assert.deepEqual(projectDocuments.sections.map(x=>x.title),[...notices.matchAll(/^#{1,2} (.+)$/gm)].map(x=>x[1].trim()));
 assert.equal(projectDocuments.licenseText,license);
 assert.equal(projectDocuments.licenseId,'GPL-3.0-or-later');
 assert.match(projectDocuments.copyright,/Ronnie Rosal/);
 for(const text of ['Storage Cleaner','Gamescope','SteamTracking'])assert.ok(projectDocuments.sections.some(x=>x.body.includes(text)));
});
test('source changes flow through generic sections without a maintained credits list',()=>{
 const data=parseProjectDocuments('# Credits\r\nNew source\r\n## New contributor\r\n<script>literal</script>','Copyright (C) 2030 New author\nSPDX-License-Identifier: MIT');
 assert.deepEqual(data.sections,[{title:'Credits',body:'New source'},{title:'New contributor',body:'<script>literal</script>'}]);assert.equal(data.licenseId,'MIT');assert.equal(data.copyright,'Copyright (C) 2030 New author');
});
test('document loader uses authoritative local sources and renders text safely',()=>{
 const rollup=read('rollup.config.js'),landing=read('src/quick-access/expanded-command-center/landing.tsx');
 for(const file of ['THIRD_PARTY_NOTICES.md','LICENSE'])assert.ok(rollup.includes(file));
 assert.doesNotMatch(landing,/dangerouslySetInnerHTML|<details|<summary|<a /);
 assert.match(landing,/DialogButton aria-expanded/);assert.match(landing,/Navigation.NavigateToExternalWeb/);
});
test('Tutorials restore selected topic focus and let outer B handle the topic list',()=>{
 const source=read('src/quick-access/expanded-command-center/tutorials.tsx');
 assert.match(source,/restore.current=item.id/);assert.match(source,/data-tutorial-back/);assert.match(source,/topic\?\{onCancelButton/);assert.doesNotMatch(source,/callable|setInterval|executeSafe/);
});
test('Tutorials use the mounted eGPU labels and keep unplug clearance explicit',()=>{
 const source=read('src/quick-access/expanded-command-center/tutorials.tsx');
 for(const label of ['Safe Disconnect','Disconnect + Sleep','Sleep — Keep eGPU Connected','Sleep connected','Shutdown','Safe Disconnect + Shutdown'])assert.ok(source.includes(label),label);
 for(const state of ['Ready','Pending','Unavailable','Refused'])assert.ok(source.includes(state),state);
 assert.match(source,/not permission to unplug/);
 assert.match(source,/absence is verified/);
 assert.match(source,/explicitly clears the physical unplug/);
 assert.doesNotMatch(source,/Safely disconnect|Disconnect eGPU and sleep|Your build may not support them/);
});
