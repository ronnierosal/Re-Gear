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
    ButtonItem:'button',egpuPresentation:()=>({}),runtimeDetails:{source:{navigate:()=>{}}}};
  return {value:evaluate(publication,env),calls};
}
test('production runtime publishes only eGPU content and denies retained hidden callbacks',()=>{
  const {value,calls}=state('production');
  assert.deepEqual(Object.entries(value.views).filter(([,node])=>node!==null).map(([key])=>key),['egpu']);
  assert.equal(value.views.egpu,'readonly-egpu');
  for(const action of ['shutdown','handheld','sleepConnected']){
    assert.equal(value[action].available,false);
    value[action].request();
  }
  assert.deepEqual(calls,[]);
});
test('production does not consume or launch a retained development game request',()=>{
  let calls=0;
  const env={buildProfile:'production',quickAccessVisible:true,claimRelaunchOnMount:()=>calls++,liveGameClosePorts:()=>({})};
  evaluate(relaunchEffect,env)();assert.equal(calls,0);
  evaluate(relaunchEffect,{...env,buildProfile:'development'})();assert.equal(calls,1);
});
test('real production eGPU detail mounts observation rows without controls or navigation',()=>{
  const jsx=(type,props)=>({type,props});
  function module(path){
    const exports={};
    const code=ts.transpileModule(readFileSync(new URL(path,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
    new Function('exports','require',code)(exports,name=>name==='react/jsx-runtime'?{jsx,jsxs:jsx}:{DialogButton:'button',Focusable:'focus'});
    return exports;
  }
  const {EgpuModule}=module('../src/quick-access/modules/egpu.tsx');
  const {egpuPresentation}=module('../src/quick-access/modules/egpu-presentation.ts');
  const env={menuFresh:false,payload:{ignored:true},PanelSection:'section',EgpuModule,egpuPresentation,
    React:{createElement:(type,props,...children)=>jsx(type,{...props,children})}};
  function mount(node){
    if(Array.isArray(node))return node.map(mount);
    if(!node||typeof node!=='object')return node;
    if(typeof node.type==='function')return mount(node.type(node.props));
    assert.equal(Object.keys(node.props??{}).some(key=>/^on[A-Z]/.test(key)),false);
    assert.notEqual(node.type,'button');
    return {...node,props:{...node.props,children:mount(node.props?.children)}};
  }
  const rendered=JSON.stringify(mount(evaluate(productionDetail,env)));
  assert.match(rendered,/Unknown/);
  assert.doesNotMatch(rendered,/Automatic TV docking|Configure docking|Troubleshoot|onClick|ToggleField|recovery is still available/);
});
test('development retains existing runtime views and actions',()=>{
  const {value,calls}=state('development');
  assert.deepEqual(Object.keys(value.views),['egpu','egpu-config','diagnostics','display']);
  for(const action of ['shutdown','handheld','sleepConnected']){
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
