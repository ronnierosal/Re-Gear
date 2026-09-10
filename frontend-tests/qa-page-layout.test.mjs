import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/page-layout.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020,
} }).outputText.replace(/^import[^;]*;$/gm, "");
const { PageLayout } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const slots = Object.fromEntries(["commandCenter", "modules", "egpu", "autoTdp", "controller", "egpuStatus", "controllerStatus", "troubleshoot", "picker"].map(key => [key, Object.freeze({ screen: key })]));
for (const [route, expected] of [
  [{ kind: "command-center" }, "commandCenter"], [{ kind: "modules" }, "modules"],
  [{ kind: "module", id: "egpu" }, "egpu"], [{ kind: "module", id: "auto-tdp" }, "autoTdp"],
  [{ kind: "module", id: "controller" }, "controller"],
  [{ kind: "status", id: "egpu" }, "egpuStatus"], [{ kind: "status", id: "controller" }, "controllerStatus"],
  [{ kind: "troubleshoot" }, "troubleshoot"],
  [{ kind: "picker", id: "tdp" }, "picker"],
  [{ kind: "picker", id: "display" }, "picker"],
]) test(`${JSON.stringify(route)} mounts only ${expected}`, () => {
  assert.equal(PageLayout({ ...slots, route }), slots[expected]);
});

// Inspect the real composition, not a duplicate fixture of its routing rules.
const index = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8");
const ast = ts.createSourceFile("index.tsx", index, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let layout;
function visit(node) {
  if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(ast) === "PageLayout") layout = node;
  ts.forEachChild(node, visit);
}
visit(ast);
const slot = name => layout.attributes.properties.find(p => p.name?.getText(ast) === name)?.initializer?.getText(ast) ?? "";
test("production Command Center slot contains quick controls without legacy settings", () => {
  assert.ok(layout);
  assert.match(slot("commandCenter"), /CommandCenterHeader/);
  assert.match(slot("commandCenter"), /CommandCenterGrid/);
  assert.match(slot("commandCenter"), /ModulesButton/);
  assert.doesNotMatch(slot("commandCenter"), /TdpControls|Automatic TV docking|Docking & actions|Support bundle/);
  assert.match(slot("autoTdp"), /AutoTdpModule/);
  assert.match(slot("egpu"), /Automatic TV docking/);
  assert.match(slot("egpu"), /activateDisplay/);
  assert.match(slot("picker"), /activateDisplay/);
  assert.match(slot("troubleshoot"), /Support bundle/);
});
test("hardware status destinations cannot invoke configuration actions", () => {
  for (const key of ["egpuStatus", "controllerStatus"]) {
    assert.doesNotMatch(slot(key), /onOpenRecovery|ToggleField|TdpControls|execute|requestSafeDisconnect/);
  }
});
