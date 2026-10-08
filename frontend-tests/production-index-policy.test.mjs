import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const source=readFileSync(new URL('../src/index.tsx',import.meta.url),'utf8');
const tree=ts.createSourceFile('index.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let publication,landingContent,productionDetail,relaunchEffect;
function visit(node){
  if(ts.isCallExpression(node)&&node.expression.getText(tree)==='runtimeDetails.publish')publication=node.arguments[0];
  if(ts.isPropertyAssignment(node)&&node.name.getText(tree)==='content'&&node.initializer.getText(tree).includes('ReGearLanding'))landingContent=node.initializer;
  if(ts.isVariableDeclaration(node)&&node.name.getText(tree)==='productionEgpuDetail')productionDetail=node.initializer;
  if(ts.isCallExpression(node)&&node.expression.getText(tree)==='useEffect'&&node.arguments[0]?.getText(tree).includes('claimRelaunchOnMount'))relaunchEffect=node.arguments[0];
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
    ButtonItem:'button',TransitionAcknowledgementControl:'guarded-display-ack',egpuPresentation:()=>({}),runtimeDetails:{source:{navigate:()=>{}}}};
  return {value:evaluate(publication,env),calls};
}
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
      if(name.startsWith('.'))return module(new URL(`${name}.tsx`,new URL(path,import.meta.url)));
      return{DialogButton:'button',Focusable:'focus',Field:'field',GamepadButton:{DIR_UP:9,DIR_DOWN:10}};
    });
    return exports;
  }
  const {EgpuModule}=module('../src/quick-access/modules/egpu.tsx');
  const {egpuPresentation}=module('../src/quick-access/modules/egpu-presentation.ts');
  let acknowledgementMounts=0;
  const env={menuFresh:false,payload:{ignored:true},PanelSection:'section',EgpuModule,egpuPresentation,
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
