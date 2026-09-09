/** Actual TSX browser preview, never native Decky/controller evidence.
 * Install isolated dependencies if unavailable: npm install --prefix <runtime> --no-package-lock react@19 react-dom@19 esbuild@0.25
 * node scripts/qa_visual_preview.mjs --runtime <runtime>/node_modules --source <checkout> --output <evidence-dir> [--playwright <bundled-node_modules>/playwright] [--serve]
 * Screenshot mode requires Playwright and its browser; --serve keeps localhost preview open.
 */
import { createRequire } from 'node:module';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
const args = process.argv.slice(2);
const option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = resolve(option('--source', root));
const output = resolve(option('--output', join(root, '.qa-preview')));
const runtime = resolve(option('--runtime', join(root, 'node_modules')));
const require = createRequire(join(runtime, '__preview.cjs'));
const { build } = require('esbuild');
await mkdir(output, { recursive: true });
const decky = `import React from 'react';
const clean = p => Object.fromEntries(Object.entries(p).filter(([k]) => !['onGamepadFocus','onGamepadBlur','onButtonDown','focusable','highlightOnFocus','padding','bottomSeparator','childrenLayout','flow-children'].includes(k)));
export const DialogButton = React.forwardRef((p,r) => React.createElement('button',{...clean(p),ref:r,onFocus:p.onGamepadFocus},p.children));
export const Focusable = React.forwardRef((p,r) => React.createElement('div',{...clean(p),ref:r},p.children));
export const Field = React.forwardRef((p,r) => React.createElement('div',{...clean(p),ref:r,tabIndex:0,onFocus:p.onGamepadFocus},p.children));
export const ButtonItem = ({layout,...p}) => React.createElement(DialogButton,p);
export const PanelSection = p => React.createElement('section',{},React.createElement('h3',{},p.title),p.children);
export const PanelSectionRow = p => React.createElement('div',{style:{marginBottom:10}},p.children);
export const DropdownItem = p => React.createElement('label',{style:{display:'block',marginBottom:10}},p.label,React.createElement('select',{style:{display:'block',width:'100%'},disabled:p.disabled,value:p.selectedOption??'',onChange:e=>p.onChange({data:Number(e.target.value)})},p.rgOptions.map(o=>React.createElement('option',{key:o.data,value:o.data},o.label))));
export const ToggleField = p => React.createElement('label',{style:{display:'block',marginBottom:10}},React.createElement('input',{type:'checkbox',checked:p.checked,disabled:p.disabled,onChange:e=>p.onChange(e.target.checked)}),p.label);`;
await build({ entryPoints: [join(root, 'frontend-tests/qa-render-preview.tsx')], bundle: true,
  outfile: join(output, 'preview.js'), platform: 'browser', format: 'iife', jsx: 'automatic',
  nodePaths: [runtime], define: { 'process.env.NODE_ENV': '"development"' },
  plugins: [{ name: 'preview-boundaries', setup(b) {
    b.onResolve({ filter: /^@source\// }, a => ({ path: resolve(source, 'src', a.path.slice(8)) + '.tsx' }));
    b.onResolve({ filter: /^@decky\/ui$/ }, () => ({ path: 'decky-mock', namespace: 'preview' }));
    b.onResolve({ filter: /^@decky\/api$/ }, () => ({ path: 'api-mock', namespace: 'api-preview' }));
    b.onLoad({ filter: /.*/, namespace: 'api-preview' }, () => ({ contents: `export const callable = name => async () => { throw new Error('Unexpected backend request in render preview: ' + name); };` }));
    b.onLoad({ filter: /.*/, namespace: 'preview' }, () => ({ contents: decky, resolveDir: runtime }));
  }}], logLevel: 'warning' });
const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Re-Gear TSX fixture preview</title><style>
*{box-sizing:border-box}body{margin:0;background:#101c29;color:#f4f7fb;font-family:Arial,sans-serif}main{width:100%;padding:0}button{font:inherit;cursor:pointer}button:focus-visible,[tabindex]:focus-visible{outline:3px solid #39d8ff;outline-offset:-3px}
</style></head><body><div id="root"></div><aside style="margin-top:16px;padding:8px;font-size:11px;color:#9eb2ca;border-top:1px solid #294665">Actual TSX · Synthetic fixtures · Mock Decky controls and focus styling · No native/device proof</aside><script src="preview.js"></script></body></html>`;
await writeFile(join(output, 'index.html'), html);
const server = createServer(async (req, res) => {
  const file = req.url?.split('?')[0] === '/preview.js' ? 'preview.js' : 'index.html';
  res.setHeader('Content-Type', (file.endsWith('.js') ? 'text/javascript' : 'text/html') + '; charset=utf-8');
  res.end(await readFile(join(output, file)));
});
await new Promise(r => server.listen(Number(option('--port', '4179')), '127.0.0.1', r));
const url = `http://127.0.0.1:${server.address().port}`;
console.log(`Actual TSX source: ${source}\nPreview: ${url}\nMock Decky CSS/focus, synthetic fixture values; no native or backend proof.`);
if (args.includes('--playwright')) {
  const { chromium } = require(resolve(option('--playwright')));
  const browser = await chromium.launch({ headless: true, ...(args.includes('--channel') ? { channel: option('--channel') } : {}) });
  const report = { source, limitation: 'Mock Decky primitives and focus style; synthetic fixtures. No native navigation, backend or device validation.', captures: [] };
  for (const width of [268, 310, 320]) for (const fixture of ['ready', 'attention', 'unavailable', 'long-name', 'modules', 'tdp-picker', 'display-picker', 'auto-tdp', 'auto-tdp-running', 'auto-tdp-unavailable', 'auto-tdp-recovery']) {
    const page = await browser.newPage({ viewport: { width, height: 720 }, deviceScaleFactor: 1 });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto(`${url}/?fixture=${fixture}`); await page.locator('main').waitFor();
    const measurements = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth > innerWidth,
      clipped: [...document.querySelectorAll('main *')].filter(e => e.scrollWidth > e.clientWidth + 1 && e.clientWidth > 0).map(e => ({ tag: e.tagName, text: e.textContent, width: e.clientWidth, scrollWidth: e.scrollWidth })),
      buttons: [...document.querySelectorAll('button')].map(e => ({ name: e.getAttribute('aria-label') || e.textContent, width: e.offsetWidth, height: e.offsetHeight })),
    }));
    await page.screenshot({ path: join(output, `${fixture}-${width}.png`), fullPage: true });
    await page.keyboard.press('Tab');
    await page.screenshot({ path: join(output, `${fixture}-${width}-focus.png`), fullPage: true });
    report.captures.push({ width, fixture, errors, ...measurements }); await page.close();
  }
  await browser.close(); await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2));
  console.log(`Captured ${report.captures.length} fixtures; report: ${join(output, 'report.json')}`);
}
if (!args.includes('--serve')) server.close();
