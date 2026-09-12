import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=readFileSync(new URL('../src/quick-access/expanded-command-center/controller-reading-lifetime.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {createControllerReadingLifetime}=await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
function setup(){
  let now=0,id=0;const timers=new Map();
  const clock={now:()=>now,schedule:(callback,delay)=>{const key=++id;timers.set(key,{at:now+delay,callback});return()=>timers.delete(key);}};
  const store=createControllerReadingLifetime(clock);const seen=[];const off=store.source.subscribe(()=>seen.push(store.source.read()));
  store.setEligible(true);
  return {store,seen,off,clock,advance(to,run=true){now=to;if(run)for(const [key,timer] of [...timers])if(timer.at<=now){timers.delete(key);timer.callback();}},timers};
}
const reading={controller:{complete:true,exact:true,builtin_available:true,external_connected:true}};

test('controller reading expires exactly ten seconds from request start without another RPC',()=>{
  const h=setup();const ticket=h.store.start();h.advance(3500);h.store.complete(ticket,reading);
  assert.equal(h.store.source.read(),reading);h.advance(9999);assert.equal(h.store.source.read(),reading);
  h.advance(10000);assert.equal(h.store.source.read(),null);assert.deepEqual(h.seen,[reading,null]);assert.equal(h.timers.size,0);
});
test('late or stalled transport cannot restart the client lifetime',()=>{
  for(const delay of [10000,25000]){const h=setup();const ticket=h.store.start();h.advance(delay);h.store.complete(ticket,reading);assert.equal(h.store.source.read(),null);assert.equal(h.timers.size,0);}
  const h=setup();h.store.start();h.advance(30000);assert.equal(h.store.source.read(),null);
});
test('superseded responses and failures cannot replace the current generation',()=>{
  const h=setup();const old=h.store.start();h.advance(100);const current=h.store.start();const newer={...reading};
  h.store.complete(current,newer);h.store.complete(old,reading);h.store.complete(old,null);assert.equal(h.store.source.read(),newer);
  const next=h.store.start();assert.equal(h.store.source.read(),null);h.store.complete(next,null);assert.equal(h.store.source.read(),null);
});
test('hide, ineligible game context, and unload invalidate pending and completed reads',()=>{
  for(const stop of [s=>s.setEligible(false),s=>s.stop()]){
    const h=setup();const ticket=h.store.start();h.store.complete(ticket,reading);stop(h.store);assert.equal(h.store.source.read(),null);
    h.store.complete(ticket,reading);assert.equal(h.store.source.read(),null);assert.equal(h.store.start(),null);
    h.store.setEligible(true);h.store.complete(ticket,reading);assert.equal(h.store.source.read(),null);
    const fresh=h.store.start();h.store.complete(fresh,reading);assert.equal(h.store.source.read(),reading);
  }
});
test('throttled timer cannot return old data and expiry still notifies other subscribers',()=>{
  const h=setup();h.store.complete(h.store.start(),reading);h.advance(10000,false);assert.equal(h.store.source.read(),null);
  h.advance(10000);assert.deepEqual(h.seen,[reading,null]);h.off();h.store.complete(h.store.start(),reading);assert.deepEqual(h.seen,[reading,null]);
});
test('controller lifetime is independent of GPU reads and drives both consumer paths',async()=>{
  const graph=['quick-access/performance-state','quick-access/expanded-command-center/model','quick-access/expanded-command-center/tiles','quick-access/expanded-command-center/tile-source'].map(path=>ts.transpileModule(readFileSync(new URL(`../src/${path}.ts`,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}}).outputText.replace(/^import[^;]*;$/gm,'')).join('\n');
  const {buildTiles}=await import(`data:text/javascript;base64,${Buffer.from(graph).toString('base64')}`);
  async function load(path){const js=ts.transpileModule(readFileSync(new URL(`../src/${path}.ts`,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}}).outputText;return import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);}
  const {controllerPresentation}=await load('quick-access/modules/controller-presentation');
  const {createNonEgpuDetailPublisher}=await load('quick-access/expanded-command-center/non-egpu-detail-source');
  const details=createNonEgpuDetailPublisher();const h=setup();let gpuFresh=false;let tiles;
  const update=()=>{const value=h.store.source.read();const controller=controllerPresentation({peripheral:value});tiles=buildTiles({fresh:gpuFresh,controllerFresh:value!==null,controller});details.publish({controller,performance:null});};
  h.store.source.subscribe(update);h.store.complete(h.store.start(),reading);
  assert.notEqual(tiles.controllers.find(tile=>tile.id==='builtin').value,'Unknown');
  assert.equal(details.source.read().controller.builtin.known,true);
  gpuFresh=true;h.advance(10000);
  assert.equal(tiles.controllers.find(tile=>tile.id==='builtin').value,'Unknown');
  assert.equal(details.source.read().controller.builtin.known,false);
  update();assert.equal(tiles.controllers.find(tile=>tile.id==='builtin').value,'Unknown');
  const index=readFileSync(new URL('../src/index.tsx',import.meta.url),'utf8');
  assert.match(index,/controllerFresh: controllerReading !== null/);
  assert.equal((index.match(/peripheral: controllerReading, shortcutAvailable: menuShortcutAvailable/g)||[]).length,2);
  assert.doesNotMatch(index,/peripheral: menuFresh \? peripheralStatus/);
  assert.match(index,/controllerLifetime\.setEligible\(controllerVisible\.current && nextPayload\.snapshot\.game_state === "idle"\)/);
  assert.match(index,/getPeripheralStatus: readPeripheral/);
});
