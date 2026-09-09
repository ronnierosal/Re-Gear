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
  nodePaths: [runtime], define: { 'process.env.NODE_ENV': '"development"' },
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
  const browser = await chromium.launch({headless:true, ...(args.includes('--channel') ? {channel:option('--channel')} : {})});
  const report = { limitation: 'Synthetic React and keyboard only. Native Steam overlay, physical LB/RB and hardware actions UNVERIFIED.', captures: [], failures: [] };
  for (const [width,height] of [[1920,1080],[1280,720],[960,600],[854,480],[320,720]]) {
    for (const tab of ['quick','performance','egpu','controllers','settings']) {
      const page = await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
      const errors=[]; page.on('pageerror', e=>errors.push(e.message));
      await page.goto(`${url}/?tab=${tab}&long=1`);
      await page.locator('[data-ec-panel]').waitFor();
      const layout = await page.evaluate(() => {
        const rect = e => {const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,right:r.right};};
        const panel=document.querySelector('[data-ec-panel]');
        const footer=panel.querySelector('footer');
        return {panel:rect(panel),footer:footer?rect(footer):null,overflow:document.documentElement.scrollWidth>innerWidth,
          controls:panel.querySelectorAll('[data-ec-control]').length,
          clipped:[...panel.querySelectorAll('button,p,h1,h2,h3')].filter(e=>e.clientWidth>0&&e.scrollWidth>e.clientWidth+1).map(e=>e.textContent)};
      });
      const failures=[];
      if(errors.length) failures.push(...errors);
      if(layout.overflow) failures.push('Document horizontal overflow');
      if(layout.panel.x < -1 || layout.panel.right > width+1 || layout.panel.bottom>height+1) failures.push('Panel outside viewport');
      if(!layout.footer || layout.footer.bottom>height+1) failures.push('Footer absent or outside viewport');
      if(layout.clipped.length) failures.push('Clipped text: '+layout.clipped.join(' | '));
      await page.screenshot({path:join(output,`${tab}-${width}-long.png`)});
      report.captures.push({width,height,tab,...layout,errors});
      report.failures.push(...failures.map(f=>`${width}/${tab}: ${f}`));
      await page.goto(`${url}/?tab=${tab}`); await page.locator('[data-ec-panel]').waitFor();
      const polish = await page.evaluate(() => {
        const panel=document.querySelector('[data-ec-panel]'), footer=panel.querySelector('footer');
        const grid=panel.querySelector('.rg-expanded-grid'), safe=panel.querySelector('.rg-expanded-pinned');
        const overlap=[...panel.querySelectorAll('.rg-expanded-tile-body')].some(body => {
          const rows=[...body.children].map(e=>e.getBoundingClientRect());
          return rows.some((r,i)=>i>0 && r.top<rows[i-1].bottom-1);
        });
        const rgb=getComputedStyle(document.activeElement).backgroundColor.match(/\d+/g)?.slice(0,3).map(Number)??[];
        return {overlap, brightFocus:rgb.length===3&&rgb.every(v=>v>200), footerButtons:footer.querySelectorAll('button').length,
          footerHeight:footer.getBoundingClientRect().height,
          columns:grid?getComputedStyle(grid).gridTemplateColumns.split(' ').length:0,
          safeVisible:!safe||(safe.getBoundingClientRect().top>=panel.getBoundingClientRect().top&&safe.getBoundingClientRect().bottom<=footer.getBoundingClientRect().top+1)};
      });
      if(polish.overlap||polish.brightFocus||polish.footerButtons||polish.footerHeight>52||!polish.safeVisible)
        report.failures.push(`${width}/${tab}: polish regression ${JSON.stringify(polish)}`);
      if(tab==='quick' && [1280,960,854].includes(width) && polish.columns!==(width===1280?4:3))
        report.failures.push(`${width}: responsive grid density mismatch`);
      await page.screenshot({path:join(output,`${tab}-${width}.png`)});
      await page.close();
    }
  }
  report.comparisons=[];
  for(const columns of [4,3]) {
    const comparison=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});
    await comparison.goto(`${url}/?columns=${columns}`);
    await comparison.locator('[data-ec-panel]').waitFor();
    const geometry=await comparison.evaluate(()=>{
      const box=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom};};
      const panel=document.querySelector('[data-ec-panel]'),content=panel.querySelector('.rg-expanded-content');
      return {panel:box(panel),content:box(content),tiles:[...panel.querySelectorAll('[data-ec-control]')].map(e=>({id:e.dataset.ecControl,...box(e)})),
        clipped:[...panel.querySelectorAll('button,span')].filter(e=>e.clientWidth>0&&e.scrollWidth>e.clientWidth+1).map(e=>e.textContent)};
    });
    if(geometry.clipped.length)report.failures.push(`Comparison ${columns}: clipped ${geometry.clipped.join(' | ')}`);
    if(geometry.tiles.some(t=>t.bottom>geometry.content.bottom+1))report.failures.push(`Comparison ${columns}: Quick Access requires scroll`);
    report.comparisons.push({columns,...geometry});
    await comparison.screenshot({path:join(output,`comparison-${columns}-columns.png`)});
    await comparison.close();
  }
  const page=await browser.newPage({viewport:{width:1280,height:720}});
  await page.goto(url); await page.locator('[data-ec-panel]').waitFor();
  const first=page.locator('[data-ec-control="auto"]'); await first.focus();
  const original=await first.getAttribute('data-ec-control');
  const originalControls=await page.locator('[data-ec-control]').evaluateAll(es=>es.map(e=>e.getAttribute('data-ec-control')));
  if(!originalControls.includes('fps')) report.failures.push('Unavailable FPS tile missing');
  await first.click();
  await page.locator('[data-ec-control="nested-back"]').waitFor();
  await page.keyboard.press('Escape');
  const nestedReturn=await page.evaluate(()=>document.activeElement?.getAttribute('data-ec-control'));
  if(nestedReturn!==original) report.failures.push(`Nested focus restore expected ${original}, got ${nestedReturn}`);
  await page.keyboard.press('e'); await page.keyboard.press('q');
  const restored=await page.evaluate(()=>document.activeElement?.getAttribute('data-ec-control'));
  if(restored!==original) report.failures.push(`Tab focus restore expected ${original}, got ${restored}`);
  const returnedControls=await page.locator('[data-ec-control]').evaluateAll(es=>es.map(e=>e.getAttribute('data-ec-control')));
  if(JSON.stringify(originalControls)!==JSON.stringify(returnedControls)) report.failures.push('Quick Access slots changed after switching tabs');
  await page.locator('[data-ec-control="display"]').focus();
  await page.keyboard.press('ArrowDown');
  const quickDown=await page.evaluate(()=>document.activeElement?.getAttribute('data-ec-control'));
  if(quickDown!=='disconnect') report.failures.push(`Quick four-column ArrowDown expected disconnect, got ${quickDown}`);
  await page.keyboard.press('e');
  await page.locator('[data-ec-control="manual"]').focus();
  await page.keyboard.press('ArrowDown');
  const performanceDown=await page.evaluate(()=>document.activeElement?.getAttribute('data-ec-control'));
  if(performanceDown!=='fps') report.failures.push(`Performance two-column ArrowDown expected fps, got ${performanceDown}`);
  await page.keyboard.press('Escape');
  if(await page.locator('[data-ec-panel]').count()) report.failures.push('Escape did not close top-level panel');
  await page.locator('#reopen').click(); await page.locator('[data-ec-panel]').waitFor();
  await page.close(); await browser.close();
  await writeFile(join(output,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({captures:report.captures.length,failures:report.failures,report:join(output,'report.json')},null,2));
  if(report.failures.length) process.exitCode=1;
}
if(!args.includes('--serve')) server.close();
