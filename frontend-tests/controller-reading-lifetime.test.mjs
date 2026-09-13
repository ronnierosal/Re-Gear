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

// Execute the production Content lifecycle and refresh callback, including every
// await before peripheral admission. Store-only tests cannot catch owner revival.
function contentHarness() {
  const text = readFileSync(new URL('../src/index.tsx', import.meta.url), 'utf8');
  const tree = ts.createSourceFile('index.tsx', text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const content = tree.statements.find(n => ts.isFunctionDeclaration(n) && n.name?.text === 'Content');
  let refreshNode, lifecycleNode;
  function visit(n) {
    if (ts.isVariableDeclaration(n) && n.name.getText(tree) === 'refresh') refreshNode = n.initializer.arguments[0];
    if (ts.isCallExpression(n) && n.expression.getText(tree) === 'useEffect' && n.arguments[0]?.getText(tree).includes('controllerLifetime.stop()')) lifecycleNode = n.arguments[0];
    ts.forEachChild(n, visit);
  }
  visit(content);
  assert.ok(refreshNode && lifecycleNode);
  const h = setup(); h.store.stop();
  const pending = new Map(); let rpc = 0, published = 0;
  function pause(stage) {
    let release, enter;
    const wait = new Promise(resolve => { release = resolve; });
    const entered = new Promise(resolve => { enter = resolve; });
    pending.set(stage, async () => { pending.delete(stage); enter(); await wait; });
    return {release, entered};
  }
  const at = async stage => { await pending.get(stage)?.(); };
  const noop = () => {};
  const env = {
    controllerOwner: {current: {active: false, generation: 0}},
    controllerVisible: {current: true}, controllerLifetime: h.store,
    refreshInFlight: {current: null}, quickAccessVisible: false, expandedVisible: true,
    diagnosticsOnScreen: {current: false},
    getSnapshot: async () => { await at('snapshot'); return {snapshot: {game_state: 'idle'}, journey: {}}; },
    getAutomaticDockStatus: async () => { await at('automatic'); return {}; },
    refreshTransitionJournal: async () => { await at('journal'); },
    getPeripheralStatus: async () => { rpc++; await at('peripheral'); return reading; },
    linkHealthNotification: {current: null}, decideLinkHealthNotification: () => ({memory: null, notification: null}),
    toaster: {toast: noop}, shouldCollectOptionalDiagnostics: () => false,
    collectOptionalDiagnostics: async () => Object.freeze({peripheralStatus: null}),
    getDockedIgpuStatus: noop, getDiagnosticLoggingStatus: noop, getActionHistory: noop,
    sanitizeJourneyStatus: x => x, lastSnapshotAt: {current: null},
    preflight: {reconcile: noop}, preflightObservation: noop,
    setPayload: () => { published++; },
  };
  for (const name of ['setLoading','setError','setAutomaticDockStatus','setAutomaticDockMessage','setDockedIgpuStatus','setDiagnosticLoggingStatus','setPeripheralStatus','setActionHistory','setPreflightStatus']) env[name] = noop;
  function execute(node) {
    const js = ts.transpileModule(`const extracted = ${node.getText(tree)};`, {compilerOptions: {target: ts.ScriptTarget.ES2022}}).outputText;
    return new Function(...Object.keys(env), `${js}; return extracted;`)(...Object.values(env));
  }
  return {...h, pause, refresh: execute(refreshNode), mount: execute(lifecycleNode), rpc: () => rpc, published: () => published};
}

for (const stage of ['snapshot', 'automatic', 'journal', 'peripheral']) {
  test(`Content cleanup rejects pending ${stage} continuation with retained visibility`, async () => {
    const h = contentHarness(); const cleanup = h.mount(); const gate = h.pause(stage);
    const result = h.refresh(); await gate.entered; cleanup(); gate.release(); await result;
    assert.equal(h.rpc(), stage === 'peripheral' ? 1 : 0);
    assert.equal(h.store.source.read(), null); assert.equal(h.timers.size, 0); assert.equal(h.published(), 0);
  });
}

test('Content replacement admits new generation while old refresh is stalled and preserves serialization', async () => {
  const h = contentHarness(); const oldCleanup = h.mount(); const oldGate = h.pause('snapshot');
  const oldRequest = h.refresh(); await oldGate.entered; oldCleanup();
  const cleanup = h.mount(); const currentGate = h.pause('peripheral');
  const currentRequest = h.refresh(); await currentGate.entered;
  oldGate.release(); await oldRequest;
  // Old finally must not clear the new generation flight or admit duplicate RPCs.
  assert.equal(await h.refresh(), null); assert.equal(h.rpc(), 1);
  currentGate.release(); await currentRequest;
  assert.equal(h.store.source.read(), reading); assert.equal(h.timers.size, 1); assert.equal(h.published(), 1);
  oldCleanup(); assert.equal(h.store.source.read(), reading);
  cleanup(); assert.equal(h.store.source.read(), null); assert.equal(h.timers.size, 0);
});
