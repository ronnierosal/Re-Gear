import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { composeV3TileArtwork } from '../scripts/compose_v3_tile_artwork.mjs';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('the two-tile proof uses only approved V3 sources and self-contained bundles', () => {
  const buttons=read('assets/command-center/button-artwork.svg');
  for(const id of ['fps','safe-disconnect']){
    const source=read(`assets/command-center/v3/tiles/${id}.svg`);
    const composed=composeV3TileArtwork(source,buttons,id);
    assert.match(source,/viewBox="0 0 240 144"/);
    assert.match(composed,new RegExp(`<symbol id="${id}"`));
    assert.match(composed,new RegExp(`href="#${id}"`));
    assert.doesNotMatch(composed,/href="\.\.\/button-artwork\.svg#/);
  }
});

test('FPS and Safe Disconnect share ReGearTile while the other 35 keep their existing path', () => {
  const shell=read('src/quick-access/expanded-command-center/shell.tsx');
  assert.match(shell,/original\.tile\.id==='fps'[\s\S]*<SharedFpsTile/);
  assert.match(shell,/original\.tile\.id==='disconnect'[\s\S]*<SharedTile/);
  assert.match(shell,/return <Button type="button"/);
  assert.match(shell,/definition\?\.directAction==="disconnect"&&onDisconnect/);
  assert.match(shell,/definition\?\.directAction==="disconnect"&&onDisconnect\)\{onDisconnect\(\);return;\}[\s\S]*setNested\(item\.id\)/);
});

test('V3 geometry keeps copy left, artwork right, focus, and reduced-motion gauge behavior', () => {
  const tile=read('src/quick-access/expanded-command-center/regear-tile.tsx');
  assert.match(tile,/\.rg-v3-tile-artwork\{position:absolute;inset:0/);
  assert.match(tile,/\.rg-expanded-tile \.rg-v3-tile-copy[^{]*\{[^}]*width:58%/);
  assert.doesNotMatch(tile,/\.rg-expanded-tile\.rg-v3-tile:after/);
  assert.match(tile,/\.rg-v3-tile-copy \.rg-expanded-value\{[^}]*overflow-wrap:anywhere/);
  assert.match(tile,/\.rg-expanded-tile\.rg-v3-tile:focus-visible/);
  assert.match(tile,/transition:stroke-dashoffset 250ms ease/);
  assert.match(tile,/@media\(prefers-reduced-motion:reduce\)/);
});
