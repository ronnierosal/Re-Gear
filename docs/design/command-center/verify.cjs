// Local design-fixture QA only. No device, backend, or network access.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 950 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const base = pathToFileURL(path.join(__dirname, 'review.html')).href;
  const output = path.join(__dirname, 'captures/review02'); fs.mkdirSync(output, { recursive: true });
  const views = ['home', 'modules', 'egpu', 'tdp', 'controller', 'troubleshoot'];
  let checks = 0;
  for (const width of [268, 310, 320]) for (const height of [387, 600]) for (const view of views) {
    await page.goto(`${base}?page=${view}&width=${width}&height=${height}`);
    const fit = await page.locator('.content').evaluate(el => el.scrollWidth <= el.clientWidth);
    assert(fit, `Overflow: ${width}/${height}/${view}`);
    assert.equal(await page.locator('img').evaluateAll(imgs => imgs.every(i => i.complete && i.naturalWidth > 0)), true);
    checks++;
  }
  for (const scenario of ['portable', 'tv', 'attention', 'pending', 'unsupported', 'long']) {
    for (const view of views) {
      await page.goto(`${base}?page=${view}&scenario=${scenario}&width=268&height=387`);
      assert(await page.locator('.content').evaluate(el => el.scrollWidth <= el.clientWidth), `Scenario overflow: ${scenario}/${view}`);
      checks++;
    }
  }
  await page.goto(base);
  await page.locator('#modules-open').click();
  await page.locator('#open-tdp').click();
  assert.equal(await page.locator('#page').inputValue(), 'tdp');
  await page.locator('#go-back').click();
  assert.equal(await page.locator('#page').inputValue(), 'modules');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'open-tdp');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#page').inputValue(), 'home');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'modules-open');
  await page.locator('#quick-fps').click();
  await page.locator('dialog [data-value="40"]').click();
  assert.match(await page.locator('#quick-fps').innerText(), /40 FPS/);
  await page.locator('#quick-power').click();
  await page.locator('dialog [data-value="20"]').click();
  assert.match(await page.locator('#quick-power').innerText(), /20 W/);
  await page.locator('#quick-auto').click();
  await page.locator('dialog [data-value="Stop"]').click();
  assert.match(await page.locator('#quick-auto').innerText(), /Off/);
  await page.locator('#quick-auto').click();
  await page.locator('dialog [data-value="Configure"]').click();
  await page.locator('#start-tdp').click();
  assert.match(await page.locator('.badge').innerText(), /On/);
  await page.goto(`${base}?scenario=attention`);
  await page.locator('#quick-auto').click();
  assert.equal(await page.locator('dialog [data-value]').count(), 0);
  await page.keyboard.press('Escape');
  await page.locator('#open-troubleshoot').click();
  assert.equal(await page.locator('#page').inputValue(), 'troubleshoot');
  const shots = [
    ['command-center', 'home', 'portable'], ['modules', 'modules', 'portable'],
    ['egpu', 'egpu', 'tv'], ['auto-tdp', 'tdp', 'portable'],
    ['controller', 'controller', 'portable'], ['attention', 'home', 'attention'],
    ['unavailable', 'tdp', 'unsupported'], ['pending', 'home', 'pending'],
    ['long-name', 'egpu', 'long'], ['troubleshoot', 'troubleshoot', 'attention'],
  ];
  for (const width of [268,310]) for (const [name,view,scenario] of shots) {
    await page.goto(`${base}?page=${view}&scenario=${scenario}&width=${width}&height=600`);
    await page.locator('.qam').screenshot({ path: path.join(output, `${name}-${width}.png`) });
  }
  await page.goto(`${base}?width=268&height=387`);
  await page.locator('#modules-open').focus();
  await page.locator('.qam').screenshot({ path: path.join(output, 'focus-short-268.png') });
  await page.locator('#open-controller').focus();
  assert(await page.locator('#open-controller').evaluate(el => {
    const box = el.getBoundingClientRect(), parent = el.closest('.content').getBoundingClientRect();
    return box.top >= parent.top && box.bottom <= parent.bottom;
  }), 'Focused control did not scroll into view');
  await page.locator('.qam').screenshot({ path: path.join(output, 'scroll-short-268.png') });
  assert.deepEqual(errors, []);
  const titles = ['Command Center','Modules','eGPU','Auto TDP','Controller','Attention Required'];
  const files = ['command-center','modules','egpu','auto-tdp','controller','attention'];
  const board = `<!doctype html><html lang="en"><meta charset="utf-8"><title>Re-Gear design review 02</title><style>body{background:#10151c;color:#edf3f8;font:16px Arial;margin:0;padding:28px}h1{font-size:25px;margin:0 0 8px}p{color:#aebdca;margin:0 0 24px}.grid{display:grid;grid-template-columns:repeat(3,342px);gap:24px}.item h2{font-size:15px;margin:0 0 10px}.item img{display:block;width:342px}footer{font-size:13px;color:#aebdca;margin-top:20px}</style><h1>Re-Gear · Command Center</h1><p>Review 02 · Proposed design · Illustrative values · Approval pending</p><div class="grid">${files.map((f,i)=>`<div class="item"><h2>${titles[i]}</h2><img src="captures/review02/${f}-310.png" alt="${titles[i]} proposed panel"></div>`).join('')}</div><footer>310px content width · Approximated QAM chrome · Local HTML fixture, not native Decky evidence</footer></html>`;
  fs.writeFileSync(path.join(__dirname,'contact-sheet.html'),board);
  await page.setViewportSize({ width:1130,height:1700 });
  await page.goto(pathToFileURL(path.join(__dirname,'contact-sheet.html')).href);
  await page.screenshot({ path:path.join(output,'review-02.png'),fullPage:true });
  const result = { date: '2026-09-08', kind:'local HTML fixture; not native Decky', browser:await browser.version(), layoutCases:checks, interactionChecks:['Modules/page/Back route','focus return','FPS/TDP pickers and Auto Stop/Start local state','unknown recovery access','short-height focus scroll'], screenshots:22, runtimeErrors:errors, limitation:'Native QAM routing, gamepad, exact chrome, device capability and hardware actions not tested.' };
  fs.writeFileSync(path.join(__dirname,'verification.json'),JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result));
  await browser.close();
})().catch(error => { console.error(error); process.exitCode=1; });
