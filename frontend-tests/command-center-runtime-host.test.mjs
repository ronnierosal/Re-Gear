import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/quick-access/expanded-command-center/runtime-host.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ES2022,target:ts.ScriptTarget.ES2022}}).outputText.replace(/^import .*;$/gm,'').replace(/export /g,'');
function fixture(){let current;const register=new Function('createElement','useEffect','useState',code+';return registerRuntimeHost')((type)=>({type}),fn=>{if(!current.started){current.effects.push(fn);}},initial=>[current.state??initial,value=>current.state=value]);return {register,mount(Component){const state={effects:[]};return {render(){current=state;const node=Component();if(!state.started){state.started=true;state.cleanups=state.effects.map(fn=>fn());}return node;},unmount(){state.cleanups?.forEach(fn=>fn?.());}};}};}
test('one global runtime mounts without a landing and survives landing lifetime; stop invalidates before deferred unmount',()=>{
 const f=fixture(),registrations=[],removed=[],owner={active:false,generation:0,stopped:false};let Global;
 const router={addGlobalComponent(name,component){registrations.push(name);Global=component},removeGlobalComponent(name){assert.equal(owner.stopped,true);assert.equal(owner.active,false);removed.push(name)}};
 const stop=f.register(router,'instance-1',()=>null,owner),root=f.mount(Global);assert.equal(root.render(),null);assert.equal(typeof root.render().type,'function');
 const second=f.mount(Global);assert.equal(second.render(),null);assert.equal(second.render(),null,'a second render surface cannot own another poller');
 assert.deepEqual(registrations,['instance-1']);owner.active=true;const generation=owner.generation;stop();assert.ok(owner.generation>generation);assert.equal(root.render(),null);stop();assert.deepEqual(removed,['instance-1']);root.unmount();
});
test('partial registration failure and failed removal cannot mount a late runtime',()=>{
 const f=fixture(),owner={active:false,generation:0,stopped:false};let retained;
 assert.throws(()=>f.register({addGlobalComponent(_name,c){retained=c;throw Error('registration')},removeGlobalComponent(){throw Error('removal')}},'failed-instance',()=>null,owner));
 const late=f.mount(retained);assert.equal(late.render(),null);assert.equal(late.render(),null);assert.equal(owner.stopped,true);
});
test('old instance stop only removes its own registration and cannot retire a newer owner',()=>{
 const f=fixture(),removed=[],router={addGlobalComponent(){},removeGlobalComponent:id=>removed.push(id)};
 const oldOwner={active:false,generation:0,stopped:false},newOwner={active:false,generation:0,stopped:false};
 const stopOld=f.register(router,'old',()=>null,oldOwner);f.register(router,'new',()=>null,newOwner);stopOld();assert.deepEqual(removed,['old']);assert.equal(newOwner.stopped,false);
});

const lifetimeSource=readFileSync(new URL('../src/quick-access/expanded-command-center/controller-reading-lifetime.ts',import.meta.url),'utf8');
const lifetimeCompiled=ts.transpileModule(lifetimeSource,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {createControllerReadingLifetime}=await import(`data:text/javascript;base64,${Buffer.from(lifetimeCompiled).toString('base64')}`);
function setup(){
  let now=0,id=0;const timers=new Map();
  const clock={now:()=>now,schedule:(callback,delay)=>{const key=++id;timers.set(key,{at:now+delay,callback});return()=>timers.delete(key);}};
  const store=createControllerReadingLifetime(clock);const seen=[];const off=store.source.subscribe(()=>seen.push(store.source.read()));
  store.setEligible(true);
  return {store,seen,off,clock,advance(to,run=true){now=to;if(run)for(const [key,timer] of [...timers])if(timer.at<=now){timers.delete(key);timer.callback();}},timers};
}
const reading={controller:{complete:true,exact:true,builtin_available:true,external_connected:true}};

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
  return {...h, pause, refresh: execute(refreshNode), mount: execute(lifecycleNode), invalidateHost(){env.controllerOwner.current.active=false;env.controllerOwner.current.generation++;env.controllerOwner.current.stopped=true;}, rpc: () => rpc, published: () => published};
}

test('host invalidation before Content cleanup retires its timer and late reading',async()=>{
 const h=contentHarness();const cleanup=h.mount();await h.refresh();assert.equal(h.timers.size,1);
 const gate=h.pause('peripheral');const pending=h.refresh();await gate.entered;
 h.invalidateHost();cleanup();assert.equal(h.timers.size,0);assert.equal(h.store.source.read(),null);
 gate.release();await pending;assert.equal(h.store.source.read(),null);assert.equal(h.timers.size,0);
});
