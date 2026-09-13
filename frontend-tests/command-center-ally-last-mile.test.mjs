import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const styles = readFileSync(new URL("../src/quick-access/expanded-command-center/styles.ts", import.meta.url), "utf8");
const utility = readFileSync(new URL("../src/quick-access/expanded-command-center/utility-rail.tsx", import.meta.url), "utf8");

test("Ally layout uses equal-size cards and removes redundant top-level help strip", () => {
  assert.match(styles, /height:88px!important;min-height:88px!important;max-height:88px!important/);
  assert.match(styles, /rg-expanded-settings-list .*height:88px!important/);
  assert.match(styles, /\.rg-expanded-info\{display:none!important\}/);
});

test("Quick Access and Settings do not repeat their page title/subtitle", () => {
  assert.match(styles, /data-ec-tab=settings/);
  assert.match(styles, /data-ec-tab=quick/);
  assert.match(styles, />h2.*display:none/);
});

test("brightness and volume stay compact, icon-first and controller-focusable", () => {
  assert.match(styles, /width:clamp\(52px,5\.8vw,62px\)/);
  assert.match(utility, /data-ec-control={`utility-\$\{id\}`}/);
  assert.match(utility, /data-utility-side=left.*rg-utility-label\{display:none/);
  assert.match(utility, /brightness:/);
  assert.match(utility, /volume:/);
});

test("right action rail remains compact instead of scrolling", () => {
  assert.match(styles, /data-utility-side=right.*max-height:70vh;overflow:hidden/);
});

test("rapid slider changes preserve the latest requested value", () => {
  assert.match(utility, /queued=useRef\(new Map<UtilityId,number>\(\)\)/);
  assert.match(utility, /queued\.current\.set\(id,percent\)/);
  assert.match(utility, /if\(next!==undefined&&next!==percent\) void run\(id,next\)/);
});
