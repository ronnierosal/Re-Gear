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

test("brightness and volume are visually integrated into the main command center", () => {
  assert.match(styles, /data-utility-side=left/);
  assert.match(styles, /position:absolute/);
  assert.match(styles, /padding-left:calc/);
  assert.doesNotMatch(styles, /Very narrow hosts cannot fit side controls/);
  assert.doesNotMatch(styles, /data-utility-side=left[^}]*display:none/);
});

test("detached action rail scales from viewport rather than fixed card geometry", () => {
  assert.match(styles, /data-utility-side=right/);
  assert.match(styles, /width:clamp\(/);
  assert.match(styles, /height:82vh/);
  assert.match(rail, /min-height:clamp\(/);
});

test("utility rails do not add a redundant support heading", () => {
  assert.doesNotMatch(rail, /Support unverified/);
  assert.match(rail, /data-utility-id=\{id\}/);
  assert.match(rail, /brightness:/);
  assert.match(rail, /volume:/);
});
