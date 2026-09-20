import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { composeCommandCenterArtwork } from "../scripts/compose_command_center_artwork.mjs";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
const shell = read("../src/quick-access/expanded-command-center/shell.tsx");
const component = read("../src/quick-access/expanded-command-center/rich-tile-artwork.tsx");
const rollup = read("../rollup.config.js");
const preview = read("../scripts/expanded_visual_preview.mjs");
const tiles = read("../assets/command-center/tile-artwork.svg");
const buttons = read("../assets/command-center/button-artwork.svg");

test("live Command Center grid mounts rich artwork behind dynamic tile copy", () => {
  assert.match(shell, /<RichArtwork controlId=\{item\.id\}\/>[\s\S]*<span className="rg-expanded-tile-body">/);
  assert.match(shell, /\{!artworkIdFor\(item\.id\) && <span className="rg-expanded-tile-icon">/);
  assert.match(shell, /<RichArtworkSprite\/>/);
  assert.match(shell, /expandedStyles \+ artworkStyles/);
  assert.ok(shell.indexOf("<RichArtwork controlId={item.id}/>") < shell.indexOf('<span className="rg-expanded-value">'));
});

test("control mapping uses exact rich tile symbols and retains legacy fallback", () => {
  const mapped = [...component.matchAll(/^\s+(\w+): "([^"]+)",$/gm)].map(([, control, artwork]) => [control, artwork]);
  assert.deepEqual(mapped, [
    ["fps","fps"],["manual","manual-tdp"],["auto","auto-tdp"],["display","display"],
    ["egpu","egpu"],["controller","controller"],["builtin","controller"],["priority","player-order"],
    ["disconnect","safe-disconnect"],["appearance","settings"],["about","about"],
  ]);
  for (const [, artwork] of mapped) assert.match(tiles, new RegExp(`<symbol id="tile-${artwork}"`));
  assert.doesNotMatch(component, /render:|game:|diagnostics:/, "controls without exact artwork must keep the legacy icon");
  assert.match(component, /if \(!artworkId\) return null/);
});

test("build composes the checked-in tile and button sprites without runtime fetches", () => {
  assert.match(component, /tile-artwork\.svg\?rich-sprite/);
  assert.match(rollup, /readFileSync\(new URL\("\.\/assets\/command-center\/tile-artwork\.svg"/);
  assert.match(rollup, /readFileSync\(new URL\("\.\/assets\/command-center\/button-artwork\.svg"/);
  assert.match(rollup, /composeCommandCenterArtwork\(tileArtwork, buttonArtwork\)/);
  assert.match(preview, /onResolve\(\{filter:\/tile-artwork\\\.svg\\\?rich-sprite\$\//);
  assert.match(preview, /composeCommandCenterArtwork\(tileArtwork,buttonArtwork\)/);
  assert.match(tiles, /href="button-artwork\.svg#/);
  assert.match(buttons, /<symbol id="fps"/);
  assert.doesNotMatch(component, /fetch\(|XMLHttpRequest|https?:\/\//);
});

test("composed artwork namespaces every injected SVG id, reference, and class", () => {
  const sprite = composeCommandCenterArtwork(tiles, buttons);
  const ids = [...sprite.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  const hrefs = [...sprite.matchAll(/\bhref="#([^"]+)"/g)].map(match => match[1]);
  const urls = [...sprite.matchAll(/url\(#([^)]+)\)/g)].map(match => match[1]);
  const classes = [...sprite.matchAll(/\bclass="([^"]+)"/g)].flatMap(match => match[1].split(/\s+/));
  assert.ok(ids.length > 0 && classes.length > 0);
  for (const value of [...ids, ...hrefs, ...urls, ...classes]) assert.match(value, /^rg-cc-/);
  assert.equal(new Set(ids).size, ids.length, "composed SVG ids must be unique");
  for (const reference of [...hrefs, ...urls]) assert.ok(ids.includes(reference), `unresolved #${reference}`);
  assert.doesNotMatch(sprite, /button-artwork\.svg#/);
  assert.doesNotMatch(sprite, /\.(?:s|c|g|w|r)(?=[\s,{.:#>+~[])/);
  assert.match(component, /#rg-cc-tile-/);
});

test("artwork layer is inert and dynamic values remain React overlays", () => {
  assert.match(component, /pointer-events:none/);
  assert.match(component, /linear-gradient\(90deg,#071825f5/);
  assert.match(component, /aria-hidden="true"/);
  assert.match(component, /prefers-reduced-motion:reduce/);
  assert.match(shell, /<span className="rg-expanded-value">[\s\S]*\{item\.value\}/);
  assert.match(shell, /<span className="rg-expanded-detail">\{item\.detail\}/);
  assert.doesNotMatch(component, /onClick|onFocus|onGamepad|item\.value|item\.detail/);
});
