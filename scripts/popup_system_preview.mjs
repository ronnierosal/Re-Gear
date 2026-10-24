import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
const baseline=process.env.REGEAR_POPUP_BASELINE==='1';const runtime=process.env.REGEAR_PREVIEW_RUNTIME,playwright=process.env.REGEAR_PLAYWRIGHT;
if(!runtime||!playwright)throw Error('External runtime paths required');
const require=createRequire(runtime+'/fixture.cjs');const {build}=require('esbuild');const {chromium}=require(playwright);
await mkdir('out/popup-preview',{recursive:true});
await writeFile('out/popup-preview/entry.tsx',`
import React from 'react';import {createRoot} from 'react-dom/client';
import {ConnectionProgressOverlay} from '../../src/connection-progress-overlay';import {connectionPanelCss} from '../../src/connection-panel-style';import {EgpuConfirmModal} from '../../src/egpu-confirm-modal';
const root=createRoot(document.getElementById('root')!);
const rows=Array.from({length:16},(_,i)=>({key:String(i),label:['GPU and driver','Connection link','TV HDMI detected','Audio recovery ready','Display switching ready'][i]??'Diagnostic observation '+i,state:i<2?'ready':'pending',stateLabel:i<2?'Confirmed':'Not yet verified'}));
const steps=(st)=>['Detect eGPU','Load GPU driver','Verify connection','Find TV','Prepare and switch display'].map((label,i)=>({label,state:st[i]}));
const ms:any={connecting:{activeStep:1,observedDone:1,progressText:'Step 2 of 5',steps:steps(['done','active','pending','pending','pending']),headline:'Connecting eGPU',currentDetail:'Step 2 of 5 · Loading GPU driver',complete:false,stale:false,attention:false},handoff:{activeStep:4,observedDone:4,progressText:'Step 5 of 5',steps:steps(['done','done','done','done','active']),headline:'Switching to TV',currentDetail:'Step 5 of 5 · Switching to TV',complete:false,stale:false,attention:false},stale:{activeStep:-1,observedDone:1,progressText:'Status stale. Last observed at step 2 of 5: Load GPU driver',steps:steps(['stale','stale','pending','pending','pending']),headline:'Waiting for a fresh update',currentDetail:'Last observed: Load GPU driver',complete:false,stale:true,attention:false},slow:{activeStep:1,observedDone:1,progressText:'Step 2 of 5',steps:steps(['done','active','pending','pending','pending']),headline:'Connecting eGPU',currentDetail:'Step 2 of 5 · Loading GPU driver',complete:false,stale:false,attention:false,slowNotice:'Slower than usual · Keep the eGPU connected'},success:{activeStep:5,observedDone:5,progressText:'Complete',steps:steps(['done','done','done','done','done']),headline:'Connected to TV',currentDetail:'Connected to TV',complete:true,stale:false,attention:false}};
(window as any).renderCase=(kind)=>{const common={rows:kind==='success'?rows.map((row,i)=>i<5?{...row,state:'ready',stateLabel:'Confirmed'}:row):kind==='failure'||kind==='setup'?rows.map((row,i)=>i===4?{...row,state:kind==='failure'?'error':'blocked',stateLabel:'Needs attention'}:row):rows,deviceLabel:'eGPU connected',elapsedSeconds:kind==='delay'?91:12,onHide:()=>{(window as any).hidden=true;},onSwitch:kind==='manual'?()=>{(window as any).switchRequested=true;}:undefined,keepConnectedMessage:'Keep the eGPU connected. Hide keeps docking active.'};
root.render(<div data-case={kind} key={kind}><style>{connectionPanelCss}</style>{['connecting','delay','success','setup','failure','longreason','manual','handoff','stale','slow'].includes(kind)?<ConnectionProgressOverlay {...common} milestones={ms[kind]} phase={kind==='success'?'ready':kind==='handoff'?'switching':'connecting'} detail={kind==='setup'?'Display setup required — open Re-Gear Diagnostics':kind==='failure'?'Display transition failed. Keep the eGPU connected.':kind==='longreason'?'Waiting for a fresh observation. '.repeat(20):kind==='delay'?'Taking longer than expected — still checking':kind==='success'?'TV switch reported complete':'Waiting for display activation'} delayNotice={kind==='delay'?'Taking longer than expected. Connection may take up to three minutes; completion is not guaranteed.':undefined}/>:
<EgpuConfirmModal strTitle={kind==='disconnect-ready'?'Disconnect readiness':kind==='blocked'?'Disconnect blocked':kind==='warning'?'Action needs attention':'Confirm action?'} strOKButtonText={kind==='confirmation'?'Confirm':'Hide'} bAlertDialog={kind!=='confirmation'} onOK={()=>{(window as any).confirmed=true;}} onCancel={()=>{(window as any).cancelled=true;}}><p>{kind==='disconnect-ready'?'Readiness checks complete. This does not establish physical unplug clearance.':'Keep the eGPU connected. No action has been performed in this fixture.'}</p>{Array.from({length:24},(_,i)=><p key={i}>Observation {i+1}: a long diagnostic explanation stays inside the scrolling details region.</p>)}</EgpuConfirmModal>}</div>);};
`);
// ConfirmModal is runtime-discovered by Decky. This mock tests our content only;
// its layout and controls do not establish native focus, bounds or A/B behavior.
const mock=`import React from 'react';export const DialogButton='button';export function ConfirmModal(p){return <section className={p.className} style={{width:440,padding:12}}><header className='fixture-header'>{p.strTitle}</header>{p.children}<footer className='fixture-footer'>{!p.bAlertDialog&&<button onClick={p.onCancel}>Cancel</button>}<button onClick={p.onOK}>{p.strOKButtonText||'OK'}</button></footer></section>}`;
await build({entryPoints:['out/popup-preview/entry.tsx'],outfile:'out/popup-preview/bundle.js',bundle:true,jsx:'automatic',loader:{'.svg':'dataurl'},nodePaths:[runtime],plugins:[{name:'native-fixture',setup(b){b.onResolve({filter:/^@decky\/ui$/},()=>({path:'ui',namespace:'mock'}));b.onLoad({filter:/.*/,namespace:'mock'},()=>({contents:mock,loader:'jsx',resolveDir:runtime}));}}]});
const browser=await chromium.launch(process.env.REGEAR_CHROMIUM?{executablePath:process.env.REGEAR_CHROMIUM,headless:true}:{channel:'msedge',headless:true});const report=[];
try{
 for(const viewport of [{width:828,height:466},{width:1280,height:720},{width:1280,height:800},{width:1920,height:1080}]){
  const page=await browser.newPage({viewport});await page.setContent('<body style="margin:0;background:#020b13;display:flex;align-items:center;justify-content:center;height:100vh"><div id="root"></div></body>');await page.addScriptTag({path:'out/popup-preview/bundle.js'});
  for(const kind of ['connecting','delay','success','setup','failure','longreason','manual','handoff','stale','slow','disconnect-ready','blocked','warning','confirmation']){
   await page.evaluate(kind=>window.renderCase(kind),kind);
   // root.render commits asynchronously: wait for this case's own marker, then two frames.
   await page.locator(`[data-case="${kind}"]`).waitFor();await page.evaluate(()=>{document.activeElement?.blur();return new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))});
   const native=['disconnect-ready','blocked','warning','confirmation'].includes(kind);
   const shell=native?'.rg-egpu-confirm':'.rg-popup',body=native?'.rg-confirm-body':'.rg-popup-body',footer=native?'.fixture-footer':'.rg-popup-footer',header=native?'.fixture-header':'.rg-popup-header';
   await page.locator(shell).waitFor();await page.locator(body).evaluate(e=>e.scrollTop=0);await page.locator(shell).evaluate(async e=>{for(const a of e.getAnimations({subtree:true}))if(a.effect.getTiming().iterations!==Infinity)await a.finished});
   const summary=page.locator('summary');if(await summary.count())await page.locator('details').evaluate(e=>e.open=false);
   const defaultBounds=await page.locator(shell).boundingBox();if(!native&&!baseline&&(defaultBounds.height>viewport.height*.60))throw Error('Default compact bounds '+JSON.stringify({viewport,defaultBounds}));
   // The connection overlay is the slim variant: 280px at every viewport, one visible Details entry (Y), 44px footer hit areas.
   if(!native&&!baseline&&Math.abs(defaultBounds.width-Math.min(280,viewport.width*.92))>2)throw Error('Slim width '+JSON.stringify({viewport,defaultBounds}));
   if(!native&&!baseline){const s=await page.locator('summary').boundingBox();if(s&&(s.width>1||s.height>1))throw Error('Visible Details summary duplicates Y Details');for(const h of await page.locator('.rg-popup-footer button').evaluateAll(bs=>bs.map(b=>b.getBoundingClientRect().height)))if(h<44)throw Error('Footer hit area under 44px: '+h);}
   if(!native&&!baseline){
    const fb=await page.locator('.rg-popup-footer').boundingBox();const rs=await page.locator('.rg-popup-footer button').evaluateAll(bs=>bs.map(b=>{const r=b.getBoundingClientRect();return {l:r.left,r:r.right,t:r.top,b:r.bottom,clip:b.scrollWidth>b.clientWidth+1}}));
    for(const [i,r] of rs.entries()){if(r.clip||r.l<fb.x-.5||r.r>fb.x+fb.width+.5||r.b>fb.y+fb.height+.5)throw Error('Footer clipping: '+kind);if(i&&r.l<rs[i-1].r-.5&&r.t<rs[i-1].b)throw Error('Footer overlap: '+kind);}
    if(kind==='manual'&&rs.length<3)throw Error('Switch to TV missing');
    const y=page.locator('.rg-popup-footer button',{hasText:'Details'});await y.click();if(!await page.locator('details').evaluate(e=>e.open))throw Error('Y did not open Details');await y.click();if(await page.locator('details').evaluate(e=>e.open))throw Error('Y did not close Details');
    const main=await page.locator('.rg-milestones').innerText();
    if(kind==='handoff'&&!main.includes('Screen will go dark'))throw Error('Hand-off warning missing');
    if(kind==='connecting'&&main.includes('Screen will go dark'))throw Error('Connecting shows hand-off warning');
    // Collapsed focus order: every Tab stop must be a visible, actionable target.
    await page.locator('details').evaluate(e=>e.open=false);await page.evaluate(()=>document.activeElement?.blur());
    const stops=[];for(let i=0;i<8;i++){await page.keyboard.press('Tab');const f=await page.evaluate(()=>{const e=document.activeElement;if(!e||e===document.body)return null;const r=e.getBoundingClientRect();return {tag:e.tagName,text:e.textContent.trim().slice(0,20),w:r.width,h:r.height}});if(!f||stops.some(s=>s.tag===f.tag&&s.text===f.text))break;stops.push(f);}
    for(const f of stops)if(f.w<=1||f.h<=1||f.tag==='SUMMARY')throw Error('Invisible focus stop: '+JSON.stringify(f));
    if(!stops.some(f=>f.text.includes('Details'))||!stops.some(f=>f.text.includes('Hide')))throw Error('Focus order missing actions: '+JSON.stringify(stops));
    if(kind==='stale'&&(main.includes('Screen will go dark')||!(await page.locator('.rg-popup-footer').innerText()).includes('Not live')))throw Error('Stale shown as live');
    if(kind==='slow'&&!main.includes('Slower than usual'))throw Error('Slow notice missing');
   }if(!native&&!baseline&&await page.locator('.rg-popup-body').evaluate(e=>e.scrollHeight>e.clientHeight+1))throw Error('Default body overflow');
   await page.mouse.move(0,0);await page.evaluate(()=>document.activeElement?.blur());
   const leftover=await page.evaluate(()=>document.activeElement&&document.activeElement!==document.body?document.activeElement.outerHTML.slice(0,80):null);if(leftover)throw Error('Focus leaked into default capture: '+leftover);
   await page.screenshot({path:`out/popup-preview/${kind}-${viewport.width}x${viewport.height}-default.png`});
   if(await summary.count()){if(native||baseline)await summary.click();else await page.locator('.rg-popup-footer button',{hasText:'Details'}).click();if(!await page.locator('details').evaluate(e=>e.open))throw Error('Details did not open');}
   const geometry=await page.evaluate(({header,body,footer})=>{const b=s=>{let r=document.querySelector(s).getBoundingClientRect();return {top:r.top,bottom:r.bottom}};return {header:b(header),body:b(body),footer:b(footer)}},{header,body,footer});
   if(geometry.header.top<viewport.height*.08||geometry.footer.bottom>viewport.height*.92||geometry.body.bottom>geometry.footer.top+1)throw Error('Bounds or footer overlap: '+kind);
   if(kind==='delay'){
    const text=await page.locator(shell).innerText();if(text.match(/Taking longer than expected/g)?.length>2||!text.includes('1:31'))throw Error('Delay copy/elapsed failure');
    if(await page.locator('.rg-popup-state-icon[data-motion=true]').first().evaluate(e=>getComputedStyle(e).animationName)==='none')throw Error('Waiting motion missing');
    const progressed=await page.locator('.rg-popup-state-icon[data-motion=true]').first().evaluate(async e=>{const a=e.getAnimations()[0];const start=a.currentTime;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return a.currentTime>start});if(!progressed)throw Error('Waiting animation did not advance');
    await page.emulateMedia({reducedMotion:'reduce'});if(await page.locator('.rg-popup-state-icon[data-motion=true]').first().evaluate(e=>getComputedStyle(e).animationName)!=='none')throw Error('Reduced motion ignored');await page.emulateMedia({reducedMotion:'no-preference'});await page.locator(shell).evaluate(async e=>{for(const a of e.getAnimations({subtree:true}))if(a.effect.getTiming().iterations!==Infinity)await a.finished});
   }
   await page.locator(body).evaluate(e=>e.scrollTop=0);await page.locator(footer+' button').last().focus();
   if(!await page.locator(footer+' button').last().evaluate(e=>e===document.activeElement))throw Error('Action focus lost');
   if(await summary.count()&&!await page.locator('details').evaluate(e=>e.open))throw Error('Focus collapsed details');
   await page.screenshot({path:`out/popup-preview/${kind}-${viewport.width}x${viewport.height}-expanded.png`});
   const scroll=await page.locator('.rg-details-scroll').count()?'.rg-details-scroll':body;await page.locator(scroll).evaluate(e=>e.scrollTop=e.scrollHeight);
   await page.screenshot({path:`out/popup-preview/${kind}-${viewport.width}x${viewport.height}-scrolled.png`});
   report.push({kind,viewport,defaultBounds,geometry,nativeHostSimulated:native});
  }
  await page.close();
 }
 await writeFile('out/popup-preview/report.json',JSON.stringify({simulatedNativeHost:true,report},null,2));console.log(report.length+' cases; default, expanded and scrolled captures; bounds, focus, elapsed, motion and reduced-motion checks passed. Native host is simulated.');
}finally{await browser.close();}
