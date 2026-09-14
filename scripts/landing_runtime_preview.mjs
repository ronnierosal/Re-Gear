// Actual plugin composition with React/DOM and simulated Decky/RPC ports. No device actions.
import {createRequire} from 'node:module';
import {resolve,join} from 'node:path';
import {readFileSync,readdirSync,mkdirSync,writeFileSync} from 'node:fs';
import {createServer} from 'node:http';
import assert from 'node:assert/strict';
const root=resolve('.'),out=resolve('out/landing-runtime-preview');mkdirSync(out,{recursive:true});
const runtime='C:/Users/SLDD/AppData/Local/Temp/regear-qa-preview-runtime/node_modules';
const require=createRequire(join(runtime,'fixture.cjs')),esbuild=require('esbuild');
const ts=require(join(root,'node_modules/typescript'));
const names=new Set();function scan(dir){for(const d of readdirSync(dir,{withFileTypes:true})){const p=join(dir,d.name);if(d.isDirectory())scan(p);else if(/\.tsx?$/.test(p)){const tree=ts.createSourceFile(p,readFileSync(p,'utf8'),ts.ScriptTarget.Latest,true);for(const n of tree.statements)if(ts.isImportDeclaration(n)&&n.moduleSpecifier.text==='@decky/ui'&&!n.importClause?.isTypeOnly)for(const e of n.importClause?.namedBindings?.elements??[])if(!e.isTypeOnly)names.add(e.propertyName?.text??e.name.text);}}}scan(join(root,'src'));
const ui=`import React from 'react';const button=React.forwardRef(({children,onOKButton,onCancelButton,preferredFocus,...props},ref)=>{const own=React.useRef(null);React.useImperativeHandle(ref,()=>own.current);React.useEffect(()=>{const node=own.current;const ok=e=>onOKButton?onOKButton(e):node.click();node.addEventListener('gamepadok',ok);return()=>node.removeEventListener('gamepadok',ok);},[onOKButton]);return React.createElement('button',{...props,ref:own},children)});const focusable=React.forwardRef(({children,onCancelButton,noFocusRing,preferredFocus,...props},ref)=>{const own=React.useRef(null);React.useImperativeHandle(ref,()=>own.current);React.useEffect(()=>{const node=own.current;const cancel=e=>onCancelButton?.(e);node.addEventListener('gamepadcancel',cancel);return()=>node.removeEventListener('gamepadcancel',cancel);},[onCancelButton]);return React.createElement('div',{...props,ref:own},children)});const primitive=React.forwardRef(({children,...props},ref)=>React.createElement('div',{ref},children));\n`+[...names].map(n=>`export const ${n}=${n==='showModal'?`(node)=>{window.lastModal=node;window.modalShows=(window.modalShows??0)+1;const root=["Shutdown","Safe Disconnect"].includes(node.props.strTitle)?window.operationRoot:window.modalRoot;root.render(node);return {Close(){root.render(null)}}}`:n==='Navigation'?'{NavigateToExternalWeb(url){window.guideUrl=url}}':n==='Button'||n==='DialogButton'?'button':n==='Focusable'?'focusable':n==='findModuleExport'?'()=>undefined':n==='GamepadButton'?'{DIR_UP:9,DIR_DOWN:10,DIR_LEFT:11,DIR_RIGHT:12,OPTIONS:4}':n==='staticClasses'||n.endsWith('Classes')?'{}':n.startsWith('use')?'()=>false':'primitive'};`).join('\n');
const fixture=JSON.parse(readFileSync('tests/fixtures/portable.json','utf8'));
const api=`import React from 'react';export const definePlugin=f=>f;export const toaster={toast(value){(window.reports??=[]).push(value)}};export const routerHook={addPatch(){return ()=>{}},removePatch(){},addGlobalComponent(name,C){window.registrations++;window.runtimeRoot.render(React.createElement(C));},removeGlobalComponent(){window.removals++;window.runtimeRoot.render(null)}};export const callable=name=>async(...args)=>{window.calls.push(name);(window.rpcCalls??=[]).push({name,args});if(name==='get_egpu_disconnect_status'&&args[0]==='whole_dock_trial')return {schema_version:1,busy:false,safe_to_unplug:false,code:'dock_teardown.no_trial',attachment_token:'a'.repeat(64)+':'+ 'b'.repeat(64)};if(name==='execute_egpu_disconnect')return {schema_version:1,busy:true,safe_to_unplug:false,code:'dock_teardown.trial_running',request_id:args[6]};if(name==='approve_safe_disconnect_shutdown'){if(window.holdShutdownApproval)await new Promise(resolve=>window.releaseShutdownApproval=resolve);return window.shutdownApproval??{schema_version:1,ready:true,approval_token:'shutdown-fixture-token',blockers:[]};}if(name==='execute_safe_disconnect_shutdown'){if(window.shutdownTransportLoss)throw Error('simulated response loss');return window.shutdownOutcome??{schema_version:1,accepted:true,code:'power.requested'};}if(name==='approve_supervised_portable_switch'){if(window.holdApproval)await new Promise(resolve=>window.releaseApproval=resolve);return {approval_token:'fixture-token',blockers:window.approvalBlocked?['fixture-blocker']:[]};}if(name==='execute_supervised_portable_switch')return {accepted:!window.executeRejected,code:'fixture-result'};if(name==='get_snapshot'){if(window.pauseSnapshots)await new Promise(resolve=>window.pendingSnapshots.push(resolve));return {snapshot:{...${JSON.stringify(fixture)},observed_at:(window.deliveredObservation=new Date(Date.now()-(window.snapshotAge??0)).toISOString()),egpu_link:{applicable:!!window.egpuUp,state:window.egpuUp?'up':'unknown',confidence:window.egpuUp?'verified':'unknown',reason:'fixture',error:''},blockers:[],sleep_guard:{required:false,confidence:'verified'},disconnect_readiness:{clients:[],ready:false}},inference:{mode:(window.deliveredMode=window.fixtureMode??'portable'),reasons:[]},diagnostics:{schema_version:2,timings_ms:[],hardware_profiles:{schema_version:1,host:{status:'unknown'},egpu:{status:'unknown'},capabilities:[]}},journey:{}};}if(name.startsWith('get_'))throw Error('Fixture provider unavailable: '+name);throw Error('Fixture denies writes: '+name)};`;
await esbuild.build({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import factory from '${root.replaceAll('\\','/')}/src/index';import {ExpandedCommandCenter} from '${root.replaceAll('\\','/')}/src/quick-access/expanded-command-center/shell';import {UtilityRail} from '${root.replaceAll('\\','/')}/src/quick-access/expanded-command-center/utility-rail';window.quickReading={available:true,value:'On',pending:true};window.quickCalls=0;window.quickWaits=[];window.quickStorage={getItem:()=>JSON.stringify({version:2,quick:['settings:utility-wifi']}),setItem(){}};window.renderQuickUtility=()=>window.modalRoot.render(<ExpandedCommandCenter onClose={()=>{}} tiles={{quick:[]}} layoutStorage={window.quickStorage} utilityReadings={{wifi:window.quickReading}} onUtilityRequest={()=>{window.quickCalls++;return new Promise((resolve,reject)=>window.quickWaits.push({resolve,reject}));}}/>);window.sliderCalls=[];window.sliderWaits=[];window.railReading={available:true,value:'50%',percent:50};window.renderRail=()=>window.modalRoot.render(<UtilityRail side="left" readings={{brightness:window.railReading}} onRequest={(id,percent)=>{window.sliderCalls.push(percent);return new Promise((resolve,reject)=>window.sliderWaits.push({resolve,reject}));}}/>);window.calls=[];window.pendingSnapshots=[];window.registrations=0;window.removals=0;window.runtimeRoot=createRoot(document.getElementById('runtime'));window.modalRoot=createRoot(document.getElementById('modal'));window.operationRoot=createRoot(document.getElementById('operation'));const landing=createRoot(document.getElementById('landing'));window.plugin=factory();window.mountLanding=()=>landing.render(window.plugin.content);window.hideLanding=()=>landing.render(null);`,loader:'tsx',resolveDir:root},bundle:true,outfile:join(out,'app.js'),platform:'browser',jsx:'automatic',nodePaths:[runtime],loader:{'.svg':'dataurl'},define:{'process.env.NODE_ENV':'"development"'},plugins:[{name:'fixture-ports',setup(b){b.onResolve({filter:/^regear:project-documents$/},()=>({path:'project-documents',namespace:'project-documents'}));b.onLoad({filter:/.*/,namespace:'project-documents'},()=>({contents:'export const noticesText='+JSON.stringify(readFileSync(join(root,'THIRD_PARTY_NOTICES.md'),'utf8'))+';export const licenseText='+JSON.stringify(readFileSync(join(root,'LICENSE'),'utf8'))+';',loader:'js'}));b.onResolve({filter:/^@decky\/(api|ui)$/},a=>({path:a.path,namespace:'fixture'}));b.onLoad({filter:/.*/,namespace:'fixture'},a=>({contents:a.path.endsWith('/api')?api:ui,loader:'js',resolveDir:root}));}}]});
const html='<!doctype html><body style="margin:0;background:#102331;color:white"><div id="runtime"></div><div id="landing"></div><div id="modal"></div><div id="operation"></div><script src="/app.js"></script>';
const server=createServer((req,res)=>res.end(req.url==='/app.js'?readFileSync(join(out,'app.js')):html));await new Promise(r=>server.listen(0,'127.0.0.1',r));
const {chromium}=require('C:/Users/SLDD/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');const browser=await chromium.launch({channel:'msedge',headless:true});
async function checkEgpuActions(page){
  const update=async(mode,age=0)=>{
    await page.evaluate(({mode,age})=>{window.fixtureMode=mode;window.snapshotAge=age;},{mode,age});
    await page.waitForFunction(({mode,age})=>{
      const value=window.contentProps.runtimeDetails.source.read();
      const snapshot=window.retainedView.disconnectControl.props.readCurrentSnapshot();
      return window.deliveredMode===mode&&(age?value&&!value.handheld.available&&!snapshot&&value.handheld.reason==='Current display status unavailable': snapshot?.observed_at===window.deliveredObservation&&value?.handheld.available===(mode==='tv_docked'||mode==='docked_egpu'));
    },{mode,age});
  };
  const activate=()=>page.evaluate(()=>window.retainedView.onAction('egpu',{id:'switch-handheld'}));
  const count=()=>page.evaluate(()=>window.modalShows??0);
  const reopen=async()=>{await page.evaluate(()=>window.openMenu());await page.waitForTimeout(80);};
  const original=await count();
  await activate();assert.equal(await count(),original,'portable direction never dispatches TV from Handheld tile');
  await update('unknown');await activate();assert.equal(await count(),original,'unknown display does not dispatch');
  await update('tv_docked',60000);await activate();assert.equal(await count(),original,'stale observation does not dispatch');
  await update('tv_docked');
  await page.evaluate(()=>window.contentProps.shortcut.portableBusy.current=true);
  await activate();assert.equal(await count(),original,'runtime busy guard rejects activation');
  await page.evaluate(()=>window.contentProps.shortcut.portableBusy.current=false);
  await page.evaluate(()=>{window.retainedView.onAction('egpu',{id:'switch-handheld'});window.retainedView.onAction('egpu',{id:'switch-handheld'});});
  assert.equal(await count(),original+1,'double A opens one confirmation');
  assert.equal(await page.evaluate(()=>window.lastModal.props.strTitle),'Return to Ally?');
  await page.evaluate(()=>window.lastModal.props.onCancel());await reopen();
  assert.equal(await page.evaluate(()=>window.rpcCalls.filter(x=>x.name==='approve_supervised_portable_switch').length),0,'cancel does not approve');
  await activate();await page.evaluate(()=>{window.holdApproval=true;window.lastModal.props.onOK();});
  await page.waitForFunction(()=>!!window.releaseApproval);
  const pending=await count();await activate();assert.equal(await count(),pending,'pending approval rejects duplicate dispatch');
  await page.evaluate(()=>{window.holdApproval=false;window.releaseApproval();});
  await page.waitForFunction(()=>window.rpcCalls.some(x=>x.name==='execute_supervised_portable_switch'));
  assert.deepEqual(await page.evaluate(()=>window.rpcCalls.filter(x=>x.name.startsWith('execute_'))),[{name:'execute_supervised_portable_switch',args:['fixture-token']}]);
  await reopen();await page.evaluate(()=>window.approvalBlocked=true);await activate();await page.evaluate(()=>window.lastModal.props.onOK());
  await page.waitForFunction(()=>window.reports.some(x=>x.body.startsWith('Display switch blocked.')));
  assert.equal(await page.evaluate(()=>window.rpcCalls.filter(x=>x.name.startsWith('execute_')).length),1,'backend blocker prevents execute');
  await reopen();await page.evaluate(()=>{window.approvalBlocked=false;window.executeRejected=true;});await activate();await page.evaluate(()=>window.lastModal.props.onOK());
  await page.waitForFunction(()=>window.reports.some(x=>x.body.startsWith('Display switch did not complete.')));
  await reopen();
  const before=await page.evaluate(()=>window.rpcCalls.filter(x=>!x.name.startsWith('get_')).length);
  await page.evaluate(()=>window.modalRoot.render(window.retainedView.renderDetail('egpu',{id:'egpu'})));
  await page.waitForFunction(()=>window.contentProps.runtimeDetails.source.readSelection()?.current==='egpu');
  assert.ok(await page.getByText('Configure docking',{exact:true}).count(),'actual eGPU status view is mounted');
  assert.equal(await page.evaluate(()=>window.rpcCalls.filter(x=>!x.name.startsWith('get_')).length),before,'status view performs no mutation');
  await page.evaluate(()=>window.modalRoot.render(null));await reopen();await update('portable');
  console.log('PASS actual mounted Content/native Handheld route: freshness, unknown/direction, busy, double A, cancel, pending, portable token execution, blocker/failure; read-only eGPU status');
}
async function checkSliders(page){
  await page.evaluate(()=>window.renderRail());
  const slider=page.getByRole('slider',{name:'Brightness',exact:true});
  const set=async(value)=>slider.evaluate((input,value)=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));},value);
  await set('94');
  await page.evaluate(()=>window.sliderWaits.shift().reject(Error('simulated failure')));
  await page.getByRole('alert').waitFor();
  assert.equal(await slider.inputValue(),'94','failed write retains requested value');
  await page.evaluate(()=>window.renderRail());
  assert.equal(await page.getByRole('alert').count(),1,'same observed object cannot clear failure');
  await page.evaluate(()=>{window.railReading={available:true,percent:52,value:'52%'};window.renderRail();});
  await page.waitForFunction(()=>!document.querySelector('[role=alert]'));
  assert.equal(await slider.inputValue(),'52','new provider observation reconciles failed request');
  await set('70');
  await page.evaluate(()=>{window.railReading={...window.railReading,pending:true};window.renderRail();});
  assert.equal(await slider.isDisabled(),false,'normal write pending stays interactive');
  await set('80');await set('94');
  assert.deepEqual(await page.evaluate(()=>window.sliderCalls),[94,70]);
  assert.equal(await slider.inputValue(),'94');
  assert.equal(await page.getByText('Applying…',{exact:true}).count(),0);
  await page.evaluate(()=>window.sliderWaits.shift().resolve());
  await page.waitForFunction(()=>window.sliderCalls.length===3);
  assert.deepEqual(await page.evaluate(()=>window.sliderCalls),[94,70,94],'only newest queued value is dispatched');
  await page.evaluate(()=>window.sliderWaits.shift().resolve());
  await page.evaluate(()=>{window.railReading={available:true,value:'94%',percent:94,pending:true};window.renderRail();});
  assert.match(await slider.getAttribute('aria-valuetext'),/requested/,'pending readback cannot confirm success');
  await page.evaluate(()=>{window.railReading={available:true,value:'94%',percent:94,pending:false};window.renderRail();});
  await page.waitForFunction(()=>document.querySelector('input[aria-label=Brightness]').getAttribute('aria-valuetext')==='94%');
  await page.evaluate(()=>{window.railReading={available:false,value:'Unavailable'};window.renderRail();});
  assert.equal(await slider.isDisabled(),true,'capability loss remains unavailable');
  await page.evaluate(()=>{window.modalRoot.render(null);window.openMenu();});
  await page.waitForTimeout(80);
  console.log('PASS actual React slider failure/recovery, optimistic value, pending interactivity and latest-wins coalescing');
}
async function checkQuickUtility(page){
 await page.evaluate(()=>window.renderQuickUtility());
 const button=page.locator('[data-ec-control="custom:settings:utility-wifi"]');
 await button.waitFor();await button.evaluate(node=>node.click());
 assert.equal(await page.evaluate(()=>window.quickCalls),0,'pending utility cannot dispatch through Quick');
 await page.evaluate(()=>{window.quickReading={available:true,value:'On',pending:false};window.renderQuickUtility();});
 await button.click();await page.evaluate(()=>window.quickWaits.shift().reject(Error('failure')));
 await page.waitForFunction(()=>document.querySelector('[data-ec-control="custom:settings:utility-wifi"]').getAttribute('aria-label').includes('Could not apply'));
 await page.evaluate(()=>window.renderQuickUtility());assert.match(await button.getAttribute('aria-label'),/Could not apply/);
 await page.evaluate(()=>{window.quickReading={available:true,value:'Off'};window.renderQuickUtility();});
 await page.waitForFunction(()=>!document.querySelector('[data-ec-control="custom:settings:utility-wifi"]').getAttribute('aria-label').includes('Could not apply'));
 await button.evaluate(node=>{node.click();node.click();});
 assert.equal(await page.evaluate(()=>window.quickCalls),2,'one further dispatch despite double activation');
 await page.evaluate(()=>window.quickWaits.shift().resolve());
 await page.evaluate(()=>{window.modalRoot.render(null);window.openMenu();});await page.waitForTimeout(80);
 console.log('PASS actual React Quick utility pending guard, failure observation recovery and duplicate activation');
}
async function checkDisconnect(page){
 await page.evaluate(()=>window.egpuUp=true);
 await page.waitForFunction(()=>window.retainedView.disconnectControl.props.readCurrentSnapshot()?.egpu_link?.state==='up');
 await page.locator('[data-ec-tab=egpu]').click();const button=page.locator('[data-ec-control=disconnect]');
 const shows=await page.evaluate(()=>window.modalShows);
 await button.evaluate(n=>{n.dispatchEvent(new CustomEvent('gamepadok',{bubbles:true,cancelable:true}));n.dispatchEvent(new CustomEvent('gamepadok',{bubbles:true,cancelable:true}));});
 await page.waitForFunction(()=>window.rpcCalls.some(x=>x.name==='execute_egpu_disconnect'));
 assert.equal(await page.evaluate(()=>window.modalShows),shows+1,'one progress popup and no intermediate confirmation');
 const calls=await page.evaluate(()=>window.rpcCalls.filter(x=>x.name==='execute_egpu_disconnect'));assert.equal(calls.length,1);
 assert.deepEqual(calls[0].args.slice(0,6),[true,'','disconnect','whole_dock_disconnect',true,'a'.repeat(64)+':'+ 'b'.repeat(64)]);
 assert.match(calls[0].args[6],/^[a-f0-9]{32}$/);
 await page.evaluate(()=>{window.lastModal.props.onCancel();window.egpuUp=false;});
 console.log('PASS actual native Safe Disconnect card A -> centered progress -> one guarded whole_dock_disconnect request, exact attachment and correlation, no second start');
}
async function checkShutdown(page){
 const count=()=>page.evaluate(()=>window.rpcCalls.filter(x=>x.name==='execute_safe_disconnect_shutdown').length);
 const open=async()=>{await page.evaluate(()=>window.openMenu());await page.waitForTimeout(80);};
 const press=async()=>{await page.locator('[data-ec-tab=egpu]').click();const button=page.locator('[data-ec-control=portable-shutdown]');await button.evaluate(n=>n.dispatchEvent(new CustomEvent('gamepadok',{bubbles:true,cancelable:true})));await page.waitForTimeout(80);};
 const hide=async()=>{await page.evaluate(()=>window.lastModal.props.onCancel());await page.waitForTimeout(40);};
 await page.waitForFunction(()=>window.contentProps.runtimeDetails.source.read()?.shutdown?.available);
 const original=await count();await page.evaluate(()=>window.holdShutdownApproval=true);await press();await press();
 await page.waitForFunction(()=>!!window.releaseShutdownApproval);
 assert.equal(await page.evaluate(()=>window.rpcCalls.filter(x=>x.name==='approve_safe_disconnect_shutdown').length),1,'pending double press approves once');
 assert.equal(await count(),original);
 await page.evaluate(()=>{window.holdShutdownApproval=false;window.releaseShutdownApproval();});
 await page.waitForFunction(()=>window.contentProps.runtimeDetails.source.read()?.shutdown?.message.includes('request accepted'));
 assert.deepEqual(await page.evaluate(()=>window.rpcCalls.filter(x=>x.name==='execute_safe_disconnect_shutdown').at(-1).args),['shutdown-fixture-token']);
 await hide();await open();assert.equal(await count(),original+1,'reopening never dispatches');
 for(const approval of [{schema_version:1,ready:false,approval_token:'',blockers:['safe_disconnect.game_running']},{schema_version:2,ready:true,approval_token:'token',blockers:[]},{schema_version:1,ready:true,approval_token:'',blockers:[]}]){
  await page.evaluate(value=>window.shutdownApproval=value,approval);await press();
  await page.waitForFunction(()=>window.contentProps.runtimeDetails.source.read()?.shutdown?.pending===false);
  assert.equal(await count(),original+1,'refused/malformed approval never executes');await hide();
 }
 await page.evaluate(()=>window.shutdownApproval=null);
 for(const outcome of [{schema_version:1,accepted:false,code:'safe_disconnect.evidence_changed'},{schema_version:1,accepted:false,code:'safe_disconnect.execution_failed'},{schema_version:2,accepted:true,code:'power.requested'}]){
  await page.evaluate(value=>window.shutdownOutcome=value,outcome);await press();
  await page.waitForFunction(()=>window.contentProps.runtimeDetails.source.read()?.shutdown?.pending===false);
  const message=await page.evaluate(()=>window.contentProps.runtimeDetails.source.read().shutdown.message);
  assert.match(message,outcome.code==='safe_disconnect.evidence_changed'?/Shutdown blocked: safe_disconnect.evidence_changed/:/completion is unverified/);
  if(outcome.code==='safe_disconnect.execution_failed')assert.ok(message.includes(outcome.code));
  await hide();
 }
 await page.evaluate(()=>window.shutdownTransportLoss=true);await press();
 await page.waitForFunction(()=>window.contentProps.runtimeDetails.source.read()?.shutdown?.message.includes('completion is unverified'));
 await hide();const after=await count();await open();assert.equal(await count(),after,'uncertain outcome does not retry automatically');
 await page.evaluate(()=>{window.shutdownTransportLoss=false;window.shutdownOutcome=null;});
 console.log('PASS mounted native Shutdown one-press approval/token, duplicate guard, malformed/refused approval, backend refusal, execution uncertainty and no automatic retry');
}
async function checkTutorialsAbout(page){
 const before=await page.evaluate(()=>window.rpcCalls.filter(x=>!x.name.startsWith('get_')).length);
 await page.locator('[data-ec-tab=settings]').click();await page.locator('[data-ec-control=tutorials]').evaluate(n=>n.dispatchEvent(new CustomEvent('gamepadok',{bubbles:true,cancelable:true})));
 const cards=page.locator('[data-tutorial]');await cards.first().waitFor();assert.equal(await cards.count(),4);
 for(let i=0;i<4;i++){
  const card=cards.nth(i),id=await card.getAttribute('data-tutorial');
  await card.focus();await card.evaluate(n=>n.dispatchEvent(new CustomEvent('gamepadok',{bubbles:true,cancelable:true})));
  await page.locator('[data-tutorial-back]').waitFor();
  await page.waitForFunction(()=>document.activeElement?.hasAttribute('data-tutorial-back'));
  assert.equal(await page.locator('li').count(),3);
  await page.getByRole('button',{name:'Read the guide',exact:true}).evaluate(n=>n.dispatchEvent(new CustomEvent('gamepadok',{bubbles:true,cancelable:true})));
  assert.match(await page.evaluate(()=>window.guideUrl),/^https:\/\/github.com\/ronnierosal\/Re-Gear\/wiki\//);
  await page.locator('[data-tutorial-back]').evaluate(n=>n.dispatchEvent(new CustomEvent('gamepadcancel',{bubbles:true,cancelable:true})));
  await page.waitForFunction(id=>document.activeElement?.getAttribute('data-tutorial')===id,id);
 }
 await page.locator('[data-ec-control=nested-back]').click();await page.locator('[data-ec-control=about]').evaluate(n=>n.dispatchEvent(new CustomEvent('gamepadok',{bubbles:true,cancelable:true})));
 const full=page.getByRole('button',{name:'Full project license',exact:true});await full.waitFor();
 assert.equal(await page.locator('pre').count(),0,'notices initially compact');
 await full.evaluate(n=>n.dispatchEvent(new CustomEvent('gamepadok',{bubbles:true,cancelable:true})));
 assert.equal(await page.locator('pre').textContent(),readFileSync('LICENSE','utf8'));
 await full.evaluate(n=>n.dispatchEvent(new CustomEvent('gamepadok',{bubbles:true,cancelable:true})));
 assert.equal(await page.locator('pre').count(),0);
 assert.equal(await page.evaluate(()=>window.rpcCalls.filter(x=>!x.name.startsWith('get_')).length),before,'tutorials/credits never mutate runtime');
 await page.evaluate(()=>{window.modalRoot.render(null);window.openMenu();});await page.waitForTimeout(80);
 console.log('PASS actual mounted Tutorials A/topic/B/focus restoration and source-derived About expansion; simulated Decky navigation ports');
}
try{const page=await browser.newPage({viewport:{width:828,height:466}});const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error('Fixture page error:',e.message)});await page.goto(`http://127.0.0.1:${server.address().port}`);await page.waitForTimeout(1500);assert.equal(errors.length,0);assert.equal(await page.evaluate(()=>window.registrations),1);assert.ok(await page.evaluate(()=>window.calls.includes('get_snapshot')));const cold=await page.evaluate(()=>{const find=(node,predicate)=>{if(!node)return null;if(predicate(node))return node;return find(node.child,predicate)||find(node.sibling,predicate)};const runtime=find(window.runtimeRoot._internalRoot.current,n=>typeof n.memoizedProps?.openExpanded==='function');if(!runtime)throw Error('Missing actual Content owner');window.contentProps=runtime.memoizedProps;window.openMenu=runtime.memoizedProps.openExpanded;window.openMenu();return true;});await page.waitForTimeout(150);const published=await page.evaluate(()=>{const find=n=>!n?null:n.memoizedProps?.disconnectControl?n:find(n.child)||find(n.sibling);const view=find(window.modalRoot._internalRoot.current);window.retainedView=view?.memoizedProps;return {snapshot:!!view?.memoizedProps.disconnectControl.props.readCurrentSnapshot(),game:view?.memoizedProps.disconnectControl.props.readCurrentSnapshot()?.game_state};});assert.deepEqual(errors,[]);assert.equal(published.snapshot,true,'cold menu sees the actual Content snapshot before landing mounts');assert.equal(published.game,'idle');await checkEgpuActions(page);await checkSliders(page);await checkQuickUtility(page);await checkDisconnect(page);await checkShutdown(page);await checkTutorialsAbout(page);await page.evaluate(()=>window.retainedView.onClose());await page.waitForTimeout(50);assert.equal(await page.evaluate(()=>window.removals),0);await page.evaluate(()=>window.openMenu());await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>window.registrations),1);await page.evaluate(()=>{window.retainedView.onClose();window.mountLanding()});await page.waitForTimeout(100);await page.screenshot({path:join(out,'landing.png')});await page.evaluate(()=>window.hideLanding());assert.equal(await page.evaluate(()=>window.removals),0);await page.evaluate(()=>{window.openMenu();window.holdShutdownApproval=true;});await page.locator('[data-ec-tab=egpu]').click();await page.locator('[data-ec-control=portable-shutdown]').click();await page.waitForFunction(()=>window.contentProps.runtimeDetails.source.read()?.shutdown?.pending===true);const shutdownBeforeUnload=await page.evaluate(()=>window.rpcCalls.filter(x=>x.name==='execute_safe_disconnect_shutdown').length);await page.evaluate(()=>{window.retainedView.onClose();window.pauseSnapshots=true;window.openMenu()});await page.waitForFunction(()=>window.pendingSnapshots.length>0);await page.evaluate(()=>{window.plugin.onDismount();window.releaseShutdownApproval();window.pendingSnapshots.splice(0).forEach(resolve=>resolve())});await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>window.retainedView.disconnectControl.props.readCurrentSnapshot()),null);assert.equal(await page.evaluate(()=>window.rpcCalls.filter(x=>x.name==='execute_safe_disconnect_shutdown').length),shutdownBeforeUnload,'unload during approval never executes shutdown');const callCount=await page.evaluate(()=>window.calls.length);await page.waitForTimeout(1100);assert.equal(await page.evaluate(()=>window.calls.length),callCount,'disposed services no longer poll');assert.equal(await page.evaluate(()=>window.removals),1);assert.equal(await page.evaluate(()=>window.runtimeRoot._internalRoot.current.child),null);assert.ok(await page.evaluate(()=>window.calls.every(name=>name.startsWith('get_')||['approve_supervised_portable_switch','execute_supervised_portable_switch','approve_safe_disconnect_shutdown','execute_safe_disconnect_shutdown','execute_egpu_disconnect'].includes(name))),'only explicitly simulated portable approval/execute RPCs');console.log('PASS real React cold global Content mount and snapshot publication into actual menu before landing, landing mount/hide and plugin unmount');}finally{await browser.close();server.close();}
