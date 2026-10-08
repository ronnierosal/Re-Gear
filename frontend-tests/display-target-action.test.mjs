import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source=readFileSync(new URL("../src/quick-access/expanded-command-center/display-target-action.ts",import.meta.url),"utf8").replace(/^import .*;$/gm,"");
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {displayTargetActionTile}=await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);

test("display target describes the next destination with matching artwork",()=>{
 const handheld=displayTargetActionTile({target:"ally",available:true,reason:"Guarded handheld return"});
 assert.deepEqual([handheld.id,handheld.title,handheld.value,handheld.artworkControlId],["display-target","Switch to Handheld","Ready","handheld"]);
 const tv=displayTargetActionTile({target:"tv",available:true,reason:"Guarded TV switch"});
 assert.deepEqual([tv.id,tv.title,tv.value,tv.artworkControlId],["display-target","Switch to TV","Ready","display-target"]);
});

test("unknown and blocked display targets remain visible and unavailable",()=>{
 const unknown=displayTargetActionTile();
 assert.deepEqual([unknown.id,unknown.title,unknown.value,unknown.tone],["display-target","Switch Display","Unavailable","unavailable"]);
 const blocked=displayTargetActionTile({target:"tv",available:false,reason:"Resolve the prior operation"});
 assert.equal(blocked.title,"Switch to TV");assert.equal(blocked.value,"Unavailable");assert.equal(blocked.detail,"Resolve the prior operation");
});

test("verified connection marks status while preserving destination and action facts",()=>{
 for(const target of ["ally","tv"]){
  for(const available of [true,false]){
   const state={target,available,reason:"Existing guard"};
   const plain=displayTargetActionTile(state);
   const marked=displayTargetActionTile({...state,egpuConnected:true});
   assert.equal(marked.value,`${plain.value} · eGPU connected`);
   assert.deepEqual({...marked,value:plain.value},plain);
  }
 }
});

test("missing and invalid connection evidence never marks or executes accessors",()=>{
 const base={target:"tv",available:true,reason:"Existing guard"};
 const plain=displayTargetActionTile(base);
 for(const egpuConnected of [false,null,undefined,"true",1,{},[]]){
  assert.deepEqual(displayTargetActionTile({...base,egpuConnected}),plain);
 }
 const inherited=Object.assign(Object.create({egpuConnected:true}),base);
 assert.deepEqual(displayTargetActionTile(inherited),plain);
 let reads=0;
 const accessor=Object.defineProperty({...base},"egpuConnected",{get(){reads++;return true;}});
 assert.deepEqual(displayTargetActionTile(accessor),plain);
 assert.equal(reads,0);
 assert.deepEqual(displayTargetActionTile({target:null,available:true,reason:"Unknown",egpuConnected:true}),displayTargetActionTile({target:null,available:true,reason:"Unknown"}));
});

test("withdrawn connection evidence immediately removes the mark",()=>{
 const state={target:"ally",available:true,reason:"Existing guard",egpuConnected:true};
 assert.equal(displayTargetActionTile(state).value,"Ready · eGPU connected");
 for(const egpuConnected of [null,false,undefined]){
  assert.equal(displayTargetActionTile({...state,egpuConnected}).value,"Ready");
 }
 assert.equal(displayTargetActionTile().value,"Unavailable");
});

test("actual shell renders connection status and keeps display dispatch unchanged",async()=>{
 const compile=name=>ts.transpileModule(readFileSync(new URL(`../src/quick-access/expanded-command-center/${name}`,import.meta.url),"utf8"),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React}}).outputText.replace(/^import .*;$/gm,"");
 const fixture=`
 const React={createElement(type,props,...children){return {type,props:{...props,children}};}};
 const useState=v=>[v,()=>{}],useRef=v=>({current:v}),useLayoutEffect=()=>{};
 const UtilityIcon='icon',UtilityRail='rail',CommandCenterIcon='icon',expandedStyles='',brandIcon='';
 ${["model.ts","control-registry.ts","utility-layout.ts","layout-preferences.ts","button-catalog.ts","customization-input.ts","layout-customization.tsx","footer-hints.tsx","shell.tsx"].map(compile).join("\n")}
 export function render(tile,onAction){return ExpandedCommandCenter({initialTab:'egpu',tiles:{egpu:[tile]},onClose(){},onAction});}
 `;
 const app=await import(`data:text/javascript;base64,${Buffer.from(fixture).toString("base64")}`);
 const nodes=n=>!n||typeof n!=="object"?[]:Array.isArray(n)?n.flatMap(nodes):[n,...nodes(n.props?.children)];
 const text=n=>n==null||typeof n==="boolean"?"":Array.isArray(n)?n.map(text).join(" "):typeof n==="object"?text(n.props?.children):String(n);
 let calls=0;
 for(const target of ["ally","tv"]){
  for(const egpuConnected of [true,false,null,undefined]){
   const tile=displayTargetActionTile({target,available:true,reason:"Existing guard",egpuConnected});
   const tree=app.render(tile,(tab,action)=>{assert.equal(tab,"egpu");assert.equal(action,tile);calls++;return true;});
   const button=nodes(tree).find(n=>n.props?.['data-ec-control']==='display-target');
   assert.ok(button);
   assert.match(text(button),new RegExp(tile.title));
   assert.equal(text(button).includes("eGPU connected"),egpuConnected===true);
   assert.ok(button.props['aria-label'].includes(tile.value));
   button.props.onClick();
  }
 }
 assert.equal(calls,8);
});
