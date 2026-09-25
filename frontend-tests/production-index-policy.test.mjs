import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const source=readFileSync(new URL('../src/index.tsx',import.meta.url),'utf8');
const tree=ts.createSourceFile('index.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let publication,landingContent;
function visit(node){
  if(ts.isCallExpression(node)&&node.expression.getText(tree)==='runtimeDetails.publish')publication=node.arguments[0];
  if(ts.isPropertyAssignment(node)&&node.name.getText(tree)==='content'&&node.initializer.getText(tree).includes('ReGearLanding'))landingContent=node.initializer;
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
    egpuDetail:'egpu',diagnosticDetail:'diagnostic',displayDetail:'display',wrapDetail:value=>value,
    React:{createElement:()=>({node:true}),Fragment:'fragment'},PanelSection:'section',EgpuModule:'egpu',
    ButtonItem:'button',egpuPresentation:()=>({}),runtimeDetails:{source:{navigate:()=>{}}}};
  return {value:evaluate(publication,env),calls};
}
test('production runtime publishes only eGPU content and denies retained hidden callbacks',()=>{
  const {value,calls}=state('production');
  assert.deepEqual(Object.entries(value.views).filter(([,node])=>node!==null).map(([key])=>key),['egpu']);
  for(const action of ['shutdown','handheld','sleepConnected']){
    assert.equal(value[action].available,false);
    value[action].request();
  }
  assert.deepEqual(calls,[]);
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
