import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const read = (f) => readFileSync(new URL(`../src/${f}`, import.meta.url), "utf8");

test("connection popup is the slim half-width variant", () => {
  const overlay = read("connection-progress-overlay.tsx");
  assert.match(overlay, /compact slim headerMeta/);
  assert.match(read("popup-frame.tsx"), /slim \? " rg-slim" : ""/);
  assert.match(read("connection-panel-style.ts"), /\.rg-popup\.rg-compact\.rg-slim\{width:min\(280px,92vw\)/);
});

test("main view is one bar and one line; step list and path move into Details", () => {
  const overlay = read("connection-progress-overlay.tsx");
  const main = overlay.slice(overlay.indexOf('className="rg-milestones"'), overlay.indexOf("<details"));
  assert.match(main, /rg-milestone-bar/);
  assert.match(main, /rg-milestone-current/);
  assert.doesNotMatch(main, /rg-milestone-list|rg-connection-flow/);
  const details = overlay.slice(overlay.indexOf("<details"));
  assert.match(details, /rg-milestone-list/);
  assert.match(details, /rg-connection-flow/);
  assert.match(details, /keepConnectedMessage/);
});

test("hand-off warns the screen will go dark only while a fresh switch is in progress", () => {
  const overlay = read("connection-progress-overlay.tsx");
  assert.match(overlay, /const handoff=!m\.stale && !m\.attention && !done && props\.phase === "switching"/);
  assert.match(overlay, /Screen will go dark — look at the TV/);
});

test("slim popup keeps one visible Details entry and 44px footer hit areas", () => {
  const css = read("connection-panel-style.ts");
  assert.match(css, /\.rg-popup\.rg-slim \.rg-popup-footer button\{[^}]*min-height:44px!important/);
  assert.match(css, /\.rg-slim \.rg-connection-details>summary\{position:absolute;width:1px;height:1px[^}]*clip:rect\(0 0 0 0\)/);
  const preview = readFileSync(new URL("../scripts/popup_system_preview.mjs", import.meta.url), "utf8");
  assert.match(preview, /import \{connectionPanelCss\} from '\.\.\/\.\.\/src\/connection-panel-style'/);
  assert.match(preview, /Math\.min\(280,viewport\.width\*\.92\)/);
  assert.match(preview, /Footer hit area under 44px/);
});
