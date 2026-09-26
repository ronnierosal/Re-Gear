import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
import { tdpControls, tdpMessage, tdpResultMessage } from "../src/tdp-ui.ts";

const jsx = (type, props, ...children) => ({ type, props: { ...props, children } });
const flatten = node => [node, ...(node?.props?.children ?? []).flat(Infinity)
  .flatMap(child => typeof child === "object" && child !== null ? flatten(child) : [child])];
const control = (tree, type, label) => flatten(tree)
  .find(node => node?.type === type && (node.props.label === label || node.props.children.join("") === label));

function renderControls(controller) {
  let cursor = 0;
  const values = [];
  const useState = initial => {
    const index = cursor++;
    if (!(index in values)) values[index] = initial;
    return [values[index], value => { values[index] = typeof value === "function" ? value(values[index]) : value; }];
  };
  const useEffect = effect => { effect(); };
  const source = readFileSync(new URL("../src/tdp-controls.tsx", import.meta.url), "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React },
  }).outputText.replace(/^import[^;]*;/gm, "").replace(/export /g, "");
  const component = new Function(
    "React", "useState", "useEffect", "tdpControls", "tdpMessage", "tdpResultMessage",
    "ButtonItem", "DropdownItem", "PanelSection", "PanelSectionRow", "ToggleField",
    "AutoTdpControls", "usePerformance", `${code};return SharedTdpControls;`,
  )(
    { createElement: jsx, Fragment: "fragment" }, useState, useEffect,
    tdpControls, tdpMessage, tdpResultMessage,
    "ButtonItem", "DropdownItem", "PanelSection", "PanelSectionRow", "ToggleField",
    "AutoTdpControls", () => { throw new Error("unexpected standalone controller"); },
  );
  return () => { cursor = 0; return component({ visible: true, controller, initiallyExpanded: true }); };
}

const manual = {
  schema_version: 1, enabled: true, can_enable: true, ready: true,
  restore_available: true, recovery_required: false, current_watts: 15,
  minimum_watts: 7, maximum_watts: 30, auto_tdp_available: true,
  code: "tdp.ready", last_result: null,
};

function controller(auto) {
  const calls = [];
  return {
    value: {
      manual, auto, busy: false, stopping: false,
      apply: value => calls.push(["apply", value]),
      restore: () => calls.push(["restore"]),
      setEnabled: value => calls.push(["enabled", value]),
      refresh: () => calls.push(["refresh"]),
    },
    calls,
  };
}

test("running Auto TDP visibly locks every manual mutation while leaving refresh available", () => {
  const subject = controller({ running: true });
  const render = renderControls(subject.value);
  render();
  const tree = render();

  assert.match(flatten(tree).filter(value => typeof value === "string").join(" "), /Stop Auto TDP to adjust manually\./);
  assert.equal(control(tree, "ToggleField", "Use Re-Gear power control").props.disabled, true);
  assert.equal(control(tree, "DropdownItem", "Power limit").props.disabled, true);
  assert.equal(control(tree, "ButtonItem", "Apply power limit").props.disabled, true);
  assert.equal(control(tree, "ButtonItem", "Restore previous power settings").props.disabled, true);
  assert.equal(control(tree, "ButtonItem", "Refresh power settings").props.disabled, false);

  control(tree, "ToggleField", "Use Re-Gear power control").props.onChange(false);
  control(tree, "DropdownItem", "Power limit").props.onChange({ data: 20 });
  control(tree, "ButtonItem", "Apply power limit").props.onClick();
  control(tree, "ButtonItem", "Restore previous power settings").props.onClick();
  assert.deepEqual(subject.calls, []);
  control(tree, "ButtonItem", "Refresh power settings").props.onClick();
  assert.deepEqual(subject.calls, [["refresh"]]);
});

test("manual controls retain their existing behavior when Auto TDP is not running", () => {
  const subject = controller({ running: false });
  const render = renderControls(subject.value);
  render();
  const tree = render();

  assert.doesNotMatch(flatten(tree).filter(value => typeof value === "string").join(" "), /Stop Auto TDP to adjust manually/);
  assert.equal(control(tree, "ToggleField", "Use Re-Gear power control").props.disabled, false);
  assert.equal(control(tree, "DropdownItem", "Power limit").props.disabled, false);
  assert.equal(control(tree, "ButtonItem", "Apply power limit").props.disabled, false);
  assert.equal(control(tree, "ButtonItem", "Restore previous power settings").props.disabled, false);

  control(tree, "ToggleField", "Use Re-Gear power control").props.onChange(false);
  control(tree, "DropdownItem", "Power limit").props.onChange({ data: 20 });
  control(tree, "ButtonItem", "Apply power limit").props.onClick();
  control(tree, "ButtonItem", "Restore previous power settings").props.onClick();
  assert.deepEqual(subject.calls, [["enabled", false], ["apply", 15], ["restore"]]);
});
