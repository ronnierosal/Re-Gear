import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=readFileSync(new URL('../src/connection-live-panel.tsx',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
function harness(){
  const h={closed:0,switched:0,effects:[],modals:[]};
  h.status={expiresAt:Date.now()+60000,canSwitch:true,connected:true,phase:'checking',seconds:150,
    rows:[{label:'GPU and driver',state:'waiting'},{label:'No game running',state:'ready'}]};
  h.store={subscribe(){},get:()=>h.status};
  const jsx=(type,props)=>({type,props});
  const imports={
    'react/jsx-runtime':{jsx,jsxs:jsx},
    react:{useSyncExternalStore:(_subscribe,get)=>get(),useEffect:fn=>h.effects.push(fn),useReducer:()=>[0,()=>{}],useRef:current=>({current})},
    '@decky/ui':{Focusable:'focus',ModalRoot:'modal',showModal:node=>{h.modals.push(node);return {Close(){h.closed++;}};}},
    './connection-progress-overlay':{ConnectionProgressOverlay:'overlay'},
    './connection-progress-model':{connectionProgressViewModel:value=>value},
    './connection-panel-style':{connectionPanelCss:''},
    './link-recovery-control':{LinkRecoveryControl:'recovery'},
  };
  const exports={};new Function('exports','require','window',code)(exports,name=>{
    assert.ok(imports[name],`unexpected runtime dependency ${name}`);return imports[name];
  },{});
  h.render=policy=>exports.LivePanel({store:h.store,close:()=>h.closed++,switchTv:()=>h.switched++,...(policy?{policy}:{})});
  h.show=exports.showConnectionLivePanel;return h;
}
function nodes(tree){return !tree||typeof tree!=='object'?[]:Array.isArray(tree)?tree.flatMap(nodes):[tree,...nodes(tree.props?.children)];}
test('production popup preserves live status but omits manual recovery and TV switching',()=>{
  const h=harness();const tree=h.render('production');const overlay=nodes(tree).find(n=>n.type==='overlay');
  assert.equal(overlay.props.onSwitch,undefined);assert.equal(overlay.props.recoveryAction,undefined);
  assert.equal(overlay.props.rows,h.status.rows);assert.equal(overlay.props.connected,true);
  assert.equal(h.switched,0);assert.equal(h.closed,0);assert.equal(h.effects.length,3);
});
test('development popup keeps eligible recovery and fresh explicit TV switch',()=>{
  for(const policy of [undefined,'development']){
    const h=harness();const overlay=nodes(h.render(policy)).find(n=>n.type==='overlay');
    assert.equal(overlay.props.recoveryAction.type,'recovery');assert.equal(overlay.props.recoveryAction.props.eligible,true);
    overlay.props.onSwitch();assert.equal(h.switched,1);assert.equal(h.closed,1);
    h.status.expiresAt=0;overlay.props.onSwitch();assert.equal(h.switched,1);
  }
});
test('popup adapter forwards explicit profile while retaining idempotent close',()=>{
  const h=harness();let closeCalls=0;
  h.show(h.store,()=>h.switched++,()=>closeCalls++,'production');
  const panel=h.modals[0];assert.equal(panel.props.policy,'production');
  panel.props.close();panel.props.close();assert.equal(closeCalls,1);assert.equal(h.closed,1);
});
