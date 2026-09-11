import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const runtime=process.env.REGEAR_PREVIEW_RUNTIME;
const playwright=process.env.REGEAR_PLAYWRIGHT;
if(!runtime||!playwright)throw Error('Set REGEAR_PREVIEW_RUNTIME and REGEAR_PLAYWRIGHT to external dependencies');
const require=createRequire(runtime+'/fixture.cjs');
const {build}=require('esbuild');const {chromium}=require(playwright);
const baseline='f95b94d086a670fab2e3c598accc4b7feac8ed36';
await mkdir('out/utility-preview',{recursive:true});
await writeFile('out/utility-preview/entry.tsx',`
import React from 'react';import {createRoot} from 'react-dom/client';
import {ExpandedCommandCenter} from '../../src/quick-access/expanded-command-center/shell';
const root=createRoot(document.getElementById('root')!);
(window as any).renderPreview=(longReasons=false)=>root.render(<ExpandedCommandCenter onClose={()=>{}} longReasons={longReasons}/>);
(window as any).renderPreview();
`);
const browser=await chromium.launch({channel:'msedge',headless:true});const reports=[];
try{for(const before of [true,false]){
 const name=before?'before':'after';
 const plugins=before?[{name:'baseline-source',setup(b){b.onLoad({filter:/expanded-command-center[\\/](shell\.tsx|styles\.ts)$/},args=>({contents:execFileSync('git',['show',baseline+':src/quick-access/expanded-command-center/'+path.basename(args.path)],{encoding:'utf8'}),loader:args.path.endsWith('tsx')?'tsx':'ts',resolveDir:path.dirname(args.path)}));}}]:[];
 await build({entryPoints:['out/utility-preview/entry.tsx'],outfile:`out/utility-preview/${name}.js`,bundle:true,jsx:'automatic',loader:{'.svg':'dataurl'},nodePaths:[runtime],plugins});
 for(const viewport of [{width:828,height:466},{width:1280,height:720},{width:600,height:466},{width:360,height:640}]){
 const page=await browser.newPage({viewport});
 await page.setContent('<body style="margin:0;background:#020b13"><div id="root"></div></body>');
 await page.addScriptTag({path:`out/utility-preview/${name}.js`});
 await page.locator('[data-ec-control="fps"]').waitFor();
 const geometry=await page.evaluate(()=>{const box=selector=>{const e=document.querySelector(selector),b=e.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height,bottom:b.bottom}};return {panel:box('.rg-expanded'),content:box('.rg-expanded-content'),disconnect:box('[data-ec-control="disconnect"]'),settings:box('[data-ec-tab="settings"]'),heading:box('.rg-expanded h2'),tabbar:box('.rg-expanded-tabs')}});
 if(geometry.heading.y<geometry.tabbar.bottom)throw Error('Heading overlap');
 if(viewport.width>600&&geometry.disconnect.bottom>geometry.content.bottom)throw Error('Safe Disconnect hidden');
 if(!before){
 if(await page.locator('.rg-utility-rail input:disabled').count()!==2||await page.locator('.rg-utility-rail button:disabled').count()!==4)throw Error('Unknown control enabled or missing');
 const railOverflow=await page.locator('.rg-utility-rail').evaluateAll(rails=>rails.some(r=>r.scrollHeight>r.clientHeight+1));if(viewport.width>600&&railOverflow)throw Error('Utility controls not visible immediately');
 const right=await page.locator('[data-utility-side="right"]').boundingBox();
 if(viewport.width>480&&Math.abs(viewport.width-right.x-right.width-viewport.width*(viewport.width<=600?.03:.02))>2)throw Error('Right controls not at screen edge');
 if(viewport.width>480&&right.x<geometry.panel.x+geometry.panel.width)throw Error('Right rail overlaps menu');
 const prior=reports.find(r=>r.name==='before'&&r.width===viewport.width);
 if(viewport.width>600&&(prior.geometry.panel.width!==geometry.panel.width||prior.geometry.panel.height!==geometry.panel.height))throw Error('Central dimensions changed');
 }
 await page.screenshot({path:`out/utility-preview/${name}-${viewport.width}.png`});
 await page.locator('[data-ec-control="auto"]').click();
 await page.locator('[data-ec-control="nested-back"]').click();
 if(!await page.locator('[data-ec-control="auto"]').evaluate(e=>e===document.activeElement))throw Error('Back focus lost');
 await page.getByRole('tab',{name:'Settings',exact:true}).click();
 await page.getByRole('tab',{name:'Quick Access',exact:true}).click();
 for(let i=0;i<18;i++){await page.keyboard.press('Tab');if(!await page.evaluate(()=>!!document.activeElement?.closest('[data-ec-panel]')))throw Error('Tab escaped modal');}
 await page.evaluate(()=>window.renderPreview(true));
 await page.screenshot({path:`out/utility-preview/${name}-${viewport.width}-long.png`});
 reports.push({name,width:viewport.width,geometry,keyboardAndPointer:true,nativeVerified:false});await page.close();
 }}
 await writeFile('out/utility-preview/report.json',JSON.stringify({baseline,head:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),simulated:true,reports},null,2));console.log('Eight same-size source comparisons passed; navigation, disabled controls, central dimensions and immediate visibility checked.');
}finally{await browser.close();}
