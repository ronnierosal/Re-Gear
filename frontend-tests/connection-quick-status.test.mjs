import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import ts from "typescript";
// Render the actual component tree with inert host components and hooks.
const source=readFileSync(new URL("../src/connection-quick-status.tsx",import.meta.url),"utf8");
const js=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022,jsx:ts.JsxEmit.React}}).outputText.replace(/^import .*;\r?$/gm,"");
const stubs=`const React={createElement:(type,props,...children)=>({type,props,children})};
const DialogButton="button",ReadinessRow="row",SectionFocus="section",connectionPanelCss="",theme={};
const useSyncExternalStore=(_subscribe,get)=>get(),useEffect=()=>{},useReducer=()=>[0,()=>{}];`;
const {ConnectionQuickStatus}=await import("data:text/javascript;base64,"+Buffer.from(stubs+js).toString("base64"));
const flatten=value=>Array.isArray(value)?value.flatMap(flatten):value&&typeof value==="object"?[value,...flatten(value.children)]:[];
function row(state,expiresAt=Date.now()+10000){
 const store={subscribe(){},get:()=>({expiresAt,title:"Status",rows:[{label:"Display switching ready",state}]})};
 return flatten(ConnectionQuickStatus({store,visible:true,onOpen(){}})).find(node=>node.type==="row");
}
test("quick status exposes the session readiness check and preserves its evidence",()=>{
 for(const state of ["ready","blocked"]){
  const rendered=row(state);assert.ok(rendered,"display switching check must be visible");
  assert.equal(rendered.props.label,"Display switching ready");assert.equal(rendered.props.state,state);
 }
 assert.equal(row("waiting").props.state,"checking");
});
test("stale session readiness never renders confirmed or blocked",()=>{
 for(const state of ["ready","blocked"]){assert.equal(row(state,0).props.state,"waiting");}
});