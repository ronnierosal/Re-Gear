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

// The old route helper remains tested above; production now publishes nodes from one global owner.
const index = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8");
test("production landing mounts no legacy grid and runtime publishes configuration details",()=>{
 assert.match(index,/content: buildProfile === "development" \? <ReGearLanding/);assert.doesNotMatch(index,/<CommandCenterGrid|<PageLayout|Open expanded demo/);
 assert.match(index,/const egpuDetail=[\s\S]*Automatic TV docking/);assert.match(index,/const diagnosticDetail=[\s\S]*Support bundle/);assert.match(index,/const displayDetail=<DisplayPicker[\s\S]*onSwitch=\{activateDisplay\}/);
 const renderer=readFileSync(new URL('../src/quick-access/expanded-command-center/non-egpu-detail-renderer.tsx',import.meta.url),'utf8');assert.match(renderer,/<AutoTdpModule controller=\{state.performance\}/);
});
test("eGPU status separates observation from explicit configuration navigation",()=>{
 const status=index.slice(index.indexOf(': {egpu:wrapDetail('),index.indexOf('"egpu-config":wrapDetail('));
 assert.match(status,/<EgpuModule presentation=\{egpuPresentation\(payload\)\}\/>/);assert.match(status,/Configure docking/);assert.doesNotMatch(status,/onOpenRecovery|ToggleField|execute|requestSafeDisconnect|activateDisplay/);
});
