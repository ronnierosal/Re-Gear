import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync,existsSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import ts from 'typescript';
const root=resolve(import.meta.dirname,'../src');
const jsx=(type,props)=>({type,props:props??{}});
function load(path){const exports={};const code=ts.transpileModule(readFileSync(path,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;new Function('exports','require',code)(exports,name=>{
 if(name==='react/jsx-runtime')return{jsx,jsxs:jsx};
 if(name==='react')return{useEffect:()=>{},useRef:()=>({current:null}),useState:v=>[v,()=>{}]};
 if(name==='@decky/ui')return{Field:'Field',Focusable:'Focusable',GamepadButton:{DIR_UP:9,DIR_DOWN:10},DialogButton:'button',Navigation:{}};
 if(name.startsWith('.')){const base=resolve(dirname(path),name);for(const ext of ['.tsx','.ts'])if(existsSync(base+ext))return load(base+ext);}
 throw Error(name);
});return exports;}
function mount(n){if(Array.isArray(n))return n.flatMap(mount);if(!n||typeof n!=='object')return[];if(typeof n.type==='function')return mount(n.type(n.props));return[n,...mount(n.props.children)];}
const unknown={text:'Unknown',known:false};
test('controller information is grouped into read-only native leaves before Back',()=>{
 const {ControllerModule}=load(resolve(root,'quick-access/modules/controller.tsx'));
 const nodes=mount(ControllerModule({presentation:{reason:'Unavailable',builtin:unknown,external:unknown,shortcut:unknown,precisionNote:'Unverified',planned:['Player order','Priority']}}));
 const fields=nodes.filter(n=>n.type==='Field');assert.equal(fields.length,6);
 assert.deepEqual(fields.slice(1,4).map(n=>n.props['aria-label']),['Built-in controls: Unknown','External controller: Unknown','Shortcut input: Unknown']);
 for(const f of fields)for(const key of ['onClick','onActivate','onOKButton','onCancelButton'])assert.equal(f.props[key],undefined);
});
test('shared status and notices are readable leaves without turning sections/actions into stops',()=>{
 const m=load(resolve(root,'quick-access/expanded-command-center/detail-ui.tsx'));
 for(const node of [m.CommandStatusRow({label:'Display',value:'Unknown',detail:'Long reason'}),m.CommandNotice({title:'Keep connected',children:'No clearance'})]){
  const fields=mount(node).filter(n=>n.type==='Field');assert.equal(fields.length,1);assert.equal(fields[0].props.focusable,true);
 }
 assert.equal(mount(m.CommandSection({title:'Actions',children:jsx('button',{children:'Apply'})})).filter(n=>n.type==='Field').length,0);
});
test('long reading scrolls in bounded steps before directional focus leaves it',()=>{
 const {ReadableBlock}=load(resolve(root,'quick-access/readable-block.tsx'));
 const field=mount(ReadableBlock({label:'Long warning',children:'Text'})).find(n=>n.type==='Field');
 const previous=globalThis.HTMLElement;class Element{};globalThis.HTMLElement=Element;
 try{const area=new Element();area.scrollTop=0;area.getBoundingClientRect=()=>({top:0,bottom:100,height:100});
 const target=new Element();target.closest=()=>area;target.getBoundingClientRect=()=>({top:-area.scrollTop,bottom:300-area.scrollTop,height:300});
 let prevented=0;const event={currentTarget:target,detail:{button:10},preventDefault(){prevented++},stopPropagation(){}};
 assert.equal(field.props.onGamepadDirection(event),true);assert.equal(area.scrollTop,65);assert.equal(prevented,1);
 area.scrollTop=200;assert.equal(field.props.onGamepadDirection(event),false,'Down exits at the end');
 event.detail.button=9;assert.equal(field.props.onGamepadDirection(event),true);assert.equal(area.scrollTop,135);
 area.getBoundingClientRect=()=>({top:0,bottom:0,height:0});assert.equal(field.props.onGamepadDirection(event),false,'hidden scroll area cannot consume direction forever');
 for(const key of ['onClick','onActivate','onCancelButton'])assert.equal(field.props[key],undefined);
 }finally{globalThis.HTMLElement=previous;}
});
