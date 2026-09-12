import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const compile=name=>ts.transpileModule(readFileSync(new URL('../src/'+name,import.meta.url),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.ES2022}}).outputText.replace(/^import .*;$/gm,'');
const jsx=`const React={createElement:(type,props,...children)=>({type,props:{...props,children}})};`;
const {EgpuConfirmModal:render}=await import('data:text/javascript;base64,'+Buffer.from(jsx+`const ConfirmModal='native-confirm',brandIcon='logo';`+compile('egpu-confirm-modal.tsx')).toString('base64'));
test('native confirmation retains every action and lifecycle prop without interception',()=>{
 const callback=()=>{};
 for(const config of [{},{bAlertDialog:true},{bDestructiveWarning:true},{onMiddleButton:callback},{strMiddleButtonText:'Label only'},{bOKDisabled:true,bCancelDisabled:true,bMiddleDisabled:true}]){
  const props={...config,onOK:callback,onCancel:callback,closeModal:callback,onEscKeypress:callback,bDisableBackgroundDismiss:true,bHideCloseIcon:true};
  const tree=render(props);assert.equal(tree.type,'native-confirm');for(const [key,value] of Object.entries(props))assert.equal(tree.props[key],value,key);
 }
});
test('native description and game consent content remain visible unchanged',()=>{
 const body={consent:'game close'};const tree=render({strTitle:'Shutdown?',strDescription:'Keep cable attached',children:body});
 const content=tree.props.children[1];assert.equal(content.props.children[0].props.children[0],'Keep cable attached');assert.equal(content.props.children[1],body);
});
// Execute the real component effect and handlers with deterministic clock/hooks.
const live=compile('connection-live-panel.tsx');
function harness(options={}){
 let now=1000,closed=0,id=0;let animation;const detailsNode={open:false};const timers=new Map(),effects=[],refs=[];let open=false;
 const store={get:()=>status,subscribe:()=>()=>{}};let status={phase:'complete',expiresAt:20000,rows:[],canSwitch:false};
 const setTimeout=(fn,ms)=>{timers.set(++id,{fn,at:now+ms});return id};const clearTimeout=id=>timers.delete(id);
 const hooks={useSyncExternalStore:(_,read)=>read(),useEffect:fn=>effects.push(fn),useReducer:()=>[0,()=>{}],useRef:value=>{const ref={current:value};refs.push(ref);return ref}};
 const make=new Function('hooks','Date','setTimeout','clearTimeout','setInterval','clearInterval','window',jsx+`const {useSyncExternalStore,useEffect,useReducer,useRef}=hooks;const Focusable='focus',ModalRoot='root',ConnectionProgressOverlay='overlay',LinkRecoveryControl='recovery',connectionPanelCss='';const connectionProgressViewModel=s=>s;`+live.replace(/export /g,'')+';return LivePanel;');
 const Component=make(hooks,{now:()=>now},setTimeout,clearTimeout,()=>0,()=>{},{matchMedia:()=>({matches:!!options.reducedMotion})});
 const tree=Component({store,close:()=>closed++});refs[1].current={querySelector:selector=>selector==='details[open]'?(open||detailsNode.open?{}:null):selector==='details'?detailsNode:options.animate?{animate:()=>{animation={cancel:()=>{animation.cancelled=true}};return animation}}:null};const cleanups=effects.map(fn=>fn());
 return {tree,get animation(){return animation},get detailsOpen(){return detailsNode.open},get closed(){return closed},setStatus:s=>status={...status,...s},details:value=>open=value,cleanup:()=>cleanups.forEach(fn=>fn?.()),advance(ms){const end=now+ms;for(;;){const next=[...timers].filter(([,v])=>v.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!next)break;timers.delete(next[0]);now=next[1].at;next[1].fn()}now=end}};
}
test('confirmed success dwells then closes without user confirmation',()=>{const h=harness();h.advance(3499);assert.equal(h.closed,0);h.advance(1);assert.equal(h.closed,1)});
test('freshness loss and operation change prevent success dismissal',()=>{for(const status of [{expiresAt:4500},{phase:'checking'}]){const h=harness();h.setStatus(status);h.advance(10000);assert.equal(h.closed,0)}});
test('expanded diagnostics hold dismissal until inspection ends',()=>{const h=harness();h.details(true);h.advance(5000);assert.equal(h.closed,0);h.details(false);h.advance(500);assert.equal(h.closed,1)});
test('pointer, keyboard, focus and native controller handlers each renew the quiet dwell',()=>{
 for(const event of ['onPointerDownCapture','onKeyDownCapture','onFocusCapture','onGamepadFocus','onGamepadDirection','onButtonDown']){
  const h=harness();h.advance(3000);h.tree.props.children[1].props[event]();h.advance(3000);assert.equal(h.closed,0,event);h.advance(500);assert.equal(h.closed,1,event);
 }
});
test('unmount cancels scheduled success dismissal',()=>{const h=harness();h.cleanup();h.advance(10000);assert.equal(h.closed,0)});


test('native options toggles diagnostics without hiding or dispatching',()=>{const h=harness();h.tree.props.children[1].props.onOptionsButton();assert.equal(h.detailsOpen,true);h.advance(4000);assert.equal(h.closed,0);h.tree.props.children[1].props.onOptionsButton();assert.equal(h.detailsOpen,false)});
test('Hide uses one bounded exit animation; reduced motion closes immediately',()=>{
 const h=harness({animate:true});h.tree.props.onCancel();h.tree.props.onCancel();assert.equal(h.closed,0);h.animation.onfinish();assert.equal(h.closed,1);
 const reduced=harness({animate:true,reducedMotion:true});reduced.tree.props.onCancel();assert.equal(reduced.closed,1);assert.equal(reduced.animation,undefined);
});
test('unmount cancels an in-flight Hide animation',()=>{const h=harness({animate:true});h.tree.props.onCancel();h.cleanup();assert.equal(h.animation.cancelled,true);assert.equal(h.closed,0)});

const {ConnectionProgressOverlay:renderProgress}=await import('data:text/javascript;base64,'+Buffer.from(jsx+`const useRef=()=>({current:null}),DialogButton='button',PopupFrame='frame',PopupStateIcon='status',CommandCenterIcon='icon',handheldIcon='repo-handheld',tvIcon='repo-tv';`+compile('connection-progress-overlay.tsx')).toString('base64'));
const flatten=value=>Array.isArray(value)?value.flatMap(flatten):value&&typeof value==='object'?[value,...flatten(value.props?.children),...flatten(value.props?.footer)]:[];
test('flow never treats TV detection or a single GPU check as completed switching',()=>{
 const rows=[{key:'gpu',label:'GPU and driver',state:'ready'},{key:'hdmi',label:'TV HDMI detected',state:'ready'}];
 const tree=renderProgress({rows,phase:'connecting',deviceLabel:'eGPU',onHide(){}});
 const lines=flatten(tree).filter(n=>n.props?.className==='rg-flow-line');assert.deepEqual(lines.map(n=>n.props['data-ready']),[false,false]);assert.ok(JSON.stringify(tree).includes('Detected; not active'));
 const done=renderProgress({rows,phase:'ready',deviceLabel:'eGPU',onHide(){}});assert.equal(flatten(done).filter(n=>n.props?.className==='rg-flow-line')[1].props['data-ready'],true);
});
test('absent core observations remain unavailable and original long reasons stay in details',()=>{
 const detail='A long backend reason '.repeat(20);const tree=renderProgress({rows:[],phase:'connecting',deviceLabel:'eGPU',detail,onHide(){}});
 assert.equal(flatten(tree).filter(n=>n.props?.className==='rg-core-row').length,5);
 assert.ok(JSON.stringify(tree).includes('Unavailable'));assert.ok(flatten(tree).some(n=>n.type==='p'&&n.props.children[0]===detail));
});
