import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

// Execute the actual module at the native primitive boundary. Field registration
// and focus events are checked here; Steam's spatial engine still needs device QA.
function loadModule(url){
 const exports={};
 const jsx=(type,props)=>({type,props:props??{}});
 const code=ts.transpileModule(readFileSync(url,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
 new Function('exports','require',code)(exports,name=>{
  if(name==='react/jsx-runtime')return{jsx,jsxs:jsx};
  if(name==='@decky/ui')return{Field:'Field',Focusable:'Focusable',DialogButton:'DialogButton',GamepadButton:{DIR_UP:9,DIR_DOWN:10}};
  if(name.startsWith('.'))return loadModule(new URL(`${name}.tsx`,url));
  throw new Error(`Unexpected runtime dependency: ${name}`);
 });
 return exports;
}
const load=()=>loadModule(new URL('../src/quick-access/modules/egpu.tsx',import.meta.url)).EgpuModule;
function mount(node){
 if(Array.isArray(node))return node.flatMap(mount);
 if(!node||typeof node!=='object')return[];
 if(typeof node.type==='function')return mount(node.type(node.props));
 return[node,...mount(node.props.children)];
}
const unknown={text:'Unknown',known:false,verified:false};
const presentation={model:null,connection:unknown,renderGpu:unknown,displayConnected:unknown,displayActive:unknown,session:unknown,game:unknown,lifecycle:unknown,disconnect:{text:'Unknown',reason:'Re-Gear cannot confirm physical unplug clearance.',safeClaim:false},recovery:{reachable:true,note:null}};

test('native eGPU status registers ordered read-only leaves above Configure docking',()=>{
 const tree=load()({presentation});
 const fields=mount(tree).filter(n=>n.type==='Field');
 assert.equal(fields.length,8,'seven independent readings and safety notice must be controller stops');
 assert.deepEqual(fields.slice(0,7).map(n=>n.props['aria-label'].split(':')[0]),['Connection','Rendering','External display','Display output','Session','Game','Lifecycle']);
 const controls=[...fields,{type:'Configure docking'}];
 let index=controls.length-1;
 assert.equal(controls[--index].type,'Field','Up reaches information before leaving the detail');
 const upwards=[];while(index>=0)upwards.push(controls[index--]);
 assert.equal(upwards.length,8);
 while(index<controls.length-1)assert.ok(controls[++index]);
 assert.equal(controls[index].type,'Configure docking','Down returns to the action');
 for(const field of fields){
  assert.equal(field.props.focusable,true);
  assert.equal(field.props.highlightOnFocus,false);
  assert.equal(typeof field.props.onGamepadDirection,'function','direction handler scrolls information only');
  for(const handler of ['onClick','onOKButton','onActivate','onCancelButton'])assert.equal(field.props[handler],undefined,handler);
 }
 assert.equal(tree.type,'Focusable');assert.equal(tree.props['flow-children'],'vertical');
});

test('every focused reading reveals itself without activating recovery or mutating state',()=>{
 let recovery=0;
 const fields=mount(load()({presentation,onOpenRecovery:()=>recovery++})).filter(n=>n.type==='Field');
 const previous=globalThis.HTMLElement;
 class Element{closest(){return null;}scrollIntoView(options){this.options=options;}}
 globalThis.HTMLElement=Element;
 try{for(const field of fields){const target=new Element();field.props.onGamepadFocus({currentTarget:target});assert.deepEqual(target.options,{block:'nearest',inline:'nearest'});}}
 finally{globalThis.HTMLElement=previous;}
 assert.equal(recovery,0);assert.equal(presentation.disconnect.safeClaim,false);
 const buttons=mount(load()({presentation,onOpenRecovery:()=>recovery++})).filter(n=>n.type==='DialogButton');
 assert.equal(buttons.length,1);buttons[0].props.onClick();assert.equal(recovery,1,'touch/controller action remains explicit');
});

test('native eGPU first reading Up reveals its section title without adding a heading focus stop',()=>{
 const fields=mount(load()({presentation})).filter(n=>n.type==='Field');assert.equal(fields.length,8);
 const previous=globalThis.HTMLElement;class Element{};globalThis.HTMLElement=Element;
 try{
  const area=new Element();area.scrollTop=53;area.getBoundingClientRect=()=>({top:0,bottom:100,height:100});
  const target=new Element();target.closest=()=>area;target.getBoundingClientRect=()=>({top:57-area.scrollTop,bottom:77-area.scrollTop,height:20});area.querySelector=()=>target;
  let consumed=0;const event={currentTarget:target,detail:{button:9},preventDefault(){consumed++},stopPropagation(){}};
  assert.equal(fields[0].props.onGamepadDirection(event),true);assert.equal(area.scrollTop,0);assert.equal(consumed,1);
  assert.equal(fields[0].props.onGamepadDirection(event),false,'Up exits after title is visible');
  event.detail.button=10;assert.equal(fields[0].props.onGamepadDirection(event),false,'Down retains ordinary next-reading navigation');
 }finally{globalThis.HTMLElement=previous;}
});

test('unavailable and long unverified readings remain focusable and independently labeled',()=>{
 const p={...presentation,connection:{text:'Observed connection with a long diagnostic reason',known:true,verified:false},recovery:{reachable:true,note:'Recovery is still available when readings are missing.'}};
 const fields=mount(load()({presentation:p})).filter(n=>n.type==='Field');
 assert.equal(fields.length,9);assert.match(fields[0].props['aria-label'],/observed/i);
 assert.match(fields.at(-1).props['aria-label'],/Recovery/);
});
