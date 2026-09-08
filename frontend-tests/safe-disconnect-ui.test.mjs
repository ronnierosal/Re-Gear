import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8");
const backend = readFileSync(new URL("../src/backend.ts", import.meta.url), "utf8");

test("safe disconnect returns Portable before offering confirmed shutdown", () => {
  assert.match(source, /Prepare to disconnect/);
  assert.match(source, /Shut down before unplugging/);
  assert.match(source, /approveSupervisedPortableSwitch/);
  assert.match(source, /executeSupervisedPortableSwitch/);
  assert.match(source, /approveSafeDisconnectShutdown/);
  assert.match(source, /executeSafeDisconnectShutdown/);
  assert.match(source, /request cannot prove physical power-off/);
  assert.match(source, /If the fan remains on after 60 seconds/);
  assert.doesNotMatch(source, /Safe to (?:unplug|disconnect) while powered/i);
});

test("the shutdown control names the ordering instead of promising a disconnect", () => {
  // "Shut down to disconnect" read as though the plugin performed the
  // disconnection, inviting an unplug while the Ally was still powering down.
  // Safety invariant 10 requires shutdown first and the physical unplug after.
  assert.doesNotMatch(source, /Shut down to disconnect/);
  assert.match(source, /Shut down before unplugging/);
  assert.match(source, /Keep the eGPU connected until fully powered off/);
  assert.match(backend, /"approve_supervised_portable_switch"/);
  assert.match(backend, /"execute_safe_disconnect_shutdown"/);
});
