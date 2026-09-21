import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
const js = ts.transpileModule(readFileSync(new URL("../src/link-recovery-model.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { recoveryOffered, recoveryResult } = await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));
const offered = () => ({ schema_version: 1, availability: "offered", offered: true,
  code: "link_recovery.available", strategies: [{ strategy: "session_restart", implemented: true }] });

test("only an explicit supported plain restart can be offered", () => {
  assert.equal(recoveryOffered(offered()), true);
  for (const value of [null, undefined, [], {}, true, { ...offered(), schema_version: 2 },
    { ...offered(), offered: "true" }, { ...offered(), availability: "unavailable" },
    { ...offered(), code: "link_recovery.game_running" }, { ...offered(), strategies: [] },
    { ...offered(), strategies: [{ strategy: "session_stop_start", implemented: true }] },
    { ...offered(), strategies: [{ strategy: "session_restart", implemented: "true" }] }]) {
    assert.equal(recoveryOffered(value), false);
  }
});

test("unknown payloads and raw diagnostics cannot become player success", () => {
  for (const value of [null, {}, { schema_version: 2, ok: true, code: "link_recovery.trained" },
    { schema_version: 1, ok: false, code: "link_recovery.trained" },
    { schema_version: 1, ok: true, code: "private raw diagnostic" }]) {
    assert.doesNotMatch(recoveryResult(value), /GPU is available|private raw diagnostic/);
  }
  assert.match(recoveryResult({ schema_version: 1, ok: true, code: "link_recovery.trained" }), /remaining connection steps/);
  assert.doesNotMatch(recoveryResult({ schema_version: 1, ok: true, code: "link_recovery.trained" }), /TV ready|disconnect|unplug/);
});
