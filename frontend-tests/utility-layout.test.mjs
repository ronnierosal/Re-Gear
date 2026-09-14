import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import ts from "typescript";
const js=ts.transpileModule(readFileSync(new URL('../src/quick-access/expanded-command-center/utility-layout.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ES2022}}).outputText;
const {normalizeUtilityLayout:normalize,defaultUtilityLayout:defaults,commandCenterUtilityIds,quickActionIds,optionalQuickActionIds}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
test('approved command center button groups stay stable',()=>{
 assert.deepEqual([...commandCenterUtilityIds],['brightness','volume']);
 assert.deepEqual([...quickActionIds],['mic','wifi','overlay','recording']);
 assert.deepEqual([...optionalQuickActionIds],['audio']);
});
test('approved default keeps brightness and volume left and thumb actions right',()=>{
 assert.deepEqual(defaults,[
  {id:'brightness',side:'left'},{id:'volume',side:'left'},
  {id:'mic',side:'right'},{id:'wifi',side:'right'},
  {id:'overlay',side:'right'},{id:'recording',side:'right'},
 ]);
});
test('malformed stored preference restores defaults without sharing mutable entries',()=>{
 const actual=normalize(null);assert.deepEqual(actual,defaults);actual[0].side='right';assert.equal(defaults[0].side,'left');
});
test('brightness and volume can never be moved or removed by customization',()=>{
 assert.deepEqual(normalize([]),[{id:'brightness',side:'left'},{id:'volume',side:'left'}]);
 assert.deepEqual(normalize([{id:'brightness',side:'right'},{id:'volume',side:'right'},{id:'mic',side:'right'}]),[
  {id:'brightness',side:'left'},{id:'volume',side:'left'},{id:'mic',side:'right'}
 ]);
});
test('right rail preserves chosen order and accepts supported optional actions only',()=>{
 assert.deepEqual(normalize([{id:'audio',side:'right'},{id:'recording',side:'right'},{id:'wifi',side:'right'}]),[
  {id:'brightness',side:'left'},{id:'volume',side:'left'},
  {id:'audio',side:'right'},{id:'recording',side:'right'},{id:'wifi',side:'right'}
 ]);
});
test('invalid, duplicate and left-side quick actions cannot corrupt layout',()=>{
 assert.deepEqual(normalize([{id:'mic',side:'right'},{id:'mic',side:'right'},{id:'overlay',side:'left'},{id:'fake',side:'right'},null]),[
  {id:'brightness',side:'left'},{id:'volume',side:'left'},{id:'mic',side:'right'}
 ]);
});

const railCode=ts.transpileModule(readFileSync(new URL('../src/quick-access/expanded-command-center/utility-rail.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ES2022,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React}}).outputText.replace(/^import[\s\S]*?;\s*$/gm,'').replace(/export /g,'');
const React={createElement:(type,props,...children)=>({type,props:{...props,children}})};
const Rail=new Function('React','useRef','useState','useLayoutEffect','defaultUtilityLayout','CommandCenterIcon',railCode+';return UtilityRail;')(React,value=>({current:value}),value=>[value,()=>{}],()=>{},defaults,'icon');
const flatten=value=>Array.isArray(value)?value.flatMap(flatten):value&&typeof value==='object'?[value,...flatten(value.props?.children)]:[];
test('Steam rail callbacks release unhandled directions and normal B, consuming editing B only',()=>{
 let returned=0,focused=false;
 const tree=Rail({side:'left',directions:{up:9,down:10,left:11,right:12},onReturnToGrid:()=>returned++});
 const slider=flatten(tree).find(node=>node.props?.['data-utility-id']==='brightness');
 const input={tagName:'INPUT',disabled:true};
 const wrapper={tagName:'DIV',querySelector:()=>input,ownerDocument:{activeElement:null},focus(){focused=true}};
 const dispatch=(handler,button,target=wrapper)=>{
   const event={detail:{button},target,currentTarget:wrapper,stopped:false,preventDefault(){},stopPropagation(){this.stopped=true}};
   if(handler(event)!==false)event.stopPropagation();
   return event.stopped;
 };
 assert.equal(dispatch(slider.props.onGamepadDirection,11),false,'LEFT keeps native fallback');
 assert.equal(dispatch(slider.props.onGamepadDirection,12),true);assert.equal(returned,1);
 assert.equal(dispatch(slider.props.onCancelButton,2),false,'B outside editing reaches modal Close');
 wrapper.ownerDocument.activeElement=input;
 assert.equal(dispatch(slider.props.onCancelButton,2),true);assert.equal(focused,true);
});

test('native A keeps wrapper focus and the next direction adjusts immediately', async()=>{
 const calls=[];let rawFocus=0,returned=0;
 const tree=Rail({side:'left',directions:{up:9,down:10,left:11,right:12},
   readings:{brightness:{available:true,value:'50%',percent:50}},
   onRequest:async(...args)=>calls.push(args),onReturnToGrid:()=>returned++});
 const slider=flatten(tree).find(node=>node.props?.['data-utility-id']==='brightness');
 const input={tagName:'INPUT',disabled:false,value:'50',focus(){rawFocus++}};
 const wrapper={tagName:'DIV',querySelector:()=>input,ownerDocument:{activeElement:null},focus(){}};
 wrapper.ownerDocument.activeElement=wrapper;
 const event=button=>({detail:{button},target:wrapper,currentTarget:wrapper,prevented:false,stopped:false,preventDefault(){this.prevented=true},stopPropagation(){this.stopped=true}});
 const dispatch=(handler,button)=>{const e=event(button);if(handler(e)!==false){e.stopPropagation();e.preventDefault();}return e;};
 assert.equal(dispatch(slider.props.onOKButton,1).stopped,true);
 assert.equal(rawFocus,0,'native A must not transfer focus out of registered Steam wrapper');
 assert.equal(dispatch(slider.props.onGamepadDirection,9).stopped,true);await new Promise(r=>setImmediate(r));
 assert.deepEqual(calls,[['brightness',53]],'first native direction adjusts, not just restores focus');
 assert.equal(slider.props.onCancelButton(event(2)),true);
 assert.equal(dispatch(slider.props.onCancelButton,2).stopped,false,'next B reaches Close');
 slider.props.onOKButton(event(1));slider.props.onGamepadBlur();assert.equal(dispatch(slider.props.onCancelButton,2).stopped,false,'blur exits native adjustment mode');
 slider.props.onOKButton(event(1));slider.props.onGamepadDirection(event(12));
 assert.equal(returned,1);assert.equal(slider.props.onCancelButton(event(2)),false);
});

function liveRailFixture(){
 const states=[],effects=[];let cursor=0,pendingEffects=[];
 const useState=initial=>{const i=cursor++;if(!(i in states))states[i]=initial;return [states[i],next=>states[i]=typeof next==='function'?next(states[i]):next];};
 const useRef=initial=>useState({current:initial})[0];
 const useLayoutEffect=(callback,deps)=>{const i=cursor++;if(!effects[i]||deps.some((v,j)=>v!==effects[i].deps[j])){pendingEffects.push(()=>{effects[i]?.cleanup?.();effects[i]={deps,cleanup:callback()}})}};
 const Component=new Function('React','useRef','useState','useLayoutEffect','defaultUtilityLayout','CommandCenterIcon',railCode+';return UtilityRail;')(React,useRef,useState,useLayoutEffect,defaults,'icon');
 return {render(props){cursor=0;pendingEffects=[];const tree=Component(props);pendingEffects.forEach(f=>f());return tree;},unmount(){effects.forEach(effect=>effect?.cleanup?.());}};
}

test('requested slider renders immediately, coalesces 3% taps and drag, waits for observed confirmation and rolls back on failure',async()=>{
 const app=liveRailFixture(),calls=[],jobs=[];
 let percent=50,tree;
 const props=()=>({side:'left',directions:{up:9,down:10,left:11,right:12},readings:{brightness:{available:true,value:percent+'%',percent}},onRequest:(...args)=>{calls.push(args);return new Promise((resolve,reject)=>jobs.push({resolve,reject}));}});
 const render=()=>{tree=app.render(props());return tree;};
 const slider=()=>flatten(tree).find(n=>n.props?.['data-utility-id']==='brightness');
 const input=()=>flatten(slider()).find(n=>n.type==='input');
 const wrapper={querySelector:()=>({disabled:false,value:input().props.value}),ownerDocument:{activeElement:null}};
 const event=button=>({target:wrapper,currentTarget:wrapper,detail:{button},preventDefault(){},stopPropagation(){}});
 const tick=async()=>{await new Promise(r=>setImmediate(r));render();render();};
 render();slider().props.onOKButton(event(1));
 for(let i=0;i<3;i++){slider().props.onGamepadDirection(event(9));render();}
 assert.equal(input().props.value,59);assert.match(input().props['aria-valuetext'],/59% requested; observed 50%/);
 assert.deepEqual(calls,[['brightness',53]]);
 percent=53;render();jobs.shift().resolve();await tick();
 assert.equal(input().props.value,59);assert.deepEqual(calls,[['brightness',53],['brightness',59]]);
 jobs.shift().resolve();await tick();assert.equal(input().props.value,59);assert.match(input().props['aria-valuetext'],/requested/);
 percent=59;render();render();assert.equal(input().props['aria-valuetext'],'59%');
 input().props.onChange({currentTarget:{value:'80'}});render();input().props.onChange({currentTarget:{value:'95'}});render();input().props.onChange({currentTarget:{value:'100'}});render();
 assert.equal(input().props.value,100);jobs.shift().resolve();await tick();assert.deepEqual(calls.slice(-2),[['brightness',80],['brightness',100]]);
 jobs.shift().reject(Error('refused'));await tick();assert.equal(input().props.value,59);assert.match(input().props['aria-valuetext'],/Could not apply/);
 percent=99;render();slider().props.onGamepadDirection(event(9));render();assert.equal(input().props.value,100);
 jobs.shift().resolve();percent=100;await tick();percent=1;render();slider().props.onGamepadDirection(event(10));render();assert.equal(input().props.value,0);
 input().props.onChange({currentTarget:{value:'45'}});app.unmount();jobs.shift().resolve();await new Promise(r=>setImmediate(r));assert.notEqual(calls.at(-1)[1],45,'unmount drops queued requests');
});

test('unavailable right slots remain focusable but never dispatch',()=>{
 let calls=0;const tree=Rail({side:'right',readings:{mic:{available:false,value:'Unavailable'}},onRequest:async()=>calls++});
 const mic=flatten(tree).find(n=>n.props?.['data-utility-id']==='mic');
 assert.equal(mic.props.disabled,undefined);assert.equal(mic.props['aria-disabled'],true);mic.props.onClick();assert.equal(calls,0);
});

test('withdrawn capability clears queued targets before a different observation reappears',async()=>{
 const app=liveRailFixture(),jobs=[],calls=[];let reading={available:true,value:'50%',percent:50};
 const render=()=>app.render({side:'left',readings:{brightness:reading},onRequest:(id,n)=>{calls.push(n);return new Promise(resolve=>jobs.push(resolve));}});
 const input=tree=>flatten(tree).find(n=>n.type==='input');
 let tree=render();input(tree).props.onChange({currentTarget:{value:'60'}});tree=render();input(tree).props.onChange({currentTarget:{value:'70'}});
 reading={available:false,value:'Unavailable'};render();render();reading={available:true,value:'20%',percent:20};tree=render();assert.equal(input(tree).props.value,20);
 jobs.shift()();await new Promise(r=>setImmediate(r));assert.deepEqual(calls,[60]);app.unmount();
});
