import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const nav = readFileSync(new URL("../src/quick-access/expanded-command-center/navigation-contract.ts", import.meta.url), "utf8");
const customize = readFileSync(new URL("../src/quick-access/expanded-command-center/quick-actions-customization.tsx", import.meta.url), "utf8");

test("X is reserved for Quick Access right-rail editing", () => {
  assert.match(nav, /quickTapX:\s*"edit-right-rail"/);
  assert.match(nav, /otherTabsTapX:\s*"none"/);
  assert.match(nav, /kind:\s*"edit-quick-actions"/);
  assert.match(nav, /kind:\s*"set-quick-action"/);
});

test("right-rail editor keeps four equal slots and fixed left utilities", () => {
  assert.match(customize, /Quick Action Buttons/);
  assert.match(customize, /repeat\(4,minmax\(0,1fr\)\)/);
  assert.match(customize, /slots\.slice\(0,4\)/);
  assert.match(customize, /Brightness and Volume stay fixed on the left/);
});

test("X editing is explicitly separate from Y main-card customization", () => {
  assert.match(customize, /X changes the detached quick-action rail/);
  assert.match(customize, /Y changes\/reorders the main Command Center cards/);
});
