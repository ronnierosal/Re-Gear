import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8").replace(/\r\n/g, "\n");

test("player-facing modals use Steam's visible window host", () => {
  const modalCalls = source.match(/showModal\([\s\S]*?\n\s*window,\n\s*\{ strTitle:/g) ?? [];
  assert.ok(modalCalls.length >= 5);
  assert.doesNotMatch(source, /showModal\([\s\S]*?\n\s*undefined,\n\s*\{ strTitle:/);
});
