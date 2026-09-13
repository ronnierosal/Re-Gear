import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/quick-access/expanded-command-center/egpu-action-panel.tsx", import.meta.url), "utf8");

test("eGPU action panel keeps the approved stable action order", () => {
  const expected = [
    '"switch-handheld"',
    '"safe-disconnect"',
    '"resolution"',
    '"status"',
    '"disconnect-sleep"',
    '"disconnect-shutdown"',
  ];
  let previous = -1;
  for (const token of expected) {
    const index = source.indexOf(token, previous + 1);
    assert.ok(index > previous, `${token} missing or reordered`);
    previous = index;
  }
});

test("unavailable and pending actions stay visible but cannot dispatch", () => {
  assert.match(source, /const disabled = !available \|\| pending \|\| !onAction/);
  assert.match(source, /disabled=\{disabled\}/);
  assert.match(source, /if \(!disabled\) void onAction\(id\)/);
  assert.match(source, /pending \? "Working…" : available \? "Open" : "Unavailable"/);
});

test("panel is reusable by Quick Access and eGPU module", () => {
  assert.match(source, /shared by Quick Access and the eGPU tab/);
  assert.match(source, /Button\?: ElementType/);
  assert.doesNotMatch(source, /rpc|usb4|pci|gamescope/i);
});
