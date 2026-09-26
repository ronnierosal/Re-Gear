import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
const index=readFileSync(new URL('../src/index.tsx',import.meta.url),'utf8');
const landing=readFileSync(new URL('../src/quick-access/expanded-command-center/landing.tsx',import.meta.url),'utf8');
test('Decky landing is shortcut, usage and credits with no runtime control tree',()=>{assert.match(index,/content: buildProfile === "development" \? <ReGearLanding shortcut=\{<expandedMenu.Settings\/>\}/);assert.doesNotMatch(index,/content: <Content/);assert.doesNotMatch(landing,/getSnapshot|WholeDockControl|Open expanded demo/);for(const title of ['How to use','About & credits'])assert.ok(landing.includes(title));});
test('runtime is registered once outside landing with existing poller and generation invalidation',()=>{assert.equal((index.match(/registerRuntimeHost\(routerHook/g)??[]).length,1);assert.equal((index.match(/const Runtime=\(\)=> <Content/g)??[]).length,1);assert.doesNotMatch(index,/useQuickAccessVisible/);assert.match(index,/const quickAccessVisible = expandedVisible/);assert.match(index,/if\(!runtimeOwner.stopped\)tilePublisher.publish/);assert.match(index,/try\{stopRuntime\?\.\(\);\}catch/);assert.match(index,/runtimeDetails.stop\(\);menuSnapshot=null;tilePublisher.publish\(\{fresh:false\}\)/);});


test('offline absent binding stays unknown and controls unavailable without timer or command',()=>{
 const source=readFileSync(new URL('../src/quick-access/expanded-command-center/offline-tab.ts',import.meta.url),'utf8');
 assert.match(source,/title:'Selected Game',value:'Unknown'/);assert.match(source,/title:'Offline Readiness',value:'Unknown'/);assert.match(source,/title:'Sync Schedule',value:'Unavailable'/);
 assert.doesNotMatch(source,/setInterval|setTimeout|callable|syncNow\(/);
});
