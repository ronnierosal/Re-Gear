import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const native = readFileSync(new URL("../src/quick-access/expanded-command-center/native.tsx", import.meta.url), "utf8");

test("the global shortcut opens Re-Gear in Steam's focused overlay", () => {
  assert.match(native, /<View token=\{token\}\/>[\s\S]*<\/ModalRoot>, undefined, \{ strTitle: "Re-Gear Command Center", bNeverPopOut: true \}/);
  assert.doesNotMatch(native, /<\/ModalRoot>, host, \{ strTitle:/);
  assert.doesNotMatch(native, /expanded demo/);
});
