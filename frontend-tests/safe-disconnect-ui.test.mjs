import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8");
const backend = readFileSync(new URL("../src/backend.ts", import.meta.url), "utf8");

test("safe disconnect returns Portable before offering confirmed shutdown", () => {
  assert.match(source, /Prepare to disconnect/);
  assert.match(source, /Shut down to disconnect/);
  assert.match(source, /approveSupervisedPortableSwitch/);
  assert.match(source, /executeSupervisedPortableSwitch/);
  assert.match(source, /approveSafeDisconnectShutdown/);
  assert.match(source, /executeSafeDisconnectShutdown/);
  assert.match(source, /request cannot prove physical power-off/);
  assert.match(source, /If the fan remains on after 60 seconds/);
  assert.doesNotMatch(source, /Safe to (?:unplug|disconnect) while powered/i);
  assert.match(backend, /"approve_supervised_portable_switch"/);
  assert.match(backend, /"execute_safe_disconnect_shutdown"/);
});
