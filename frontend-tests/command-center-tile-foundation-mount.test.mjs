import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/quick-access/expanded-command-center/shell.tsx', import.meta.url), 'utf8');

test('Command Center mounts the approved artwork sprite and overlay styles exactly once', () => {
  assert.match(source, /import \{ tileOverlayStyles \} from ["']\.\/regear-tile["'];/);
  assert.match(source, /import \{ TileArtworkSprite \} from ["']\.\/tile-artwork["'];/);
  assert.equal(source.match(/<TileArtworkSprite\s*\/>/g)?.length, 1);
  assert.match(source, /<style>\{expandedStyles \+ \(typeof tileOverlayStyles === "string" \? tileOverlayStyles : ""\) \+ artworkStyles\}<\/style>/);
  assert.match(source, /\{typeof TileArtworkSprite === "function" \? <TileArtworkSprite\/> : null\}/);
});

test('foundation mount does not replace the existing tile renderer', () => {
  assert.match(source, /const renderTile = \(item: Tile\) => <Button/);
  assert.match(source, /\{items\.map\(item => tab === "settings"/);
});
