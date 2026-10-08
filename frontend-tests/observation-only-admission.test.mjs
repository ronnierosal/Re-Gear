import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import { sleepProtectionLabel } from "../src/diagnostics-overlay.ts";

const source = ts.createSourceFile("index.tsx", fs.readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let expression;
function visit(node) {
  if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(source) === "DiagnosticRow") {
    const attrs = node.attributes.properties;
    if (attrs.some(a => a.name?.getText(source) === "name" && a.initializer?.text === "System inhibitor")) {
      expression = attrs.find(a => a.name?.getText(source) === "value").initializer.expression.getText(source);
    }
  }
  ts.forEachChild(node, visit);
}
visit(source);
assert.ok(expression, "actual production System inhibitor expression exists");
const mountedLabel = (sleepGuard, loading = false) => vm.runInNewContext(expression, {sleepGuard, loading});

test("actual production inhibitor and overlay label never infer absence from unknown or errored evidence", () => {
  for (const guard of [undefined, {}, {required: false, active: false, confidence: "unknown", error: ""},
    {required: false, active: false, confidence: "observed", error: ""},
    {required: true, active: true, confidence: "stale", error: ""},
    {required: false, active: false, confidence: "verified", error: "unreadable"}]) {
    assert.match(mountedLabel(guard), /Unknown.*unverified/);
    assert.match(sleepProtectionLabel(guard), /Unknown.*unverified/);
  }
});

test("actual production known protection and verified absence labels are preserved", () => {
  for (const [guard, expected] of [
    [{required: true, active: true, confidence: "verified", error: ""}, "Active"],
    [{required: true, active: false, confidence: "observed", error: ""}, "Inactive"],
    [{required: false, active: false, confidence: "verified", error: ""}, "Not required"],
  ]) {
    assert.equal(mountedLabel(guard), expected);
    assert.equal(sleepProtectionLabel(guard), expected);
  }
  assert.equal(mountedLabel(undefined, true), "Checking…");
});
