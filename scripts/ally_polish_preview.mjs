// Actual-source browser capture with synthetic missing-data and utility readings.
// Usage: node scripts/ally_polish_preview.mjs <source-root> <output-directory> <runtime-node-modules> <playwright-module>
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { resolve, join } from 'node:path';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
const customization=process.argv.includes('--customization');
const pathArgs=process.argv.slice(2).filter(value=>value!=='--customization');
if(pathArgs.length !== 4) throw new Error('Expected source, output, runtime node_modules and Playwright module paths');
const [source, output, runtime, playwright] = pathArgs.map(value=>resolve(value));
const require=createRequire(join(runtime,'preview.cjs'));
await mkdir(output,{recursive:true});
const base=source.replaceAll('\\','/');
await require('esbuild').build({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import {ExpandedCommandCenter} from '${base}/src/quick-access/expanded-command-center/shell';import {buildTiles} from '${base}/src/quick-access/expanded-command-center/tile-source';import {testBuildTiles,unavailableTestActions} from '${base}/src/quick-access/expanded-command-center/test-build-actions';window.starts=0;createRoot(document.getElementById('root')).render(<ExpandedCommandCenter ${customization ? "layoutStorage={window.localStorage} editButtons={{y:4}}" : ""} initialTab={new URLSearchParams(location.search).get('tab')||'quick'} tiles={testBuildTiles(buildTiles({}))} unavailableActions={unavailableTestActions} utilityReadings={{brightness:{available:true,value:"50%",percent:50},volume:{available:true,value:"40%",percent:40}}} onUtilityRequest={async()=>({ok:true})} onDisconnect={()=>{window.starts++}} onClose={()=>{}}/>);`,loader:'tsx',resolveDir:source},bundle:true,outfile:join(output,'preview.js'),platform:'browser',format:'iife',jsx:'automatic',loader:{'.svg':'dataurl'},nodePaths:[runtime],define:{'process.env.NODE_ENV':'"development"'}});
await writeFile(join(output,'index.html'),'<!doctype html><html><head><style>body{margin:0;background:#172b39;color:white;font-family:Arial}button{font:inherit}.notice{position:fixed;bottom:2px;right:5px;font-size:9px}</style></head><body><div id="root"></div><div class="notice">SIMULATED DATA / NO DEVICE ACTIONS</div><script src="/preview.js"></script></body></html>');
const server=createServer(async(req,res)=>{const js=req.url.startsWith('/preview.js');res.setHeader('Content-Type',js?'text/javascript':'text/html');res.end(await readFile(join(output,js?'preview.js':'index.html')))});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const {chromium}=require(playwright);
const browser=await chromium.launch({channel:'msedge',headless:true});const cases=[];const navigation=[];
try {for(const [width,height] of [[828,466],[1280,720]]){const page=await browser.newPage({viewport:{width,height}});for(const tab of ['quick','performance','egpu','controllers','settings']){await page.goto(`http://127.0.0.1:${server.address().port}/?tab=${tab}`);await page.locator('.rg-expanded-grid').waitFor();await page.screenshot({path:join(output,`${tab}-${width}.png`)});cases.push({width,height,tab,...await page.evaluate(()=>{const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}};return {shell:rect(document.querySelector('.rg-expanded')),cards:[...document.querySelectorAll('.rg-expanded-tile')].map(e=>({id:e.dataset.ecControl,rect:rect(e),label:e.querySelector('.rg-expanded-label').textContent,chevron:!!e.querySelector('.rg-expanded-chevron')})),headings:[...document.querySelectorAll('.rg-expanded-content>h2')].filter(e=>e.offsetHeight).length,rails:[...document.querySelectorAll('.rg-utility-rail')].map(e=>({side:e.dataset.utilitySide,rect:rect(e)})),columns:getComputedStyle(document.querySelector('.rg-expanded-grid')).gridTemplateColumns.split(' ').length}})});}await page.goto(`http://127.0.0.1:${server.address().port}/?tab=quick`);
await page.locator('[data-ec-control="fps"]').focus();
await page.keyboard.press('ArrowLeft');
assert.equal(await page.locator(':focus').getAttribute('data-ec-control'),'utility-brightness');
await page.keyboard.press('ArrowDown');
assert.equal(await page.locator(':focus').getAttribute('data-ec-control'),'utility-volume');
await page.keyboard.press('ArrowRight');
assert.equal(await page.locator(':focus').getAttribute('data-ec-control'),'fps');
await page.locator('[data-ec-control="disconnect"]').click();
assert.equal(await page.evaluate(()=>window.starts),1);
assert.equal(await page.locator('.rg-expanded-detail-page').count(),0);
navigation.push({width,railEntryTraverseReturn:true,disconnectOnePress:true});
if(customization){
  await page.locator('[data-ec-control="fps"]').focus();await page.keyboard.press('y');
  await page.locator('[data-ec-control="choice:performance:display"]').waitFor();
  await page.screenshot({path:join(output,`customize-${width}.png`)});
  await page.locator('[data-ec-control="choice:performance:display"]').click();
  await page.locator('[data-ec-control="custom:performance:display"]').waitFor();
  const before=await page.evaluate(()=>localStorage.getItem('regear.command-center-layout.v1'));
  assert.ok(JSON.parse(before).quick.includes('performance:display'));
  await page.locator('[data-ec-control="disconnect"]').focus();
  await page.keyboard.down('y');await new Promise(r=>setTimeout(r,600));await page.keyboard.up('y');
  await page.locator('[data-move-selected="true"]').waitFor();
  await page.screenshot({path:join(output,`move-${width}.png`)});
  await page.keyboard.press('ArrowLeft');await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(()=>localStorage.getItem('regear.command-center-layout.v1')),before);
  await page.locator('[data-ec-control="disconnect"]').focus();
  await page.keyboard.down('y');await new Promise(r=>setTimeout(r,600));await page.keyboard.up('y');
  await page.locator('[data-move-selected="true"]').waitFor();await page.keyboard.press('ArrowLeft');await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(()=>window.starts),1,'placing disconnect must not dispatch');
  assert.notEqual(await page.evaluate(()=>localStorage.getItem('regear.command-center-layout.v1')),before);
  await page.locator('[data-ec-control=utility-mic]').focus();await page.keyboard.press('y');assert.equal(await page.locator('[data-ec-picker]').count(),1);assert.equal(await page.locator('[data-utility-side=right] [data-utility-id]').count(),4);
  await page.screenshot({path:join(output,`right-editor-${width}.png`)});
}

await page.close();}}finally{await browser.close();server.close()}
await writeFile(join(output,'observations.json'),JSON.stringify({source,limitation:'Actual source with production buildTiles unknown-state projection and simulated utility values; no native controller or hardware verification.',cases,navigation},null,2));console.log(output);

