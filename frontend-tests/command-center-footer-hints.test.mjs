import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/quick-access/expanded-command-center/footer-hints.tsx", import.meta.url), "utf8");

test("Quick Access advertises separate X quick-action editing and Y customization/move", () => {
  assert.match(source, /button: "X", label: "Quick Actions"/);
  assert.match(source, /button: "Y", label: "Customize"/);
  assert.match(source, /button: "Y", label: "Move", hold: true/);
});

test("non-Quick tabs expose move-only editing", () => {
  const nonQuick = source.slice(source.indexOf("} else {"));
  assert.match(nonQuick, /button: "Y", label: "Move", hold: true/);
  assert.doesNotMatch(nonQuick, /label: "Quick Actions"/);
});

test("edit modes replace normal hints with place or choose affordances", () => {
  assert.match(source, /mode === "move"/);
  assert.match(source, /button: "A", label: "Place"/);
  assert.match(source, /button: "B", label: "Cancel"/);
  assert.match(source, /mode === "quick-actions"/);
  assert.match(source, /button: "A", label: "Choose"/);
});
