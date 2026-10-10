import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync,existsSync} from 'node:fs';
import ts from 'typescript';

const source=readFileSync(new URL('../src/index.tsx',import.meta.url),'utf8');
const tree=ts.createSourceFile('index.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let publication,landingContent,productionDetail,relaunchEffect,refreshCallback;
function visit(node){
  if(ts.isCallExpression(node)&&node.expression.getText(tree)==='runtimeDetails.publish')publication=node.arguments[0];
  if(ts.isPropertyAssignment(node)&&node.name.getText(tree)==='content'&&node.initializer.getText(tree).includes('ReGearLanding'))landingContent=node.initializer;
  if(ts.isVariableDeclaration(node)&&node.name.getText(tree)==='productionEgpuDetail')productionDetail=node.initializer;
  if(ts.isCallExpression(node)&&node.expression.getText(tree)==='useEffect'&&node.arguments[0]?.getText(tree).includes('claimRelaunchOnMount'))relaunchEffect=node.arguments[0];
  if(ts.isVariableDeclaration(node)&&node.name.getText(tree)==='refresh'&&ts.isCallExpression(node.initializer)&&node.initializer.expression.getText(tree)==='useCallback')refreshCallback=node.initializer.arguments[0];
  ts.forEachChild(node,visit);
}
visit(tree);
assert.ok(publication,'exercise the real runtime publication');
function evaluate(node,env){
  const code=ts.transpileModule(`const value = ${node.getText(tree)};`,{compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022}}).outputText;
  return new Function(...Object.keys(env),`${code};return value;`)(...Object.values(env));
}
function state(profile,target='ally'){
  const calls=[];
  const env={buildProfile:profile,menuFresh:true,payload:{inference:{mode:'portable'}},
    runtimeOwner:{stopped:false},safeDisconnectBusy:false,tvSwitchBusy:false,safeDisconnectMessage:'',
    primaryDisplayAction:{target,disabled:false,description:'Ready'},
    executeSafeDisconnect:()=>calls.push('shutdown'),activateDisplay:()=>calls.push('handheld'),
    setProductionActionRequest:()=>calls.push('sleep'),productionActionNonce:{current:0},
    productionEgpuDetail:'readonly-egpu',egpuDetail:'egpu',diagnosticDetail:'diagnostic',displayDetail:'display',wrapDetail:value=>value,
    React:{createElement:()=>({node:true}),Fragment:'fragment'},PanelSection:'section',EgpuModule:'egpu',
    ButtonItem:'button',TransitionAcknowledgementControl:'guarded-display-ack',Usb4WaitingStatus:'readonly-usb4-status',usb4WaitingSource:null,egpuPresentation:()=>({}),runtimeDetails:{source:{navigate:()=>{}}}};
  return {value:evaluate(publication,env),calls};
}

// Execute the real coordinator and plugin startup/Content refresh composition.
// The unrelated automatic-status request is controllably delayed to prove that
// direct admission is consumed before a second await can age the response.
function sleepRuntime(profile,options={}){
  const exports={};
  const coordinatorCode=ts.transpileModule(readFileSync(new URL('../src/sleep-preflight.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  new Function('exports',coordinatorCode)(exports);
  const counts={resolve:0,acquire:0,release:0,patch:0,unpatch:0,read:0,automatic:0,toast:0,modal:0,close:0};
  const jobs=[];let suspend,reply,followup,clock=Date.parse('2026-10-09T04:00:00Z');
  const runtimeOwner={stopped:false};
  const startup=source.slice(source.indexOf('  let warningModal:'),source.indexOf('  const offlineFocusChecks',source.indexOf('  let warningModal:')));
  const env={SleepPreflightCoordinator:exports.SleepPreflightCoordinator,runtimeOwner,
    createDeckySteamSuspendAdapter(){counts.resolve++;return{
      acquireBlocker(){counts.acquire++;return()=>{counts.release++;options.release?.();};},
      observeSuspendRequests(fn){counts.patch++;suspend=fn;return()=>{counts.unpatch++;options.unpatch?.();};},
    };},PRODUCT_NAME:'Re-Gear',BLOCKED_ATTEMPT_MODAL_DELAY_MS:1,
    toaster:{toast(){counts.toast++;}},
    window:{setTimeout(fn){jobs.push({fn,cancelled:false});return jobs.length;},clearTimeout(id){jobs[id-1].cancelled=true;}},
    deliverBlockedAttempt(warning,ports){ports.showModal();},
    showBlockedAttempt(){counts.modal++;options.show?.();return{Close(){counts.close++;options.close?.();}};},
  };
  const startupCode=ts.transpileModule(startup,{compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022}}).outputText;
  const preflight=new Function(...Object.keys(env),`${startupCode};return preflight;`)(...Object.values(env));
  const owner={current:{active:true,generation:1}},inFlight={current:null};
  const refreshEnv={buildProfile:profile,controllerOwner:owner,refreshInFlight:inFlight,preflight,
    Date:{now:()=>clock},SNAPSHOT_STALE_AFTER_MS:10000,setLoading(){},setError(){},setPreflightStatus(){},
    getSnapshot(){counts.read++;assert.equal(counts.acquire,1,'startup lease precedes direct RPC');return new Promise((resolve,reject)=>{reply={resolve,reject};});},
    getAutomaticDockStatus(){counts.automatic++;return new Promise(resolve=>{followup=resolve;});},setAutomaticDockStatus(){},setAutomaticDockMessage(){},
  };
  const refresh=evaluate(refreshCallback,refreshEnv);
  return{counts,preflight,owner,runtimeOwner,jobs,suspend:()=>suspend(),refresh,
    reply(value){reply.resolve(value);},reject(){reply.reject(Error('read rejected'));},
    advance(ms){clock+=ms;},
    async finish(pending){owner.current.active=false;followup?.(null);await pending;},
    stop(){owner.current.active=false;runtimeOwner.stopped=true;preflight.stop();},
  };
}
const sleepReply=(admission='observation-only',offset=0)=>({runtime_admission:{schema_version:1,sleep_interceptor_admission:admission},snapshot:{schema_version:3,observed_at:new Date(Date.parse('2026-10-09T04:00:00Z')+offset).toISOString()}});
const settle=async()=>{await Promise.resolve();await Promise.resolve();};

test('both profile compositions protect synchronously then retire from direct admission before unrelated awaits',async()=>{
  for(const profile of ['development','production']){
    const app=sleepRuntime(profile);assert.equal(app.preflight.status().blocking,true);
    assert.deepEqual([app.counts.resolve,app.counts.acquire,app.counts.patch,app.counts.read],[1,1,1,0]);
    const pending=app.refresh();app.suspend();const queued=app.jobs[0];
    app.reply(sleepReply());await settle();
    assert.equal(app.counts.automatic,1);assert.equal(app.preflight.status().reason,'observation_only');
    assert.equal(app.preflight.status().blocking,false);assert.equal(app.counts.release,1);assert.equal(app.counts.unpatch,1);
    assert.equal(queued.cancelled,true);queued.fn();app.suspend();assert.equal(app.counts.modal,0);
    app.preflight.start();app.preflight.reconcile({kind:'unavailable'});assert.equal(app.counts.acquire,1);
    await app.finish(pending);app.stop();assert.equal(app.counts.release,1);
  }
});

test('actual direct composition denies malformed, accessor, inherited, stale and future retirement',async()=>{
  let reads=0;const accessor=sleepReply();Object.defineProperty(accessor,'runtime_admission',{get(){reads++;return sleepReply().runtime_admission;}});
  const cases=[{},null,sleepReply('UNKNOWN'),sleepReply('observation-only',1),sleepReply('observation-only',-10000),
    {...sleepReply(),runtime_admission:{schema_version:'1',sleep_interceptor_admission:'observation-only'}},
    {...sleepReply(),snapshot:{schema_version:2,observed_at:'2026-10-09T04:00:00Z'}},accessor,Object.create(sleepReply())];
  for(const value of cases){
    const app=sleepRuntime('production');const pending=app.refresh();app.reply(value);await settle();
    assert.equal(app.preflight.status().blocking,true);assert.equal(app.counts.release,0);assert.equal(app.counts.unpatch,0);
    await app.finish(pending);app.stop();
  }
  assert.equal(reads,0);
});

test('actual current-generation composition latches supported lifetime and rejects obsolete or disposed replies',async()=>{
  for(const change of ['generation','inactive','disposed']){
    const app=sleepRuntime('production');const pending=app.refresh();
    if(change==='generation')app.owner.current.generation++;
    else if(change==='inactive')app.owner.current.active=false;
    else app.stop();
    app.reply(sleepReply());await pending;assert.equal(app.counts.automatic,0);assert.equal(app.preflight.isRetired(),false);app.stop();
  }
  const app=sleepRuntime('production');let pending=app.refresh();app.reply(sleepReply('supported-runtime'));await settle();await app.finish(pending);
  app.owner.current.active=true;app.owner.current.generation++;pending=app.refresh();app.reply(sleepReply());await settle();
  assert.equal(app.preflight.isRetired(),false);assert.equal(app.preflight.status().blocking,true);assert.equal(app.counts.release,0);
  await app.finish(pending);app.stop();
});

test('actual composition keeps delayed/rejected protection and reports cleanup uncertainty without repeat cleanup',async()=>{
  const delayed=sleepRuntime('production');const pending=delayed.refresh();delayed.advance(10000);delayed.reply(sleepReply());await settle();
  assert.equal(delayed.preflight.status().blocking,true);await delayed.finish(pending);delayed.stop();
  const rejected=sleepRuntime('production');const rejectedRead=rejected.refresh();rejected.reject();await rejectedRead;
  assert.equal(rejected.preflight.status().blocking,true);assert.equal(rejected.counts.automatic,0);rejected.stop();
  for(const failure of ['close','unpatch','release']){
    const app=sleepRuntime('production',{[failure](){throw Error(failure+' failed');}});app.suspend();app.jobs[0].fn();
    const read=app.refresh();app.reply(sleepReply());await settle();
    const status=app.preflight.status();assert.equal(status.state,'unavailable');assert.match(status.error,/failed/);
    if(failure==='release')assert.equal(status.blocking,null);
    assert.equal(app.counts.unpatch,1);assert.equal(app.counts.release,1);await app.finish(read);app.stop();app.suspend();
    assert.equal(app.counts.release,1);assert.equal(app.counts.unpatch,1);
  }
});

test('reentrant native modal creation closes the late handle after terminal retirement',()=>{
  let app;
  app=sleepRuntime('production',{show(){app.preflight.admitSnapshot(sleepReply(),Date.parse('2026-10-09T04:00:00Z'),10000);}});
  app.suspend();app.jobs[0].fn();
  assert.equal(app.preflight.isRetired(),true);
  assert.equal(app.counts.modal,1);assert.equal(app.counts.release,1);assert.equal(app.counts.unpatch,1);
  assert.equal(app.counts.close,1,'Decky returned after retirement: close rather than retain the late handle');
  app.stop();assert.equal(app.counts.close,1);
});
test('production runtime publishes only eGPU content and denies retained hidden callbacks',()=>{
  const {value,calls}=state('production');
  assert.deepEqual(Object.entries(value.views).filter(([,node])=>node!==null).map(([key])=>key),['egpu']);
  assert.equal(value.views.egpu,'readonly-egpu');
  for(const action of ['shutdown','sleepConnected']){
    assert.equal(value[action].available,false);
    value[action].request();
  }
  assert.equal(value.displayAction.available,true);
  value.displayAction.request();
  assert.deepEqual(calls,['handheld']);
});
test('production does not consume or launch a retained development game request',()=>{
  let calls=0;
  const env={buildProfile:'production',quickAccessVisible:true,claimRelaunchOnMount:()=>calls++,liveGameClosePorts:()=>({})};
  evaluate(relaunchEffect,env)();assert.equal(calls,0);
  evaluate(relaunchEffect,{...env,buildProfile:'development'})();assert.equal(calls,1);
});
test('real production eGPU detail mounts observations and only the existing guarded result control',()=>{
  const jsx=(type,props)=>({type,props});
  function module(path){
    const exports={};
    const code=ts.transpileModule(readFileSync(new URL(path,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
    new Function('exports','require',code)(exports,name=>{
      if(name==='react/jsx-runtime')return{jsx,jsxs:jsx};
      if(name==='react')return{useSyncExternalStore:(_subscribe,read)=>read()};
      if(name.endsWith('.svg'))return 'synthetic-asset';
      if(name.startsWith('.')){
        const candidate=new URL(`${name}.tsx`,new URL(path,import.meta.url));
        return module(existsSync(candidate)?candidate:new URL(`${name}.ts`,new URL(path,import.meta.url)));
      }
      return{DialogButton:'button',Focusable:'focus',Field:'field',GamepadButton:{DIR_UP:9,DIR_DOWN:10}};
    });
    return exports;
  }
  const {EgpuModule}=module('../src/quick-access/modules/egpu.tsx');
  const {egpuPresentation}=module('../src/quick-access/modules/egpu-presentation.ts');
  const {Usb4WaitingStatus}=module('../src/usb4-waiting-runtime.tsx');
  const {USB4_WAITING_TEXT,USB4_WAITING_UNAVAILABLE}=module('../src/usb4-waiting-model.ts');
  let acknowledgementMounts=0;
  const env={menuFresh:false,payload:{ignored:true},PanelSection:'section',EgpuModule,egpuPresentation,Usb4WaitingStatus,usb4WaitingSource:null,
    TransitionAcknowledgementControl:()=>{acknowledgementMounts++;return null;},
    React:{createElement:(type,props,...children)=>jsx(type,{...props,children})}};
  let readingCount=0;
  function mount(node){
    if(Array.isArray(node))return node.map(mount);
    if(!node||typeof node!=='object')return node;
    if(typeof node.type==='function')return mount(node.type(node.props));
    // Informational focus may reveal a reading. Activation/mutation remains absent.
    assert.equal(Object.keys(node.props??{}).some(key=>/^on[A-Z]/.test(key)&&!['onGamepadFocus','onGamepadDirection'].includes(key)),false);
    if(node.props?.onGamepadFocus||node.props?.onGamepadDirection)assert.equal(node.type,'field');
    if(node.props?.onGamepadDirection){
      assert.equal(node.props.highlightOnFocus,false);readingCount++;
      const previous=globalThis.HTMLElement;class Element{};globalThis.HTMLElement=Element;
      try{
        const area=new Element();area.scrollTop=53;area.getBoundingClientRect=()=>({top:0,bottom:100,height:100});
        const target=new Element();target.closest=()=>area;target.getBoundingClientRect=()=>({top:57-area.scrollTop,bottom:77-area.scrollTop,height:20});area.querySelector=()=>readingCount===1?target:new Element();
        let consumed=0;const event={currentTarget:target,detail:{button:9},preventDefault(){consumed++;},stopPropagation(){}};
        assert.equal(node.props.onGamepadDirection(event),readingCount===1);assert.equal(area.scrollTop,readingCount===1?0:53);assert.equal(consumed,readingCount===1?1:0);
        event.detail.button=10;assert.equal(node.props.onGamepadDirection(event),false,'Down does not activate or consume an ordinary row');
      }finally{globalThis.HTMLElement=previous;}
    }
    assert.notEqual(node.type,'button');
    return {...node,props:{...node.props,children:mount(node.props?.children)}};
  }
  const rendered=JSON.stringify(mount(evaluate(productionDetail,env)));
  assert.match(rendered,/Unknown/);
  assert.equal(acknowledgementMounts,1);
  assert.equal(readingCount,8,'production still registers all seven readings plus safety information');
  assert.doesNotMatch(rendered,/Automatic TV docking|Configure docking|Troubleshoot|onClick|ToggleField|recovery is still available/);
  // Mount the real passive component without changing existing row/action checks.
  for(const status of [null,
    Object.freeze({state:'unknown',guidance:USB4_WAITING_UNAVAILABLE,automaticNoticeSuppressed:true}),
    Object.freeze({state:'unauthorized',guidance:USB4_WAITING_TEXT,automaticNoticeSuppressed:true})]){
    readingCount=0;acknowledgementMounts=0;
    let sourceReads=0;
    env.usb4WaitingSource={read:()=>{sourceReads++;return status;},subscribe:()=>()=>{}};
    const passive=JSON.stringify(mount(evaluate(productionDetail,env)));
    assert.equal(sourceReads,1,'actual Usb4WaitingStatus consumes the supplied source');
    assert.equal(acknowledgementMounts,1);
    assert.equal(readingCount,status?9:8,'passive guidance adds one informational leaf only');
    if(status){assert.ok(passive.includes(status.guidance));assert.match(passive,/"role":"status"/);}
    else assert.doesNotMatch(passive,/USB4 authorization status/);
    assert.doesNotMatch(passive,/Automatic TV docking|Configure docking|Troubleshoot|onClick|ToggleField|recovery is still available|uw-/);
  }
});
test('development retains existing runtime views and actions',()=>{
  const {value,calls}=state('development');
  assert.deepEqual(Object.keys(value.views),['egpu','egpu-config','diagnostics','display']);
  for(const action of ['shutdown','displayAction','sleepConnected']){
    assert.equal(value[action].available,true);
    value[action].request();
  }
  assert.deepEqual(calls,['shutdown','handheld','sleep']);
});
test('hidden providers stay dormant while connection and receipt runtime remain mounted',()=>{
  assert.match(source,/usePerformance\(buildProfile === "development" &&/);
  assert.match(source,/offlineFocusChecks = buildProfile === "development" \? startOfflineFocusChecks\(\)/);
  assert.match(source,/preflight.start\(\)/);
  assert.match(source,/const connection = startConnectionMonitor\(/);
  assert.match(source,/tilePublisher.source, \(\) => menuSnapshot, renderDetail, runtimeDetails.source, buildProfile/);
});
test('production landing retains launcher and credits without instructions for hidden features',()=>{
  const env={buildProfile:'production',React:{Fragment:'fragment',createElement:(type,props,...children)=>({type,props,children})},
    ReGearLanding:'development-landing',ReGearAbout:'credits',expandedMenu:{Settings:'shortcut'},
    PanelSection:'section',PanelSectionRow:'row'};
  const production=JSON.stringify(evaluate(landingContent,env));
  assert.match(production,/shortcut/);assert.match(production,/credits/);assert.match(production,/Safe Disconnect/);
  assert.doesNotMatch(production,/development-landing|Quick Access|LB\/RB|brightness|customiz/i);
  assert.equal(evaluate(landingContent,{...env,buildProfile:'development'}).type,'development-landing');
});
