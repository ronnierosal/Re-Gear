import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
const runtime=process.env.REGEAR_PREVIEW_RUNTIME,playwright=process.env.REGEAR_PLAYWRIGHT;
if(!runtime||!playwright)throw Error('External runtime paths required');
const require=createRequire(runtime+'/fixture.cjs');const {build}=require('esbuild');const {chromium}=require(playwright);
await mkdir('out/popup-preview',{recursive:true});
await writeFile('out/popup-preview/entry.tsx',`
import React from 'react';import {createRoot} from 'react-dom/client';
import {ConnectionProgressOverlay} from '../../src/connection-progress-overlay';import {EgpuConfirmModal} from '../../src/egpu-confirm-modal';
const root=createRoot(document.getElementById('root')!);
const rows=Array.from({length:16},(_,i)=>({key:String(i),label:i===0?'GPU and driver':i===1?'Display activation':'Diagnostic observation '+i,state:i===0?'ready':'pending',stateLabel:i===0?'Confirmed':'Waiting for confirmation'}));
(window as any).renderCase=(kind)=>{const common={rows,deviceLabel:'eGPU connected',elapsedSeconds:kind==='delay'?91:12,onHide:()=>{(window as any).hidden=true;},keepConnectedMessage:'Keep the eGPU connected. Hide keeps docking active.'};
root.render(kind==='connecting'||kind==='delay'||kind==='success'?<ConnectionProgressOverlay {...common} phase={kind==='success'?'ready':kind==='connecting'?'switching':'connecting'} detail={kind==='delay'?'Taking longer than expected — still checking':kind==='success'?'TV switch reported complete':'Waiting for display activation'} delayNotice={kind==='delay'?'Taking longer than expected. Connection may take up to three minutes; completion is not guaranteed.':undefined}/>:
<EgpuConfirmModal strTitle={kind==='disconnect-ready'?'Disconnect readiness':kind==='blocked'?'Disconnect blocked':kind==='warning'?'Action needs attention':'Confirm action?'} strOKButtonText={kind==='confirmation'?'Confirm':'Hide'} bAlertDialog={kind!=='confirmation'} onOK={()=>{(window as any).confirmed=true;}} onCancel={()=>{(window as any).cancelled=true;}}><p>{kind==='disconnect-ready'?'Readiness checks complete. This does not establish physical unplug clearance.':'Keep the eGPU connected. No action has been performed in this fixture.'}</p>{Array.from({length:24},(_,i)=><p key={i}>Observation {i+1}: a long diagnostic explanation stays inside the scrolling details region.</p>)}</EgpuConfirmModal>);};
`);
// ConfirmModal is runtime-discovered by Decky. This mock tests our content only;
// its layout and controls do not establish native focus, bounds or A/B behavior.
const mock=`import React from 'react';export const DialogButton='button';export function ConfirmModal(p){return <section className={p.className} style={{width:440,padding:12}}><header className='fixture-header'>{p.strTitle}</header>{p.children}<footer className='fixture-footer'>{!p.bAlertDialog&&<button onClick={p.onCancel}>Cancel</button>}<button onClick={p.onOK}>{p.strOKButtonText||'OK'}</button></footer></section>}`;
await build({entryPoints:['out/popup-preview/entry.tsx'],outfile:'out/popup-preview/bundle.js',bundle:true,jsx:'automatic',loader:{'.svg':'dataurl'},nodePaths:[runtime],plugins:[{name:'native-fixture',setup(b){b.onResolve({filter:/^@decky\/ui$/},()=>({path:'ui',namespace:'mock'}));b.onLoad({filter:/.*/,namespace:'mock'},()=>({contents:mock,loader:'jsx',resolveDir:runtime}));}}]});
const browser=await chromium.launch({channel:'msedge',headless:true});const report=[];
try{
 for(const viewport of [{width:828,height:466},{width:1280,height:720},{width:1280,height:800},{width:1920,height:1080}]){
  const page=await browser.newPage({viewport});await page.setContent('<body style="margin:0;background:#020b13;display:flex;align-items:center;justify-content:center;height:100vh"><div id="root"></div></body>');await page.addScriptTag({path:'out/popup-preview/bundle.js'});
  for(const kind of ['connecting','delay','success','disconnect-ready','blocked','warning','confirmation']){
   await page.evaluate(kind=>window.renderCase(kind),kind);
   const native=['disconnect-ready','blocked','warning','confirmation'].includes(kind);
   const shell=native?'.rg-egpu-confirm':'.rg-popup',body=native?'.rg-confirm-body':'.rg-popup-body',footer=native?'.fixture-footer':'.rg-popup-footer',header=native?'.fixture-header':'.rg-popup-header';
   await page.locator(shell).waitFor();await page.locator(body).evaluate(e=>e.scrollTop=0);await page.locator(shell).evaluate(async e=>{for(const a of e.getAnimations())if(a.effect.getTiming().iterations!==Infinity)await a.finished});
   const summary=page.locator('summary');if(await summary.count())await page.locator('details').evaluate(e=>e.open=false);
   await page.screenshot({path:`out/popup-preview/${kind}-${viewport.width}x${viewport.height}-default.png`});
   if(await summary.count()){await summary.click();if(!await page.locator('details').evaluate(e=>e.open))throw Error('Details did not open');}
   const geometry=await page.evaluate(({header,body,footer})=>{const b=s=>{let r=document.querySelector(s).getBoundingClientRect();return {top:r.top,bottom:r.bottom}};return {header:b(header),body:b(body),footer:b(footer)}},{header,body,footer});
   if(geometry.header.top<viewport.height*.08||geometry.footer.bottom>viewport.height*.92||geometry.body.bottom>geometry.footer.top+1)throw Error('Bounds or footer overlap: '+kind);
   if(kind==='delay'){
    const text=await page.locator(shell).innerText();if(text.match(/Taking longer than expected/g)?.length!==1||!text.includes('1:31 elapsed'))throw Error('Delay copy/elapsed failure');
    if(await page.locator('.rg-popup-state-icon[data-motion=true]').first().evaluate(e=>getComputedStyle(e).animationName)==='none')throw Error('Waiting motion missing');
    await page.emulateMedia({reducedMotion:'reduce'});if(await page.locator('.rg-popup-state-icon[data-motion=true]').first().evaluate(e=>getComputedStyle(e).animationName)!=='none')throw Error('Reduced motion ignored');await page.emulateMedia({reducedMotion:'no-preference'});await page.locator(shell).evaluate(async e=>{for(const a of e.getAnimations())if(a.effect.getTiming().iterations!==Infinity)await a.finished});
   }
   await page.locator(body).evaluate(e=>e.scrollTop=0);await page.locator(footer+' button').last().focus();
   if(!await page.locator(footer+' button').last().evaluate(e=>e===document.activeElement))throw Error('Action focus lost');
   if(await summary.count()&&!await page.locator('details').evaluate(e=>e.open))throw Error('Focus collapsed details');
   await page.screenshot({path:`out/popup-preview/${kind}-${viewport.width}x${viewport.height}-expanded.png`});
   await page.locator(body).evaluate(e=>e.scrollTop=e.scrollHeight);
   await page.screenshot({path:`out/popup-preview/${kind}-${viewport.width}x${viewport.height}-scrolled.png`});
   report.push({kind,viewport,geometry,nativeHostSimulated:native});
  }
  await page.close();
 }
 await writeFile('out/popup-preview/report.json',JSON.stringify({simulatedNativeHost:true,report},null,2));console.log('28 cases; default, expanded and scrolled captures; bounds, focus, elapsed, motion and reduced-motion checks passed. Native host is simulated.');
}finally{await browser.close();}

