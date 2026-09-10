/** Local synthetic browser preview. No Decky runtime or device connection. */
import { createRequire } from 'node:module';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
const args = process.argv.slice(2);
const option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const output = resolve(option('--output', join(root, 'out/expanded-preview')));
const runtime = resolve(option('--runtime', join(root, 'node_modules')));
const require = createRequire(join(runtime, '__preview.cjs'));
const { build } = require('esbuild');
await mkdir(output, { recursive: true });
await build({ entryPoints: [join(root, 'frontend-tests/expanded-render-preview.tsx')], bundle: true,
  outfile: join(output, 'preview.js'), platform: 'browser', format: 'iife', jsx: 'automatic',
  loader: {'.svg': 'dataurl'}, nodePaths: [runtime], define: { 'process.env.NODE_ENV': '"development"' },
  plugins: [{name: 'forbid-device-api', setup(b) {
    b.onResolve({filter: /^@decky\//}, a => ({errors: [{text: `Synthetic preview cannot import ${a.path}`}]}));
  }}], logLevel: 'warning' });
await writeFile(join(output, 'index.html'), `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Re-Gear expanded synthetic prototype</title><style>
*{box-sizing:border-box}body{margin:0;background:#172b39;color:#f4f7fb;font-family:Arial,sans-serif}button{font:inherit}button:focus-visible{outline:3px solid #fff;outline-offset:-3px}
.sample-world{position:fixed;inset:0;overflow:hidden;background:linear-gradient(175deg,#456779 0%,#86aab8 36%,#253e31 37%,#4e6651 53%,#1c2526 54%)}.sample-world>span{position:absolute;right:3%;top:4%;font-size:12px;letter-spacing:3px;color:#dce9ed}.sample-road{position:absolute;left:48%;top:45%;width:70%;height:100%;transform:perspective(300px) rotateX(35deg) rotateZ(-14deg);background:linear-gradient(90deg,#424749 48%,#c8c4ab 48%,#c8c4ab 49%,#424749 49%)}
.preview-disclaimer{position:fixed;right:12px;bottom:4px;max-width:90vw;font-size:9px;letter-spacing:1px;color:#d1dee5;pointer-events:none}#reopen{position:relative;margin:40px;padding:20px}
</style></head><body><div id="root"></div><script src="/preview.js"></script></body></html>`);
const server = createServer(async (req, res) => {
  const file = req.url?.split('?')[0] === '/preview.js' ? 'preview.js' : 'index.html';
  res.setHeader('Content-Type', (file.endsWith('.js') ? 'text/javascript' : 'text/html') + '; charset=utf-8');
  res.end(await readFile(join(output, file)));
});
await new Promise(r => server.listen(Number(option('--port', '4184')), '127.0.0.1', r));
const url = `http://127.0.0.1:${server.address().port}`;
console.log(`Synthetic expanded preview: ${url}`);
if (args.includes('--playwright')) {
 const { chromium } = require(resolve(option('--playwright')));
 const browser=await chromium.launch({headless:true,...(args.includes('--channel')?{channel:option('--channel')}:{})});
 const failures=[],cases=[];
 for(const [width,height,columns] of [[1920,1080,4],[1280,720,4],[854,480,3],[828,466,3],[640,720,3],[390,700,2]]){
  const page=await browser.newPage({viewport:{width,height}});
  page.on('pageerror',e=>failures.push(e.message));
  for(const tab of ['quick','performance','egpu','controllers','settings'])for(const long of [false,true]){
   await page.goto(`${url}/?tab=${tab}${long?'&long=1':''}`);
   await page.locator('.rg-expanded-grid').waitFor();
   const r=await page.evaluate(()=>{
    const panel=document.querySelector('.rg-expanded'),content=document.querySelector('.rg-expanded-content'),grid=document.querySelector('.rg-expanded-grid'),footer=document.querySelector('footer');
    const clipped=[...panel.querySelectorAll('button,span,p,h2,select')].filter(e=>e.clientWidth&&e.scrollWidth>e.clientWidth+2).map(e=>e.textContent.slice(0,70));
    const iconSizes=[...panel.querySelectorAll('.rg-expanded-tile-icon svg')].map(e=>e.getBoundingClientRect().width);
    return {columns:getComputedStyle(grid).gridTemplateColumns.split(' ').length,clipped,iconSizes,footerVisible:footer.getBoundingClientRect().bottom<=innerHeight,overflow:document.documentElement.scrollWidth>innerWidth,contentOverflow:content.scrollWidth>content.clientWidth+1,logo:document.querySelector('.rg-expanded-wordmark img').naturalWidth>0};
   });
   cases.push({width,height,tab,long,...r});
   if(r.columns!==columns||r.clipped.length||r.overflow||r.contentOverflow||!r.footerVisible||!r.logo||r.iconSizes.some(s=>s<30))failures.push({width,tab,long,...r});
   if(!long)await page.screenshot({path:join(output,`${tab}-${width}.png`)});
  }
  await page.close();
 }
 const page=await browser.newPage({viewport:{width:1280,height:720}});
 await page.goto(url);
 const visual = await page.evaluate(()=>{
  const active=document.querySelector('[data-ec-control="manual"] .rg-expanded-tile-icon');
  const muted=document.querySelector('[data-ec-control="fps"] .rg-expanded-tile-icon');
  const warning=document.querySelector('[data-ec-control="disconnect"] .rg-expanded-value');
  return {active:getComputedStyle(active).color,muted:getComputedStyle(muted).color,warning:getComputedStyle(warning).color};
 });
 if(new Set(Object.values(visual)).size!==3)failures.push('Icon state colors are not distinct');
 await page.locator('[data-ec-tab="performance"]').focus();
 if(await page.locator('[data-ec-tab="quick"]').getAttribute('aria-selected')!=='true')failures.push('Focus incorrectly selected another tab');
 await page.locator('[data-ec-control="manual"]').click();
 await page.keyboard.press('Escape');
 if(await page.locator('[data-ec-control="manual"]').evaluate(e=>e!==document.activeElement))failures.push('Nested back did not restore launcher');
 await page.keyboard.press('e'); await page.keyboard.press('q');
 if(await page.locator('[data-ec-control="manual"]').evaluate(e=>e!==document.activeElement))failures.push('Tab switch lost focus memory');
 await page.locator('[data-ec-tab="settings"]').click();
 await page.locator('select').selectOption('disabled');
 if(await page.locator('select').inputValue()!=='disabled')failures.push('Dropdown failed');
 await page.locator('[data-ec-control="about"]').focus();
 for(let i=0;i<3;i++)await page.keyboard.press('PageUp');
 if(await page.locator('.rg-expanded-content').evaluate(e=>e.scrollTop)!==0)failures.push('Settings return to top failed');
 await page.keyboard.press('Escape');
 if(await page.locator('[data-ec-panel]').count())failures.push('Close failed');
 await page.locator('#reopen').click();
 await page.locator('[data-ec-panel]').waitFor();
 await page.goto(`${url}/?columns=3`);
 await page.locator('.rg-expanded-grid').waitFor();
 if(await page.locator('.rg-expanded-grid').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length)!==3)failures.push('Explicit three-column comparison failed');
 await page.screenshot({path:join(output,'quick-three-column.png')});
 await browser.close();
 await writeFile(join(output,'report.json'),JSON.stringify({limitation:'Synthetic DOM/keyboard and native adapter fixtures; actual Decky controller/layout performance unverified.',failures,cases},null,2));
 console.log(JSON.stringify({failures,cases:cases.length,report:join(output,'report.json')}));
 if(failures.length)process.exitCode=1;
}
if(!args.includes('--serve'))server.close();
