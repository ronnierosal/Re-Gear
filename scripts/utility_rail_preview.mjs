import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
const runtime=process.env.REGEAR_PREVIEW_RUNTIME;
const playwright=process.env.REGEAR_PLAYWRIGHT;
if(!runtime||!playwright)throw Error('Set REGEAR_PREVIEW_RUNTIME and REGEAR_PLAYWRIGHT to external dependencies');
const require=createRequire(runtime+'/fixture.cjs');
const {build}=require('esbuild');const {chromium}=require(playwright);
await mkdir('out/utility-preview',{recursive:true});
await writeFile('out/utility-preview/entry.tsx',`
import React from 'react';import {createRoot} from 'react-dom/client';
import {ExpandedCommandCenter} from '../../src/quick-access/expanded-command-center/shell';
import {UtilityRail} from '../../src/quick-access/expanded-command-center/utility-rail';
const readings={brightness:{available:true,value:'65%',percent:65},volume:{available:true,value:'40%',percent:40},mic:{available:true,value:'Muted'},recording:{available:false,value:'Unavailable'},overlay:{available:true,value:'Off'},audio:{available:true,value:'Speakers'}};
function Preview(){return <><p style={{color:'#a8cbe5',font:'12px Arial'}}>Preview fixtures · no device actions · existing menu source unchanged</p><div className="preview-layout"><UtilityRail side="left" readings={readings}/><ExpandedCommandCenter onClose={()=>{}}/><UtilityRail side="right" readings={readings}/></div></>}
createRoot(document.getElementById('root')!).render(<Preview/>);
`);
await build({entryPoints:['out/utility-preview/entry.tsx'],outfile:'out/utility-preview/bundle.js',bundle:true,jsx:'automatic',loader:{'.svg':'dataurl'},nodePaths:[runtime]});
const browser=await chromium.launch({channel:'msedge',headless:true});
try{const page=await browser.newPage({viewport:{width:1000,height:660}});
await page.setContent('<body style="margin:8px;background:#020b13"><div id="root"></div><style>.preview-layout{display:flex;align-items:flex-start;gap:10px}.preview-layout .rg-expanded-backdrop{position:static;display:contents}.preview-layout .rg-expanded{height:90vh}</style></body>');
await page.addScriptTag({path:'out/utility-preview/bundle.js'});
await page.getByLabel('Brightness',{exact:true}).waitFor();
if(!await page.getByLabel('Brightness',{exact:true}).isDisabled())throw Error('Preview without adapter enabled a control');
await page.screenshot({path:'out/utility-preview/utility-rails.png'});
console.log('Source preview saved; no-adapter controls disabled.');
}finally{await browser.close();}
