import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
import { tdpControls, tdpMessage, tdpResultMessage, manualPresetOptions, createCustomTdpDraft, validCustomTdpDraft, retireCustomTdpDraft } from "../src/tdp-ui.ts";

import {tdpCyclePresentation} from "../src/tdp-ui.ts";
const jsx = (type, props, ...children) => ({ type, props: { ...props, children } });
const flatten = node => [node, ...(node?.props?.children ?? []).flat(Infinity)
  .flatMap(child => typeof child === "object" && child !== null ? flatten(child) : [child])];
const control = (tree, type, label) => flatten(tree)
  .find(node => node?.type === type && (node.props.label === label || node.props.children.join("") === label));

function renderControls(controller, initiallyExpanded = true, basic = true) {
  let cursor = 0;
  const values = [];
  const useState = initial => {
    const index = cursor++;
    if (!(index in values)) values[index] = initial;
    return [values[index], value => { values[index] = typeof value === "function" ? value(values[index]) : value; }];
  };
  const effects = [];
  let effectCursor = 0;
  const useEffect = (effect, dependencies) => {
    const index = effectCursor++;
    if (!effects[index] || dependencies.some((value, i) => value !== effects[index].dependencies[i])) {
      effects[index]?.cleanup?.();
      effects[index] = { dependencies, cleanup: effect() };
    }
  };
  const source = readFileSync(new URL("../src/tdp-controls.tsx", import.meta.url), "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React },
  }).outputText.replace(/^import[^;]*;/gm, "").replace(/export /g, "");
  const component = new Function(
    "React", "useState", "useEffect", "useRef", "tdpControls", "tdpMessage", "tdpResultMessage", "manualPresetOptions", "createCustomTdpDraft", "validCustomTdpDraft", "retireCustomTdpDraft",
    "ButtonItem", "DropdownItem", "PanelSection", "PanelSectionRow", "ToggleField",
    "AutoTdpControls", "usePerformance", "ReadableBlock", "tdpCyclePresentation", `${code};return SharedTdpControls;`,
  )(
    { createElement: jsx, Fragment: "fragment" }, useState, useEffect, initial => useState({current:initial})[0],
    tdpControls, tdpMessage, tdpResultMessage, manualPresetOptions, createCustomTdpDraft, validCustomTdpDraft, retireCustomTdpDraft,
    "ButtonItem", "DropdownItem", "PanelSection", "PanelSectionRow", "ToggleField",
    "AutoTdpControls", () => { throw new Error("unexpected standalone controller"); },
    ({label,children})=>jsx("Field",{focusable:true,"aria-label":label},children), tdpCyclePresentation,
  );
  const render = (visible = true) => { cursor = 0; effectCursor = 0; return component({ visible, controller, initiallyExpanded, basic }); };
  render.unmount = () => { for (const effect of effects) effect?.cleanup?.(); };
  return render;
}

const manual = {
  schema_version: 1, enabled: true, can_enable: true, ready: true,
  restore_available: true, recovery_required: false, current_watts: 15,
  minimum_watts: 7, maximum_watts: 30, auto_tdp_available: true,
  code: "tdp.ready", last_result: null,
};

function controller(auto) {
  const calls = [];
  return {
    value: {
      manual, auto, busy: false, stopping: false,
      apply: value => calls.push(["apply", value]),
      restore: () => calls.push(["restore"]),
      setEnabled: value => calls.push(["enabled", value]),
      refresh: () => calls.push(["refresh"]),
    },
    calls,
  };
}

test("Power settings opens Basic with Custom, consent, truthful state and an explicit Advanced toggle",()=>{
 const subject=controller({running:false,stopping:false});const render=renderControls(subject.value);render();let tree=render();
 assert.equal(control(tree,"DropdownItem","Power limit"),undefined);assert.equal(control(tree,"ButtonItem","Apply power limit"),undefined);
 assert.ok(control(tree,"ButtonItem","Custom"));assert.ok(control(tree,"ToggleField","Use Re-Gear power control"));
 const advanced=control(tree,"ButtonItem","Advanced");assert.ok(advanced);advanced.props.onClick();tree=render();
 assert.ok(control(tree,"DropdownItem","Power limit"));assert.ok(control(tree,"ButtonItem","Apply power limit"));
 control(tree,"ButtonItem","Basic").props.onClick();tree=render();assert.equal(control(tree,"DropdownItem","Power limit"),undefined);assert.deepEqual(subject.calls,[]);
 const auto=flatten(tree).find(n=>n?.type==="AutoTdpControls");assert.ok(auto);assert.equal(auto.props.advanced,false);
});
test("Basic preserves unknown, recovery and Auto lock guidance without exposing tuning",()=>{
 for(const status of [null,{...manual,recovery_required:true},{...manual,code:"tdp.conflict",ready:false}]){
  const subject=controller({running:true,stopping:false});subject.value.manual=status;const render=renderControls(subject.value);render();const tree=render();
  const words=flatten(tree).filter(n=>typeof n==="string").join(" ");assert.match(words,/configured limit, not measured/);assert.match(words,/Stop Auto TDP/);
  assert.equal(control(tree,"DropdownItem","Power limit"),undefined);assert.deepEqual(subject.calls,[]);
  if(status?.recovery_required)assert.ok(control(tree,"ButtonItem","Restore previous power settings"));
 }
});
test('Basic Custom remains local and Advanced navigation retires its captured Apply',()=>{
 const subject=controller({running:false,stopping:false});const render=renderControls(subject.value);render();let tree=render();
 control(tree,'ButtonItem','Custom').props.onClick();tree=render();const apply=control(tree,'ButtonItem','Apply Custom').props.onClick;
 control(tree,'ButtonItem','+1 W').props.onClick();tree=render();assert.deepEqual(subject.calls,[]);
 control(tree,'ButtonItem','Cancel').props.onClick();apply();assert.deepEqual(subject.calls,[]);
 tree=render();control(tree,'ButtonItem','Custom').props.onClick();tree=render();const second=control(tree,'ButtonItem','Apply Custom').props.onClick;
 control(tree,'ButtonItem','Advanced').props.onClick();second();assert.deepEqual(subject.calls,[]);
});
test('Basic reports requested and pending mode separately from committed readback',()=>{
 const subject=controller({running:false,stopping:false,enabled:false});subject.value.cycleSelected='Performance';subject.value.cyclePending='Performance';
 const render=renderControls(subject.value);render();const words=flatten(render()).filter(n=>typeof n==='string').join(' ');
 assert.match(words,/Applying Performance/);assert.match(words,/Selected Performance/);assert.match(words,/Last checked: Balanced 15 W/);assert.doesNotMatch(words,/Last checked: Performance/);assert.deepEqual(subject.calls,[]);
});
