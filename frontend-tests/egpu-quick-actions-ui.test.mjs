import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const ui = readFileSync(new URL("../src/quick-access/expanded-command-center/egpu-actions-ui.tsx", import.meta.url), "utf8");

test("eGPU quick actions keep the approved six stable action ids", () => {
  for (const id of ["switch-handheld","safe-disconnect","resolution","disconnect-sleep","disconnect-shutdown","status"]) {
    assert.match(ui, new RegExp(`"${id}"`));
  }
});

test("eGPU action grid prefers four equal columns and never spans cards", () => {
  assert.match(ui, /grid-template-columns:repeat\(4,minmax\(0,1fr\)\)/);
  assert.doesNotMatch(ui, /grid-column:\s*span\s*2/);
  assert.doesNotMatch(ui, /\[data-egpu-action-card\][^{]*\{[^}]*grid-column:\s*(?:span|1\s*\/\s*-1)/);
});

test("eGPU action cards expose icon, copy and a full-width controller-safe control slot", () => {
  assert.match(ui, /data-egpu-action-icon/);
  assert.match(ui, /data-egpu-action-copy/);
  assert.match(ui, /data-egpu-action-control/);
  assert.match(ui, /\[data-egpu-action-control\]>button/);
  assert.match(ui, /width:100%/);
});

test("USB and sleep popups stay explicit and do not invent permanent authorization", () => {
  assert.match(ui, /USB authorization required/);
  assert.match(ui, /Sleep with eGPU connected/);
  assert.match(ui, /Keep eGPU connected/);
  assert.doesNotMatch(ui, /Safe Disconnect \+ Sleep/);
  assert.doesNotMatch(ui, /safeDisconnectSleepAction/);
  assert.doesNotMatch(ui, /Always trust/i);
});
