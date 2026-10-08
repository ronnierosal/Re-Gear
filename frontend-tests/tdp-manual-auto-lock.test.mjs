import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
import { tdpControls, tdpMessage, tdpResultMessage, manualPresetOptions } from "../src/tdp-ui.ts";

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
  const effects = [];
  let effectCursor = 0;
  const useEffect = (effect, dependencies) => {
    const index = effectCursor++;
    if (!effects[index] || dependencies.some((value, i) => value !== effects[index][i])) {
      effects[index] = dependencies; effect();
    }
  };
  const source = readFileSync(new URL("../src/tdp-controls.tsx", import.meta.url), "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React },
  }).outputText.replace(/^import[^;]*;/gm, "").replace(/export /g, "");
  const component = new Function(
    "React", "useState", "useEffect", "tdpControls", "tdpMessage", "tdpResultMessage", "manualPresetOptions",
    "ButtonItem", "DropdownItem", "PanelSection", "PanelSectionRow", "ToggleField",
    "AutoTdpControls", "usePerformance", "ReadableBlock", `${code};return SharedTdpControls;`,
  )(
    { createElement: jsx, Fragment: "fragment" }, useState, useEffect,
    tdpControls, tdpMessage, tdpResultMessage, manualPresetOptions,
    "ButtonItem", "DropdownItem", "PanelSection", "PanelSectionRow", "ToggleField",
    "AutoTdpControls", () => { throw new Error("unexpected standalone controller"); },
    ({label,children})=>jsx("Field",{focusable:true,"aria-label":label},children),
  );
  return () => { cursor = 0; effectCursor = 0; return component({ visible: true, controller, initiallyExpanded: true }); };
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
  let tree = render();

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
  let tree = render();

  assert.doesNotMatch(flatten(tree).filter(value => typeof value === "string").join(" "), /Stop Auto TDP to adjust manually/);
  assert.equal(control(tree, "ToggleField", "Use Re-Gear power control").props.disabled, false);
  assert.equal(control(tree, "DropdownItem", "Power limit").props.disabled, false);
  assert.equal(control(tree, "ButtonItem", "Apply power limit").props.disabled, false);
  assert.equal(control(tree, "ButtonItem", "Restore previous power settings").props.disabled, false);

  control(tree, "ToggleField", "Use Re-Gear power control").props.onChange(false);
  control(tree, "DropdownItem", "Power limit").props.onChange({ data: 20 });
  tree = render();
  control(tree, "ButtonItem", "Apply power limit").props.onClick();
  control(tree, "ButtonItem", "Restore previous power settings").props.onClick();
  assert.deepEqual(subject.calls, [["enabled", false], ["apply", 20], ["restore"]]);
});

test("stopping Auto TDP locks manual mutation handlers even after running turns false", () => {
  for (const kind of ["auto", "owner"]) {
    const subject = controller({ running: false, stopping: kind === "auto" });
    subject.value.stopping = kind === "owner";
    const render = renderControls(subject.value); render(); const tree = render();
    for (const [type, label] of [["ToggleField", "Use Re-Gear power control"], ["DropdownItem", "Power limit"], ["ButtonItem", "Apply power limit"], ["ButtonItem", "Restore previous power settings"]]) assert.equal(control(tree, type, label).props.disabled, true);
    control(tree, "ToggleField", "Use Re-Gear power control").props.onChange(false);
    control(tree, "ButtonItem", "Apply power limit").props.onClick();
    control(tree, "ButtonItem", "Restore previous power settings").props.onClick();
    assert.deepEqual(subject.calls, []);
  }
});
test("fixed preset selection is local and existing Apply submits the staged value", () => {
  const subject = controller({ running: false, stopping: false });
  subject.value.manual = { ...manual, manual_presets: [{ id: "low", watts: 10, admitted: true }, { id: "balanced", watts: 15, admitted: true }, { id: "high", watts: 25, admitted: true }] };
  const render = renderControls(subject.value); render(); let tree = render();
  control(tree, "ButtonItem", "Chill · 10 W").props.onClick();
  assert.deepEqual(subject.calls, [], "selection must not enable, stop, or apply");
  tree = render(); control(tree, "ButtonItem", "Apply power limit").props.onClick();
  assert.deepEqual(subject.calls, [["apply", 10]]);
});

const presetStatus = (admitted = true) => ({ ...manual, manual_presets: [{ id: "low", watts: 10, admitted }, { id: "balanced", watts: 15, admitted }, { id: "high", watts: 25, admitted }] });
test("missing or malformed presets visibly disable choices while ordinary Manual remains usable", () => {
  for (const manual_presets of [undefined, [], [{ id: "low", watts: 11, admitted: true }]]) {
    const subject = controller({ running: false }); subject.value.manual = { ...manual, manual_presets };
    const render = renderControls(subject.value); render(); const tree = render();
    for (const label of ["Chill · 10 W", "Balanced · 15 W", "Performance · 25 W"]) {
      const button = control(tree, "ButtonItem", label); assert.equal(button.props.disabled, true); button.props.onClick();
    }
    assert.deepEqual(subject.calls, []);
    assert.equal(control(tree, "DropdownItem", "Power limit").props.disabled, false);
    assert.equal(control(tree, "ButtonItem", "Restore previous power settings").props.disabled, false);
  }
});
test("Enable remains explicit before preset selection, then one Apply and guarded Restore", () => {
  const subject = controller({ running: false }); subject.value.manual = { ...presetStatus(), enabled: false, ready: false };
  const render = renderControls(subject.value); render(); let tree = render();
  assert.equal(control(tree, "ButtonItem", "Chill · 10 W").props.disabled, true);
  control(tree, "ButtonItem", "Chill · 10 W").props.onClick(); assert.deepEqual(subject.calls, []);
  control(tree, "ToggleField", "Use Re-Gear power control").props.onChange(true);
  assert.deepEqual(subject.calls, [["enabled", true]]);
  subject.value.manual = presetStatus(); render(); tree = render();
  control(tree, "ButtonItem", "Performance · 25 W").props.onClick(); tree = render();
  control(tree, "ButtonItem", "Apply power limit").props.onClick();
  control(tree, "ButtonItem", "Restore previous power settings").props.onClick();
  assert.deepEqual(subject.calls, [["enabled", true], ["apply", 25], ["restore"]]);
});
test("withdrawn or replaced status and stopping invalidate old preset callbacks", () => {
  for (const change of ["withdraw", "missing", "replacement", "auto", "owner", "busy"]) {
    const subject = controller({ running: false }); subject.value.manual = presetStatus();
    const render = renderControls(subject.value); render(); let tree = render();
    control(tree, "ButtonItem", "Chill · 10 W").props.onClick(); tree = render();
    const oldApply = control(tree, "ButtonItem", "Apply power limit").props.onClick;
    const oldSelect = control(tree, "ButtonItem", "Balanced · 15 W").props.onClick;
    if (change === "withdraw") subject.value.manual = presetStatus(false);
    if (change === "missing") subject.value.manual = null;
    if (change === "replacement") subject.value.manual = presetStatus();
    if (change === "auto") subject.value.auto = { running: false, stopping: true };
    if (change === "owner") subject.value.stopping = true;
    if (change === "busy") subject.value.busy = true;
    oldApply(); oldSelect(); assert.deepEqual(subject.calls, [], change);
  }
});
test("ordinary watt selection clears preset intent and uses only existing Apply", () => {
  const subject = controller({ running: false }); subject.value.manual = presetStatus();
  const render = renderControls(subject.value); render(); let tree = render();
  control(tree, "ButtonItem", "Chill · 10 W").props.onClick(); tree = render();
  control(tree, "DropdownItem", "Power limit").props.onChange({ data: 20 }); tree = render();
  assert.ok(control(tree, "ButtonItem", "Chill · 10 W"));
  control(tree, "ButtonItem", "Apply power limit").props.onClick();
  assert.deepEqual(subject.calls, [["apply", 20]]);
});
