import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync, readdirSync } from 'node:fs';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('all 37 approved production tiles are native, self-contained SVG artwork', () => {
  const files=readdirSync(new URL('../assets/command-center/v3/production/',import.meta.url))
    .filter(name=>/^\d{2}_[a-z-]+\.svg$/.test(name)).sort();
  assert.equal(files.length,37);
  assert.equal(files[0],'01_fps.svg');
  assert.equal(files.at(-1),'37_more.svg');
  for(const file of files){
    const source=read(`assets/command-center/v3/production/${file}`);
    assert.match(source,/viewBox="0 0 240 144"/);
    assert.doesNotMatch(source,/<text\b|\bhref=/);
  }
});

test('the production artwork loader imports all assets and maps registry identities explicitly', () => {
  const component=read('src/quick-access/expanded-command-center/v3-tile-artwork.tsx');
  const imports=[...component.matchAll(/production\/(\d{2}_[a-z-]+)\.svg\?v3-production/g)].map(match=>match[1]);
  assert.equal(imports.length,37);
  assert.equal(new Set(imports).size,37);
  for(const [control,artwork] of [
    ['fps-target','fps'],['manual-tdp','manual-tdp'],['auto-tdp','auto-tdp'],
    ['performance-profile','performance'],['safe-disconnect','safe-disconnect'],
    ['disconnect-sleep','disconnect-sleep'],['disconnect-shutdown','disconnect-shutdown'],
    ['controller-battery','battery'],['controller-priority','player-order'],
    ['offline-readiness','offline-ready'],['recording','record'],['audio','audio-output'],
  ]) assert.match(component,new RegExp(`"?${control}"?: "${artwork}"`));
  assert.match(component,/data-v3-artwork=\{artworkId\}/);
  assert.doesNotMatch(component,/fetch\(|XMLHttpRequest|https?:\/\//);
});

test('FPS, Safe Disconnect, and matching registry controls share ReGearTile without changing dispatch', () => {
  const shell=read('src/quick-access/expanded-command-center/shell.tsx');
  assert.match(shell,/original\.tile\.id==='fps'[\s\S]*<SharedFpsTile/);
  assert.match(shell,/original\.tile\.id==='disconnect'[\s\S]*<SharedTile/);
  assert.match(shell,/const v3ControlId=definition\?\.id\?\?original\.tile\.id/);
  assert.match(shell,/if\(v3ArtworkId\)[\s\S]*<SharedTile/);
  assert.match(shell,/definition\?\.directAction==="disconnect"&&onDisconnect/);
  assert.match(shell,/definition\?\.directAction==="disconnect"&&onDisconnect\)\{onDisconnect\(\);return;\}[\s\S]*setNested\(item\.id\)/);
  assert.match(shell,/return <Button type="button"/, 'unmapped controls retain the existing fallback');
});

test('production bundling is allowlisted and has no runtime filesystem or network fetch', () => {
  const rollup=read('rollup.config.js');
  assert.match(rollup,/const v3ProductionTiles = new Set/);
  assert.ok(rollup.includes('assets\\/command-center\\/v3\\/production\\/(\\d{2}_[a-z-]+)'));
  assert.match(rollup,/data:image\/svg\+xml;base64/);
  assert.doesNotMatch(rollup,/composeV3TileArtwork/);
});

test('V3 geometry keeps copy left, artwork right, focus, and reduced-motion gauge behavior', () => {
  const tile=read('src/quick-access/expanded-command-center/regear-tile.tsx');
  assert.match(tile,/aspect-ratio:5\/3/);
  assert.match(tile,/\.rg-v3-tile-artwork\{position:absolute;inset:0/);
  assert.match(tile,/\.rg-expanded-tile \.rg-v3-tile-copy[^{]*\{[^}]*width:58%/);
  assert.doesNotMatch(tile,/\.rg-expanded-tile\.rg-v3-tile:after/);
  assert.match(tile,/\.rg-v3-tile-copy \.rg-expanded-value\{[^}]*overflow-wrap:anywhere/);
  assert.match(tile,/\.rg-expanded-tile\.rg-v3-tile:focus-visible/);
  assert.match(tile,/transition:stroke-dashoffset 250ms ease/);
  assert.match(tile,/@media\(prefers-reduced-motion:reduce\)/);
});
