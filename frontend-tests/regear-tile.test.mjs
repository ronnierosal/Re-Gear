import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import ts from 'typescript';

const root = new URL('../src/quick-access/expanded-command-center/', import.meta.url);
// Execute the actual components with a tiny JSX tree renderer; no Decky runtime required.
const renderer = `const Fragment = 'fragment';
let ref = {current:null};
function useRef() { return ref; }
function useEffect(fn) { fn(); }
export function resetGauge() { ref = {current:null}; }
function h(type, props, ...children) {
  props = {...props, children: children.flat(Infinity)};
  return typeof type === 'function' ? type(props) : {type, props};
}`;
const files = ['tile-artwork.tsx', 'tile-reading.ts', 'regear-tile.tsx'];
const source = files.map(file => readFileSync(new URL(file, root), 'utf8')
  .replace(/^import .*?;\r?\n/gm, '')).join('\n');
const js = ts.transpileModule(renderer + source, { compilerOptions: {
  module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022,
  jsx: ts.JsxEmit.React, jsxFactory: 'h', jsxFragmentFactory: 'Fragment',
}}).outputText;
const api = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));
const walk = node => node && typeof node === 'object' ? [node, ...(node.props?.children ?? []).flatMap(walk)] : [];
const text = node => node && typeof node === 'object' ? (node.props?.children ?? []).map(text).join('') : node == null || node === false ? '' : String(node);

test('five-column artwork copy keeps words intact and scales within its card', () => {
  assert.match(source, /width:58%/);
  assert.match(source, /rg-v3-tile-copy \.rg-expanded-label\{[^}]*font-size:clamp\(9px,.78vw,11px\)[^}]*overflow-wrap:normal[^}]*word-break:normal[^}]*hyphens:none/);
  assert.match(source, /rg-v3-tile-copy \.rg-expanded-value\{[^}]*font-size:clamp\(9px,.85vw,13px\)[^}]*overflow-wrap:normal[^}]*word-break:normal[^}]*hyphens:none[^}]*-webkit-line-clamp:2/);
  assert.doesNotMatch(source, /rg-v3-tile-copy \.rg-expanded-value\{[^}]*overflow-wrap:anywhere/);
});

test('approved sprite has 37 unique individually addressable symbols, with no fallback artwork', () => {
  assert.equal(createHash('sha256').update(api.approvedTileSprite).digest('hex'),
    'b2ecd73e379180a77f3164c57ba885de6406fd8f9d4f8d8f365bdcb0cdbab73f');
  assert.equal(api.tileArtworkIds.length, 37);
  assert.equal(new Set(api.tileArtworkIds).size, 37);
  for (const id of api.tileArtworkIds) {
    assert.equal(api.TileArtwork({id}).props.children[0].props.href, `#rg-cc-artwork-${id}`);
  }
  assert.equal(api.TileArtwork({id:'missing'}), null);
  const html = api.TileArtworkSprite().props.dangerouslySetInnerHTML.__html;
  assert.match(html, /id="rg-cc-artwork-fps"/);
  assert.doesNotMatch(html, /class="s"|\.s\{/);
});

test('unknown, unavailable and stale never surface retained values or gauges', () => {
  for (const reading of [
    {availability:'unknown'}, {availability:'available',freshness:'stale'},
    {availability:'available',freshness:'unknown'},
  ]) {
    const view = api.tileReadingView({...reading, primaryValue:60, secondaryValue:'GPU model', status:'Connected', progress:.5,unit:'FPS'});
    assert.equal(view.primary,'—'); assert.equal(view.secondary,undefined); assert.equal(view.progress,null);
    assert.equal(view.status,undefined);
  }
  assert.equal(api.tileReadingView({availability:'unavailable',primaryValue:60}).primary,'Unavailable');
  for (const value of [NaN,Infinity,-Infinity,null,undefined,'']) {
    assert.equal(api.tileReadingView({availability:'available',primaryValue:value}).primary,'—');
  }
  assert.equal(api.tileReadingView({availability:'available',primaryValue:0}).primary,'0');
});

test('FPS gauge uses verified current/target, clamps and rejects invalid readings', () => {
  const evidence={availability:'available',freshness:'fresh'};
  assert.equal(api.fpsReading(30,60,evidence).progress,.5);
  assert.equal(api.fpsReading(90,60,evidence).progress,1);
  assert.equal(api.fpsReading(0,60,evidence).progress,0);
  for(const current of [-1,NaN,Infinity,null,undefined]) assert.equal(api.fpsReading(current,60,evidence).progress,null);
  for(const target of [0,-1,NaN,Infinity,null,undefined]) assert.equal(api.fpsReading(30,target,evidence).progress,null);
  assert.match(api.tileOverlayStyles,/250ms ease/);
  assert.match(api.tileOverlayStyles,/prefers-reduced-motion:reduce/);
});

test('static actions dispatch once with no chevron, detail route or value, and stay visible when unavailable', () => {
  let calls=0;
  const props={label:'Safe Disconnect',artworkId:'safe-disconnect',buttonProps:{onClick:()=>calls++}};
  const action=api.StaticActionTile(props);
  action.props.onClick(); assert.equal(calls,1);
  assert.equal(text(action),'Safe Disconnect');
  assert.equal(walk(action).some(n=>String(n.props.className).includes('chevron')),false);
  const unavailable=api.StaticActionTile({...props,readiness:'Unavailable'});
  assert.equal(unavailable.props['aria-disabled'],true);
  assert.equal(unavailable.props.onClick,undefined);
  assert.match(text(unavailable),/Safe DisconnectUnavailable/);
  assert.equal(walk(unavailable).some(n=>n.props.className==='rg-expanded-detail'),false);
  assert.equal(walk(unavailable).find(n=>n.props.className==='rg-tile-metadata').props.children[0],'Unavailable');
});

test('unavailable native tiles refuse pointer and A activation while retaining focus navigation', () => {
  let pointerCalls=0;
  let controllerCalls=0;
  const onFocus=()=>{};
  const onLeft=()=>{};
  const DeckyButton=props=>({type:'decky-button',props});
  const buttonProps={
    onClick:()=>pointerCalls++,
    onOKButton:()=>controllerCalls++,
    onFocus,
    onLeft,
    'data-ec-control':'safe-disconnect',
  };

  const unavailable=api.ReGearTile({
    label:'Safe Disconnect', artworkId:'safe-disconnect', Button:DeckyButton, buttonProps, unavailable:true,
  });
  assert.equal(unavailable.type,'decky-button');
  assert.equal(unavailable.props['aria-disabled'],true);
  assert.equal(unavailable.props.onClick,undefined);
  assert.equal(unavailable.props.onOKButton,undefined);
  assert.equal(unavailable.props.onFocus,onFocus);
  assert.equal(unavailable.props.onLeft,onLeft);
  assert.equal(unavailable.props['data-ec-control'],'safe-disconnect');
  assert.match(text(unavailable),/Safe Disconnect/);
  assert.equal(pointerCalls,0);
  assert.equal(controllerCalls,0);

  const available=api.ReGearTile({
    label:'Safe Disconnect', artworkId:'safe-disconnect', Button:DeckyButton, buttonProps,
  });
  available.props.onClick();
  available.props.onOKButton();
  assert.equal(pointerCalls,1);
  assert.equal(controllerCalls,1);
});

test('static and dynamic share card geometry and forward focus and navigation hooks', () => {
  api.resetGauge();
  const onFocus=()=>{};
  const props={label:'FPS',artworkId:'fps',buttonProps:{onFocus,'data-ec-control':'fps'}};
  const action=api.StaticActionTile(props);
  const dynamic=api.DynamicTile({...props,reading:{availability:'unknown',unit:'FPS'},gauge:true});
  assert.equal(action.props.className,dynamic.props.className);
  assert.equal(dynamic.props.onFocus,onFocus);
  assert.equal(dynamic.props['data-ec-control'],'fps');
  assert.match(text(dynamic),/— FPS/);
  assert.equal(walk(dynamic).find(n=>n.props.className==='rg-tile-gauge').props['data-known'],false);
  assert.equal(walk(dynamic).find(n=>n.props.className==='rg-tile-gauge-fill').props.style.transition,'none');
});

test('unavailable telemetry does not disable FPS navigation or Move placement', () => {
  api.resetGauge();
  let activations=0;
  const dynamic=api.FpsTile({
    label:'FPS Target', current:null, target:60,
    evidence:{availability:'unavailable'},
    buttonProps:{onClick:()=>activations++,'data-ec-control':'fps'},
  });
  assert.equal(dynamic.props['aria-disabled'],undefined);
  assert.equal(typeof dynamic.props.onClick,'function');
  dynamic.props.onClick();
  assert.equal(activations,1);
  assert.match(text(dynamic),/Unavailable/);
});

test('gauge interpolates only between known readings, never from unknown to known', () => {
  api.resetGauge();
  const render = current => api.FpsTile({label:'FPS',current,target:60,evidence:{availability:'available',freshness:'fresh'}});
  const fill = tree => walk(tree).find(n=>n.props.className==='rg-tile-gauge-fill');
  assert.equal(fill(render(30)).props.style.transition,'none');
  assert.equal(fill(render(45)).props.style,undefined);
  assert.equal(fill(render(null)).props.style.transition,'none');
  assert.equal(fill(render(60)).props.style.transition,'none');
});
