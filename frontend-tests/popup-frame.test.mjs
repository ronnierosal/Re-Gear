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
function harness(){
 let now=1000,closed=0,id=0;const timers=new Map(),effects=[],refs=[];let open=false;
 const store={get:()=>status,subscribe:()=>()=>{}};let status={phase:'complete',expiresAt:20000,rows:[],canSwitch:false};
 const setTimeout=(fn,ms)=>{timers.set(++id,{fn,at:now+ms});return id};const clearTimeout=id=>timers.delete(id);
 const hooks={useSyncExternalStore:(_,read)=>read(),useEffect:fn=>effects.push(fn),useReducer:()=>[0,()=>{}],useRef:value=>{const ref={current:value};refs.push(ref);return ref}};
 const make=new Function('hooks','Date','setTimeout','clearTimeout','setInterval','clearInterval',jsx+`const {useSyncExternalStore,useEffect,useReducer,useRef}=hooks;const Focusable='focus',ModalRoot='root',ConnectionProgressOverlay='overlay',connectionPanelCss='';const connectionProgressViewModel=s=>s;`+live.replace(/export /g,'')+';return LivePanel;');
 const Component=make(hooks,{now:()=>now},setTimeout,clearTimeout,()=>0,()=>{});
 const tree=Component({store,close:()=>closed++});refs[1].current={querySelector:()=>open?{}:null};const cleanups=effects.map(fn=>fn());
 return {tree,get closed(){return closed},setStatus:s=>status={...status,...s},details:value=>open=value,cleanup:()=>cleanups.forEach(fn=>fn?.()),advance(ms){const end=now+ms;for(;;){const next=[...timers].filter(([,v])=>v.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!next)break;timers.delete(next[0]);now=next[1].at;next[1].fn()}now=end}};
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
