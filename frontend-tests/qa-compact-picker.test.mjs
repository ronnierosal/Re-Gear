import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const compile = (path, jsx = false) => ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React },
}).outputText.replace(/^import[^;]*;$/gm, "");
const mock = `const React = {createElement:(type,props,...children)=>({type,props:props??{},children:children.flat()})};
const ButtonItem="ButtonItem",DropdownItem="DropdownItem",PanelSection="PanelSection",PanelSectionRow="PanelSectionRow";
const useState=value=>[value,()=>{}],useEffect=()=>{};`;
const code = mock + compile("../src/tdp-ui.ts") + compile("../src/quick-access/compact-picker.tsx");
const { TdpPicker, DisplayPicker } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
const find = (node, type) => [node, ...(node?.children ?? []).flatMap(n => typeof n === "object" && n ? find(n,type) : [])].filter(n => n?.type === type);
const ready = { enabled: true, ready: true, can_enable: true, current_watts: 12, minimum_watts: 10, maximum_watts: 14, recovery_required: false };
test("compact power choices use device limits and guarded Apply", () => {
  let applied;
  const tree = TdpPicker({status:ready,busy:false,onApply:w=>applied=w,onConfigure:()=>{}});
  assert.deepEqual(find(tree,"DropdownItem")[0].props.rgOptions.map(o=>o.data),[10,11,12,13,14]);
  find(tree,"ButtonItem")[0].props.onClick(); assert.equal(applied,12);
});
test("unknown, recovery and busy power states cannot apply", () => {
  for (const [status,busy] of [[null,false],[{...ready,recovery_required:true},false],[ready,true]]) {
    let applied=false;
    const tree=TdpPicker({status,busy,onApply:()=>applied=true,onConfigure:()=>{}});
    const button=find(tree,"ButtonItem")[0]; assert.equal(button.props.disabled,true);
    button.props.onClick(); assert.equal(applied,false);
  }
});
test("a blocked display picker never dispatches", () => {
  let calls=0;
  const tree=DisplayPicker({current:"Unknown",action:{disabled:true,title:"Unavailable",description:"Check state"},onSwitch:()=>calls++,onConfigure:()=>{}});
  find(tree,"ButtonItem")[0].props.onClick(); assert.equal(calls,0);
});
