import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const styles = readFileSync(new URL("../src/quick-access/expanded-command-center/styles.ts", import.meta.url), "utf8");
const rail = readFileSync(new URL("../src/quick-access/expanded-command-center/utility-rail.tsx", import.meta.url), "utf8");

test("Quick root does not spend vertical space on a duplicate title and subtitle", () => {
  assert.match(styles, /data-ec-tab=quick/);
  assert.match(styles, />h2/);
  assert.match(styles, />\.rg-expanded-context/);
  assert.match(styles, /display:none/);
});

test("main command center keeps the approved wide responsive geometry", () => {
  assert.match(styles, /width:min\(74vw,1120px\)/);
  assert.match(styles, /height:82vh/);
  assert.match(styles, /@media\(max-width:900px\)\{\.rg-expanded\{width:76vw\}\}/);
  assert.match(styles, /@media\(max-width:760px\)[\s\S]*?width:78vw/);
  assert.match(styles, /@media\(max-width:620px\)[\s\S]*?width:80vw/);
  assert.doesNotMatch(styles, /width:min\(64vw,980px\)/);
});

test("brightness and volume are visually integrated into the main command center", () => {
  assert.match(styles, /data-utility-side=left/);
  assert.match(styles, /position:absolute/);
  assert.match(styles, /padding-left:calc/);
  assert.doesNotMatch(styles, /Very narrow hosts cannot fit side controls/);
  assert.doesNotMatch(styles, /data-utility-side=left[^}]*display:none/);
});

test("detached action rail scales from viewport rather than fixed card geometry", () => {
  assert.match(styles, /data-utility-side=right/);
  assert.match(styles, /width:clamp\(68px,8\.5vw,94px\)/);
  assert.match(styles, /height:82vh/);
  assert.match(rail, /min-height:clamp\(/);
});

test("utility rails do not add redundant headings and retain approved labels", () => {
  assert.doesNotMatch(rail, /Support unverified/);
  assert.doesNotMatch(rail, /Quick actions/);
  assert.match(rail, /data-utility-id=\{id\}/);
  assert.match(rail, /brightness:"Brightness"/);
  assert.match(rail, /volume:"Volume"/);
  assert.match(rail, /mic:"Mic mute"/);
  assert.match(rail, /recording:"Record"/);
  assert.match(rail, /overlay:"Overlay"/);
});

test("quick tiles stay compact rather than drifting back to oversized cards", () => {
  assert.match(styles, /min-height:100px/);
  assert.match(styles, /gap:8px/);
  assert.doesNotMatch(styles, /min-height:116px/);
  assert.doesNotMatch(styles, /gap:10px/);
});