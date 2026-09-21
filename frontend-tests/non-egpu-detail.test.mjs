import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/expanded-command-center/non-egpu-detail-source.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { createNonEgpuDetailPublisher, nonEgpuDetailKind } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);

test("detail source updates independently of unchanged tile labels and clears on owner loss", () => {
  const publisher = createNonEgpuDetailPublisher();
  assert.equal(publisher.source.read(), null);
  let changes = 0;
  const unsubscribe = publisher.source.subscribe(() => changes++);
  const first = { performance: { busy: false }, controller: {} };
  publisher.publish(first);
  assert.equal(publisher.source.read(), first);
  assert.equal(publisher.source.read(), publisher.source.read());
  publisher.publish(first);
  assert.equal(changes, 1);
  const busy = { ...first, performance: { busy: true } };
  publisher.publish(busy);
  assert.equal(publisher.source.read(), busy);
  publisher.publish(null);
  assert.equal(publisher.source.read(), null);
  assert.equal(changes, 3);
  unsubscribe();
  publisher.publish(first);
  assert.equal(changes, 3);
});

test("only supported tab and tile pairs reach the existing detail modules", () => {
  for (const tab of ["quick", "performance"]) for (const id of ["manual", "auto"])
    assert.equal(nonEgpuDetailKind(tab, id), "power");
  assert.equal(nonEgpuDetailKind("quick", "controller"), "controller");
  for (const id of ["controller", "builtin", "priority"])
    assert.equal(nonEgpuDetailKind("controllers", id), "controller");
  for (const tab of ["quick", "performance", "egpu", "controllers", "settings"])
    for (const id of ["disconnect", "display", "power", "fps", "record", "appearance", "unknown"])
      assert.equal(nonEgpuDetailKind(tab, id), null);
  assert.equal(nonEgpuDetailKind("egpu", "manual"), null);
  assert.equal(nonEgpuDetailKind("settings", "controller"), null);
});

test("renderer forwards the current owner handles without creating a collector", async () => {
  let current = { performance: { busy: false, apply() {} }, controller: { reason: "Unknown" } };
  const runtime = {
    useSyncExternalStore: (_subscribe, read) => read(),
    AutoTdpModule: function AutoTdpModule() {}, ControllerModule: function ControllerModule() {},
    jsx: (type, props) => ({ type, props }), nonEgpuDetailKind,
  };
  const rendererSource = readFileSync(new URL("../src/quick-access/expanded-command-center/non-egpu-detail-renderer.tsx", import.meta.url), "utf8");
  const output = ts.transpileModule(rendererSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {};
  new Function("require", "exports", output)(() => runtime, exports);
  const render = exports.createNonEgpuDetailRenderer({ read: () => current, subscribe: () => () => {} });
  const element = render("quick", { id: "manual" });
  assert.equal(element.type(element.props).props.controller, current.performance);
  current = { ...current, performance: { busy: true } };
  assert.equal(element.type(element.props).props.controller, current.performance);
  const controller = render("controllers", { id: "priority" });
  assert.equal(controller.type(controller.props).props.presentation, current.controller);
  assert.equal(render("egpu", { id: "disconnect" }), null);
  current = null;
  assert.equal(element.type(element.props), null);
});
