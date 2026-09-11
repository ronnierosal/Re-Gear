// Actual component fixture; Decky modal host is simulated, never native hardware proof.
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
const runtime = resolve('out/preview-runtime');
const require = createRequire(runtime + '/package.json');
const { build } = require('esbuild');
if (!process.env.REGEAR_PLAYWRIGHT) throw Error('REGEAR_PLAYWRIGHT path required');
const { chromium } = require(process.env.REGEAR_PLAYWRIGHT);
await mkdir('out/link-recovery-preview', { recursive: true });
const baseline = execFileSync('git', ['show', '0ef9325:src/connection-quick-status.tsx'], { encoding: 'utf8' });
await writeFile('out/link-recovery-preview/baseline.tsx', baseline.replaceAll('from "./', 'from "../../src/'));
await writeFile('out/link-recovery-preview/entry.tsx', `
import React from 'react'; import {createRoot} from 'react-dom/client';
import {ConnectionQuickStatus} from '../../src/connection-quick-status';
import {ConnectionQuickStatus as Baseline} from './baseline';
import {createLiveStatusStore} from '../../src/connection-live-status';
const store=createLiveStatusStore();
const offered={schema_version:1,availability:'offered',offered:true,code:'link_recovery.available',strategies:[{strategy:'session_restart',implemented:true}]};
(window as any).fixture={status:offered,executeCalls:[],reads:0,failExecute:false};
const initial={phase:'checking',connected:true,expiresAt:Date.now()+60000,seconds:180,title:'Taking longer than expected—still checking',canSwitch:false,rows:[{label:'GPU and driver',state:'waiting'},{label:'Connection link',state:'waiting'},{label:'TV HDMI detected',state:'waiting'},{label:'Audio recovery ready',state:'waiting'},{label:'Display switching ready',state:'waiting'},{label:'No game running',state:'ready'}]};
store.set(initial as any);(window as any).update=(patch:any)=>store.set({...store.get(),...patch});
const Component=location.hash==='#baseline'?Baseline:ConnectionQuickStatus;
createRoot(document.getElementById('root')!).render(<Component store={store} visible={true} onOpen={()=>{}}/>);
`);
const ui = `import React,{useEffect,useRef} from 'react';import {createRoot} from 'react-dom/client';
export const DialogButton='button';export function Field({children}){return <div>{children}</div>}
export function showModal(element,parent,options){const node=document.createElement('div');node.className='fixture-overlay';document.body.appendChild(node);const root=createRoot(node);let closed=false;const Close=()=>{if(closed)return;closed=true;root.unmount();node.remove();options?.fnOnClose?.()};root.render(React.cloneElement(element,{closeModal:Close}));return {Close,Update:()=>{}}}
export function ConfirmModal(p){const cancel=useRef(null);useEffect(()=>{cancel.current?.focus()},[]);return <section role='dialog' className={p.className} style={{width:420,padding:12}} onKeyDown={e=>{if(e.key==='Escape'){p.onEscKeypress?.();p.closeModal?.()}}}><header>{p.strTitle}</header>{p.children}<footer><button ref={cancel} onClick={()=>{p.onCancel?.();p.closeModal?.()}}>{p.strCancelButtonText}</button><button onClick={()=>{p.onOK?.();p.closeModal?.()}}>{p.strOKButtonText}</button></footer></section>}
`;
const api = `export function callable(name){return async(...args)=>{const f=window.fixture;if(name==='get_link_recovery_status'){f.reads++;if(f.status===null)throw Error('RPC unavailable');return f.status}if(name==='execute_link_recovery'){f.executeCalls.push(args);if(f.failExecute)throw Error('reply lost');return {schema_version:1,ok:true,code:'link_recovery.trained'}}throw Error('Unexpected RPC '+name)}}`;
await build({ entryPoints: ['out/link-recovery-preview/entry.tsx'], outfile: 'out/link-recovery-preview/bundle.js',
  bundle: true, jsx: 'automatic', loader: { '.svg': 'dataurl' }, nodePaths: [runtime + '/node_modules'],
  plugins: [{ name: 'decky-fixture', setup(b) {
    b.onResolve({ filter: /^@decky\/(ui|api)$/ }, args => ({ path: args.path, namespace: 'fixture' }));
    b.onLoad({ filter: /.*/, namespace: 'fixture' }, args => ({ contents: args.path.endsWith('/ui') ? ui : api,
      loader: 'jsx', resolveDir: runtime }));
  } }],
});
const { readFile } = await import('node:fs/promises');
const bundle = await readFile('out/link-recovery-preview/bundle.js', 'utf8');
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const results = [];
try {
  for (const viewport of [{ width: 828, height: 466 }, { width: 1280, height: 720 }]) {
    const page = await browser.newPage({ viewport });
    const errors = []; page.on('pageerror', error => errors.push(String(error)));
    const load = async baseline => {
      await page.goto('about:blank' + (baseline ? '#baseline' : ''));
      await page.setContent('<style>body{margin:0;background:#09111b;font-family:Arial;color:white}#root{width:310px;margin:12px}button{cursor:pointer}button:focus-visible{outline:2px solid #39d8ff}.fixture-overlay{position:fixed;inset:0;background:#0008;display:grid;place-items:center}footer{display:flex;gap:8px;margin-top:12px}footer button{padding:10px;flex:1}</style><div id="root"></div>');
      await page.addScriptTag({ content: bundle });
      await page.getByRole('button', { name: 'View full progress' }).waitFor();
    };
    await load(true);
    const before = await page.getByRole('button', { name: 'View full progress' }).boundingBox();
    await page.screenshot({ path: `out/link-recovery-preview/before-${viewport.width}.png` });
    await load(false);
    const retry = () => page.getByRole('button', { name: 'Retry eGPU detection' });
    await retry().waitFor();
    assert.deepEqual(await page.getByRole('button', { name: 'View full progress' }).boundingBox(), before);
    assert.equal(await page.evaluate(() => window.fixture.executeCalls.length), 0);
    await page.screenshot({ path: `out/link-recovery-preview/after-${viewport.width}.png` });
    await retry().click();
    await page.getByRole('dialog').waitFor();
    const dialog = await page.getByRole('dialog').boundingBox();
    assert.ok(Math.abs(dialog.x + dialog.width / 2 - viewport.width / 2) <= 1, 'dialog horizontally centered');
    assert.ok(Math.abs(dialog.y + dialog.height / 2 - viewport.height / 2) <= 1, 'dialog vertically centered');
    await page.screenshot({ path: `out/link-recovery-preview/confirm-${viewport.width}.png` });
    await page.keyboard.press('Escape');
    assert.equal(await page.getByRole('dialog').count(), 0);
    assert.equal(await page.evaluate(() => window.fixture.executeCalls.length), 0);
    await retry().click();
    await page.evaluate(() => { window.fixture.status = { schema_version: 1, offered: false }; });
    await page.getByRole('button', { name: 'Restart Gaming Mode', exact: true }).click();
    await page.getByText('Connection status changed. Check the latest readings.').waitFor();
    assert.equal(await page.evaluate(() => window.fixture.executeCalls.length), 0);
    await load(false); await retry().waitFor(); await retry().click();
    await page.evaluate(() => window.update({ expiresAt: 0 }));
    await page.waitForTimeout(50);
    await page.getByRole('button', { name: 'Restart Gaming Mode', exact: true }).click();
    assert.equal(await page.evaluate(() => window.fixture.executeCalls.length), 0);
    await load(false); await retry().waitFor(); await retry().click();
    await page.getByRole('button', { name: 'Restart Gaming Mode', exact: true }).evaluate(b => { b.click(); b.click(); });
    await page.getByText('The GPU is available. Checking the remaining connection steps…').waitFor();
    assert.deepEqual(await page.evaluate(() => window.fixture.executeCalls), [[true, 'session_restart']]);
    await load(false); await retry().waitFor();
    await page.evaluate(() => { window.fixture.failExecute = true; });
    await retry().click(); await page.getByRole('button', { name: 'Restart Gaming Mode', exact: true }).click();
    await page.getByText('Gaming Mode may have restarted. Check the connection status.').waitFor();
    await page.waitForTimeout(100);
    assert.equal(await page.evaluate(() => window.fixture.executeCalls.length), 1);
    assert.deepEqual(errors, []);
    results.push({ viewport, preservedProgressButtonBounds: before, interactionChecks: 'passed', nativeHost: 'simulated' });
    await page.close();
  }
  await writeFile('out/link-recovery-preview/report.json', JSON.stringify(results, null, 2));
  console.log('Both viewports: unchanged existing action position; no mount/cancel/stale dispatch; fresh backend recheck; one confirmed restart; lost reply is not retried.');
} finally { await browser.close(); }
