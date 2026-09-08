import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access-section-state.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } });
const { requestedSectionId, applySectionSelection } =
  await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const closed = { showDiagnostics: false, chosen: "egpu" };

test("an open diagnostics boolean is the System section", () => {
  assert.equal(requestedSectionId({ showDiagnostics: true, chosen: "egpu" }), "system");
});

test("a closed panel resolves to the chosen row target", () => {
  assert.equal(requestedSectionId({ showDiagnostics: false, chosen: "display" }), "display");
});

test("the chosen target survives System being opened and closed", () => {
  // The row must return the player where they were, not to the default.
  const opened = applySectionSelection({ showDiagnostics: false, chosen: "tdp" }, "system");
  assert.equal(requestedSectionId(opened.next), "system");
  const back = applySectionSelection(opened.next, "tdp");
  assert.equal(requestedSectionId(back.next), "tdp");
});

test("selecting System opens the existing diagnostics boolean and refreshes", () => {
  const result = applySectionSelection(closed, "system");
  assert.equal(result.next.showDiagnostics, true);
  assert.equal(result.refresh, true);
});

test("re-selecting an open System does not re-request evidence", () => {
  // The existing Troubleshooting control refreshes on the closed -> open edge
  // only; a row target that refreshed on every press would poll the backend.
  const result = applySectionSelection({ showDiagnostics: true, chosen: "egpu" }, "system");
  assert.equal(result.next.showDiagnostics, true);
  assert.equal(result.refresh, false);
});

test("choosing another section closes System instead of stacking it", () => {
  const result = applySectionSelection({ showDiagnostics: true, chosen: "egpu" }, "controller");
  assert.equal(result.next.showDiagnostics, false);
  assert.equal(result.next.chosen, "controller");
  assert.equal(result.refresh, false);
});

test("no non-System target ever requests a refresh", () => {
  for (const id of ["egpu", "controller", "tdp", "display"]) {
    for (const open of [true, false]) {
      const result = applySectionSelection({ showDiagnostics: open, chosen: "egpu" }, id);
      assert.equal(result.refresh, false, id);
      assert.equal(result.next.showDiagnostics, false, id);
    }
  }
});

test("selection never mutates the state it was given", () => {
  const before = { showDiagnostics: false, chosen: "egpu" };
  applySectionSelection(before, "system");
  assert.deepEqual(before, { showDiagnostics: false, chosen: "egpu" });
});
