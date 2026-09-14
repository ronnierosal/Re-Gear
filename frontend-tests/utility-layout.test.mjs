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

const railCode=ts.transpileModule(readFileSync(new URL('../src/quick-access/expanded-command-center/utility-rail.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ES2022,jsx:ts.JsxEmit.React}}).outputText.replace(/^import[\s\S]*?;\s*$/gm,'').replace(/export /g,'');
const React={createElement:(type,props,...children)=>({type,props:{...props,children}})};
const Rail=new Function('React','useRef','useState','defaultUtilityLayout','CommandCenterIcon',railCode+';return UtilityRail;')(React,value=>({current:value}),value=>[value,()=>{}],defaults,'icon');
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
 assert.deepEqual(calls,[['brightness',51]],'first native direction adjusts, not just restores focus');
 assert.equal(slider.props.onCancelButton(event(2)),true);
 assert.equal(dispatch(slider.props.onCancelButton,2).stopped,false,'next B reaches Close');
 slider.props.onOKButton(event(1));slider.props.onGamepadBlur();assert.equal(dispatch(slider.props.onCancelButton,2).stopped,false,'blur exits native adjustment mode');
 slider.props.onOKButton(event(1));slider.props.onGamepadDirection(event(12));
 assert.equal(returned,1);assert.equal(slider.props.onCancelButton(event(2)),false);
});
