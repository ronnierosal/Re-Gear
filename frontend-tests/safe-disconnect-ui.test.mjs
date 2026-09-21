import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8");
const backend = readFileSync(new URL("../src/backend.ts", import.meta.url), "utf8");

test("legacy shutdown adapter remains guarded while normal disconnect uses the canonical launcher", () => {
  assert.match(source, /title="Safe Disconnect"[\s\S]*onClick=\{openDisconnect\}/);
  assert.doesNotMatch(source, /onClick=\{requestSafeDisconnect\}/);
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
  const actions=readFileSync(new URL("../src/quick-access/expanded-command-center/test-build-actions.ts",import.meta.url),"utf8");
  // Wired on 2026-09-15: both tiles open the guarded whole-dock route.
  assert.doesNotMatch(actions, /"disconnect-(sleep|shutdown)": /);
  assert.match(backend, /"approve_supervised_portable_switch"/);
  assert.match(backend, /"execute_safe_disconnect_shutdown"/);
});
