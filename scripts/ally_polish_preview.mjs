// Actual-source browser capture with synthetic missing-data and utility readings.
// Usage: node scripts/ally_polish_preview.mjs <source-root> <output-directory>
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { resolve, join } from 'node:path';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
const [source, output] = process.argv.slice(2).map(value=>resolve(value));
const runtime='C:/Users/SLDD/AppData/Local/Temp/regear-qa-preview-runtime/node_modules';
const require=createRequire(join(runtime,'preview.cjs'));
await mkdir(output,{recursive:true});
const base=source.replaceAll('\\','/');
await require('esbuild').build({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import {ExpandedCommandCenter} from '${base}/src/quick-access/expanded-command-center/shell';import {buildTiles} from '${base}/src/quick-access/expanded-command-center/tile-source';import {testBuildTiles,unavailableTestActions} from '${base}/src/quick-access/expanded-command-center/test-build-actions';window.starts=0;createRoot(document.getElementById('root')).render(<ExpandedCommandCenter initialTab={new URLSearchParams(location.search).get('tab')||'quick'} tiles={testBuildTiles(buildTiles({}))} unavailableActions={unavailableTestActions} utilityReadings={{brightness:{available:true,value:"50%",percent:50},volume:{available:true,value:"40%",percent:40}}} onUtilityRequest={async()=>({ok:true})} onDisconnect={()=>{window.starts++}} onClose={()=>{}}/>);`,loader:'tsx',resolveDir:source},bundle:true,outfile:join(output,'preview.js'),platform:'browser',format:'iife',jsx:'automatic',loader:{'.svg':'dataurl'},nodePaths:[runtime],define:{'process.env.NODE_ENV':'"development"'}});
await writeFile(join(output,'index.html'),'<!doctype html><html><head><style>*{box-sizing:border-box}body{margin:0;background:#172b39;color:white;font-family:Arial}button{font:inherit}.notice{position:fixed;bottom:2px;right:5px;font-size:9px}</style></head><body><div id="root"></div><div class="notice">SIMULATED DATA / NO DEVICE ACTIONS</div><script src="/preview.js"></script></body></html>');
const server=createServer(async(req,res)=>{const js=req.url.startsWith('/preview.js');res.setHeader('Content-Type',js?'text/javascript':'text/html');res.end(await readFile(join(output,js?'preview.js':'index.html')))});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const {chromium}=require('C:/Users/SLDD/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
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
await page.close();}}finally{await browser.close();server.close()}
await writeFile(join(output,'observations.json'),JSON.stringify({source,limitation:'Actual source with production buildTiles unknown-state projection and simulated utility values; no native controller or hardware verification.',cases,navigation},null,2));console.log(output);

