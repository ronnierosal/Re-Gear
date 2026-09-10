import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import ts from "typescript";
import {autoTdpActivity,autoTdpMessage,validAutoTdpRange} from "../src/auto-tdp-ui.ts";
import {tdpMessage} from "../src/tdp-ui.ts";
import {READY,RUNNING,STOPPING,RUNNING_READBACK_INVALID,CLOCK_INVALID_TERMINAL,MANUAL} from "./qa-auto-tdp-contract-fixtures.test.mjs";
const jsx=(type,props,...children)=>({type,props:{...props,children}});
function renderControls(controller) {
  let cursor=0;const values=[];
  const useState=initial=>{const i=cursor++;if(!(i in values)) values[i]=initial;return [values[i],v=>{values[i]=typeof v==="function"?v(values[i]):v;}];};
  const source=readFileSync(new URL("../src/auto-tdp-controls.tsx",import.meta.url),"utf8");
  const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.React}}).outputText.replace(/^import[^;]*;/gm,"").replace(/export /g,"");
  const names=["React","useState","useEffect","autoTdpActivity","autoTdpMessage","validAutoTdpRange","tdpMessage","ButtonItem","DropdownItem","PanelSectionRow","ToggleField","TdpBenchmarkControls","AutoTdpPreferencesControls"];
  const component=new Function(...names,code+";return AutoTdpControls;")({createElement:jsx,Fragment:"fragment"},useState,()=>{},autoTdpActivity,autoTdpMessage,validAutoTdpRange,tdpMessage,...names.slice(7));
  return ()=>{cursor=0;return component({controller});};
}
const flatten=node=>[node,...(node?.props?.children??[]).flat(Infinity).flatMap(child=>typeof child==="object"&&child!==null?flatten(child):[child])];
const button=(tree,label)=>flatten(tree).find(node=>node?.type==="ButtonItem"&&node.props.children.join("")===label);
const dropdown=(tree,label)=>flatten(tree).find(node=>node?.type==="DropdownItem"&&node.props.label===label);
const base=(auto)=>({manual:{...MANUAL,enabled:true,can_enable:true,code:"tdp.ready"},auto,busy:false,stopping:false,start:()=>{throw Error("unexpected start");},stop:()=>{},refresh:()=>{}});

test("module has no collector and forwards the same shared handle",()=>{
  const source=readFileSync(new URL("../src/quick-access/modules/auto-tdp.tsx",import.meta.url),"utf8");
  const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.React}}).outputText.replace(/^import[^;]*;/gm,"").replace(/export /g,"");
  const module=new Function("React","TdpControls",code+";return AutoTdpModule;")({createElement:jsx},"TdpControls");
  const controller=base(READY);const tree=module({controller});assert.equal(tree.props.controller,controller);assert.equal(tree.props.expanded,true);
});
test("Start requires explicit range choices, and calls the shared guarded action",()=>{
  const calls=[];const controller={...base(READY),start:(...args)=>calls.push(args)};
  const render=renderControls(controller);let tree=render();
  assert.equal(button(tree,"Start Auto TDP").props.disabled,true);
  dropdown(tree,"Minimum power").props.onChange({data:7});dropdown(tree,"Maximum power").props.onChange({data:30});tree=render();
  assert.equal(button(tree,"Start Auto TDP").props.disabled,false);button(tree,"Start Auto TDP").props.onClick();assert.deepEqual(calls,[[60,7,30]]);
  dropdown(tree,"Minimum power").props.onChange({data:20});tree=render();assert.equal(button(tree,"Start Auto TDP").props.disabled,true);
});
test("Stop remains reachable for running and unavailable states; stopping blocks repeats",()=>{
  for(const auto of [null,RUNNING,RUNNING_READBACK_INVALID,CLOCK_INVALID_TERMINAL]) {
    let stopped=0;const render=renderControls({...base(auto),busy:true,stop:()=>stopped++});const tree=render();
    assert.equal(button(tree,"Stop Auto TDP").props.disabled,false);button(tree,"Stop Auto TDP").props.onClick();assert.equal(stopped,1);
    assert.equal(button(tree,"Start Auto TDP").props.disabled,true);
  }
  assert.equal(button(renderControls(base(STOPPING))(),"Stop Auto TDP").props.disabled,true);
});
test("recovery prevents Start; preference loading only edits form and benchmark is disclosed",()=>{
  let starts=0;const controller={...base(READY),manual:{...MANUAL,recovery_required:true},start:()=>starts++};
  const render=renderControls(controller);let tree=render();
  assert.equal(button(tree,"Start Auto TDP").props.disabled,true);
  assert.equal(flatten(tree).some(n=>n?.type==="AutoTdpPreferencesControls"),false);
  assert.equal(flatten(tree).some(n=>n?.type==="TdpBenchmarkControls"),false);
  const toggle=flatten(tree).find(n=>n?.props?.label==="Show saved mode preferences");toggle.props.onChange(true);tree=render();
  const preferences=flatten(tree).find(n=>n?.type==="AutoTdpPreferencesControls");assert.equal(preferences.props.canSave,false);
  preferences.props.onLoad({target_fps:40,minimum_watts:7,maximum_watts:30});assert.equal(starts,0);
  assert.match(flatten(tree).filter(n=>typeof n==="string").join(" "),/Stop keeps the current limit\. Restore returns to saved settings/);
});
