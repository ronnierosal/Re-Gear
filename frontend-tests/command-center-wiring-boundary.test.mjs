import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const shell = readFileSync(new URL("../src/quick-access/expanded-command-center/shell.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/quick-access/expanded-command-center/styles.ts", import.meta.url), "utf8");

test("runtime wiring cannot repurpose the shared Command Center header", () => {
  assert.doesNotMatch(shell, /Disconnect trial/);
  assert.doesNotMatch(shell, /Keep the cable connected/);
  assert.match(shell, /Re-Gear/);
  assert.match(shell, /Application status/);
});

test("wiring stays presentation-neutral in the shared shell", () => {
  // Runtime-owned controls may be injected into approved nested surfaces, but
  // feature state must not conditionally change brand/header presentation.
  assert.doesNotMatch(shell, /rg-expanded-brand[^\n]*disconnect/i);
  assert.doesNotMatch(shell, /rg-expanded-wordmark[^\n]*disconnect/i);
});

test("approved responsive geometry remains owned by UI", () => {
  assert.match(styles, /width:min\(74vw,1120px\)/);
  assert.match(styles, /@media\(max-width:900px\)\{\.rg-expanded\{width:76vw\}\}/);
  assert.match(styles, /@media\(max-width:760px\)[\s\S]*\.rg-expanded\{width:78vw\}/);
  assert.match(styles, /@media\(max-width:620px\)[\s\S]*\.rg-expanded\{width:80vw\}/);
  assert.doesNotMatch(styles, /width:min\(64vw/);
});

test("wiring does not reintroduce duplicate Quick Access copy", () => {
  assert.match(styles, /data-ec-tab=quick/);
  assert.match(styles, />h2/);
  assert.match(styles, />\.rg-expanded-context/);
  assert.match(styles, /display:none/);
});
