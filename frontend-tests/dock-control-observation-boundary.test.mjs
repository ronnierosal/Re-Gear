import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

// Exercise production eligibility with a fixed clock. Snapshot schema and
// expiry must agree with the expanded menu's observation gate before either
// surface offers an operation. Backend dispatch remains separately guarded.
const js = ts.transpileModule(readFileSync(new URL("../src/whole-dock-control-model.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { dockControl } = await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));

const now = Date.parse("2026-09-12T18:00:00.000Z");
const status = {
  schema_version: 1, busy: false, safe_to_unplug: false,
  code: "dock_teardown.no_trial",
  attachment_token: "a".repeat(64) + ":" + "b".repeat(64),
};
const snapshot = (age, schema_version = 3) => ({
  schema_version, game_state: "idle", egpu_link: { state: "up" },
  observed_at: new Date(now - age).toISOString(),
});

test("fresh supported snapshot preserves dock disconnect eligibility", () => {
  for (const age of [0, 9999]) {
    assert.equal(dockControl(status, snapshot(age), now).action, "whole_dock_disconnect");
  }
});

for (const schema of [null, 2, 4, "3"]) {
  test(`unsupported snapshot schema ${JSON.stringify(schema)} cannot offer dock disconnect`, () => {
    assert.equal(dockControl(status, snapshot(0, schema), now).action, null);
  });
}

test("missing snapshot schema cannot offer dock disconnect", () => {
  const unversioned = snapshot(0);
  delete unversioned.schema_version;
  assert.equal(dockControl(status, unversioned, now).action, null);
});

test("snapshot expires at exactly ten seconds, matching expanded menu freshness", () => {
  assert.equal(dockControl(status, snapshot(10000), now).action, null);
});

test("older and future snapshot observations remain unavailable", () => {
  for (const age of [10001, -1]) {
    assert.equal(dockControl(status, snapshot(age), now).action, null);
  }
});
