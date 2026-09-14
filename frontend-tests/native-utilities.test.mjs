import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const base = "../src/quick-access/expanded-command-center/";
const compile = (name) => ts.transpileModule(readFileSync(new URL(base + name, import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
}).outputText;
const {testBuildTiles,unavailableTestActions}=await import(`data:text/javascript;base64,${Buffer.from(compile("test-build-actions.ts")).toString("base64")}`);
const GamepadButton={DIR_UP:9,DIR_DOWN:10,DIR_LEFT:11,DIR_RIGHT:12};
const { createNativeUtilities } = await import(`data:text/javascript;base64,${Buffer.from(compile("native-utilities.ts")).toString("base64")}`);
const settle = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const devices = (id = 4, volume = .4) => ({ activeOutputDeviceId: id, vecDevices: [{ id, bHasOutput: true, flOutputVolume: volume }] });
function systemHarness() {
  const callbacks = new Map(), registrations = [], writes = [];
  let snapshot = devices(), get = async () => snapshot, writeResult = { result: 1 };
  const register = (owner, name) => function (callback) {
    assert.equal(this, owner, `${name} receiver`);
    callbacks.set(name, callback);
    const subscription = { closed: 0, unregister() { this.closed++; } };
    registrations.push(subscription);
    return subscription;
  };
  const Display = { SetBrightness(value) { assert.equal(this, Display); writes.push(["brightness", value]); } };
  Display.RegisterForBrightnessChanges = register(Display, "brightness");
  const Audio = {
    GetDevices() { assert.equal(this, Audio); return get(); },
    async SetDeviceVolume(...args) { assert.equal(this, Audio); writes.push(["volume", ...args]); return writeResult; },
  };
  for (const method of ["RegisterForDeviceVolumeChanged", "RegisterForDeviceAdded", "RegisterForDeviceRemoved", "RegisterForServiceConnectionStateChanges"]) Audio[method] = register(Audio, method);
  return { system: { Display, Audio }, callbacks, registrations, writes,
    setDevices(value) { snapshot = value; }, setGet(value) { get = value; }, setResult(value) { writeResult = value; } };
}

test("native observation enables normalized readings without optimistic brightness writes", async () => {
  const h = systemHarness(), utility = createNativeUtilities(h.system);
  assert.equal(utility.read().brightness.available, false);
  assert.equal(h.registrations.length, 0);
  utility.start(); await settle();
  assert.equal(utility.read().brightness.available, false);
  assert.equal(utility.read().volume.percent, 40);
  h.callbacks.get("brightness")({ flBrightness: .65 });
  assert.equal(utility.read().brightness.percent, 65);
  await utility.request("brightness", 25);
  assert.deepEqual(h.writes, [["brightness", .25]]);
  assert.equal(utility.read().brightness.percent, 65, "setter acceptance must not invent readback");
  h.callbacks.get("brightness")({ flBrightness: .25 });
  assert.equal(utility.read().brightness.percent, 25);
  utility.stop();
});

test("volume resolves current output at dispatch and uses AllOutput=1 with normalized units", async () => {
  const h = systemHarness(), utility = createNativeUtilities(h.system);
  utility.start(); await settle();
  h.setDevices(devices(19, .73));
  await utility.request("volume", 60);
  assert.deepEqual(h.writes, [["volume", 19, 1, .6]]);
  assert.equal(utility.read().volume.percent, 73, "readback, not requested number, becomes visible");
  h.setDevices(devices(23, .2));
  h.callbacks.get("RegisterForDeviceAdded")(); await settle();
  assert.equal(utility.read().volume.percent, 20);
  utility.stop();
});

test("absent providers, invalid percentages and malformed observations never dispatch", async () => {
  const missing = createNativeUtilities({}); missing.start();
  await assert.rejects(missing.request("brightness", 50));
  await assert.rejects(missing.request("volume", 50));
  missing.stop();
  const h = systemHarness(), utility = createNativeUtilities(h.system);
  utility.start(); await settle();
  for (const value of [NaN, Infinity, -1, 101, undefined, "40"]) await assert.rejects(utility.request("volume", value));
  for (const id of ["mic", "wifi", "recording", "overlay", "audio"]) await assert.rejects(utility.request(id, 50));
  for (const value of [NaN, Infinity, -1, 1.01, "0.5", undefined]) {
    h.callbacks.get("brightness")({ flBrightness: value });
    assert.equal(utility.read().brightness.available, false);
  }
  h.setDevices({ activeOutputDeviceId: 99, vecDevices: devices().vecDevices });
  h.callbacks.get("RegisterForDeviceRemoved")(); await settle();
  assert.equal(utility.read().volume.available, false);
  assert.deepEqual(h.writes, []);
  utility.stop();
});

test("audio read failures invalidate availability and rejected writes do not invent success", async () => {
  const h = systemHarness(), utility = createNativeUtilities(h.system);
  utility.start(); await settle();
  h.setResult({ result: 2 });
  await assert.rejects(utility.request("volume", 90));
  assert.equal(utility.read().volume.percent, 40);
  h.setGet(async () => { throw new Error("service offline"); });
  h.callbacks.get("RegisterForServiceConnectionStateChanges")(); await settle();
  assert.equal(utility.read().volume.available, false);
  await assert.rejects(utility.request("volume", 50));
  assert.equal(h.writes.length, 1);
  utility.stop();
});

test("start is idempotent; stop unregisters every hook and rejects later writes", async () => {
  const h = systemHarness(), utility = createNativeUtilities(h.system);
  let notifications = 0;
  const unsubscribe = utility.subscribe(() => notifications++);
  utility.start(); utility.start(); await settle();
  assert.equal(h.registrations.length, 5);
  const brightness = h.callbacks.get("brightness");
  utility.stop();
  assert.ok(h.registrations.every(item => item.closed === 1));
  const before = notifications;
  unsubscribe(); brightness({ flBrightness: .9 });
  assert.equal(utility.read().brightness.available, false);
  assert.equal(notifications, before);
  await assert.rejects(utility.request("volume", 30));
  assert.deepEqual(h.writes, []);
});

test("old async read cannot replace state after close and reopen", async () => {
  const h = systemHarness(), old = deferred(), utility = createNativeUtilities(h.system);
  h.setGet(() => old.promise);
  utility.start();
  const oldBrightness = h.callbacks.get("brightness");
  utility.stop(); h.setGet(async () => devices(8, .8)); utility.start(); await settle();
  old.resolve(devices(4, .1)); oldBrightness({ flBrightness: .9 }); await settle();
  assert.equal(utility.read().volume.percent, 80);
  assert.equal(utility.read().brightness.available, false);
  utility.stop();
});

test("a request awaiting route discovery cannot write after its menu generation closes", async () => {
  const h = systemHarness(), utility = createNativeUtilities(h.system);
  utility.start(); await settle();
  const discovery = deferred(); h.setGet(() => discovery.promise);
  const request = utility.request("volume", 70);
  const rejected = assert.rejects(request);
  utility.stop(); h.setGet(async () => devices(8, .8)); utility.start(); await settle();
  discovery.resolve(devices(4, .4)); await rejected;
  assert.deepEqual(h.writes, []);
  assert.equal(utility.read().volume.percent, 80);
  utility.stop();
});

const React = { createElement: (type, props, ...children) => ({ type, props: { ...props, children } }) };
function loadComponent(name, exported, bindings = {}) {
  const js = compile(name).replace(/^import[\s\S]*?;\s*$/gm, "").replace(/export /g, "");
  return new Function("React", ...Object.keys(bindings), `${js}\nreturn ${exported};`)(React, ...Object.values(bindings));
}
const flatten = value => Array.isArray(value) ? value.flatMap(flatten)
  : value && typeof value === "object" ? [value, ...flatten(value.props?.children)] : [];
const hooks = { useRef: value => ({ current: value }), useState: value => [value, () => {}], useLayoutEffect: () => {}, useEffect: () => {}, useSyncExternalStore: (_, read) => read() };
const model = await import(`data:text/javascript;base64,${Buffer.from(compile("model.ts")).toString("base64")}`);
const registryUrl=`data:text/javascript;base64,${Buffer.from(compile("control-registry.ts")).toString("base64")}`;
const registry=await import(registryUrl);
const layout = await import(`data:text/javascript;base64,${Buffer.from(compile("utility-layout.ts").replace(/['"]\.\/control-registry['"]/g,JSON.stringify(registryUrl))).toString("base64")}`);
const catalog=await import(`data:text/javascript;base64,${Buffer.from(compile("button-catalog.ts").replace(/['"]\.\/control-registry['"]/g,JSON.stringify(registryUrl))).toString("base64")}`);
const Rail = loadComponent("utility-rail.tsx", "UtilityRail", { ...hooks, ...layout, ...registry, CommandCenterIcon: "icon" });
const Shell = loadComponent("shell.tsx", "ExpandedCommandCenter", { ...hooks, ...model, ...registry, ...catalog, UtilityRail: Rail, CommandCenterIcon: "icon", expandedStyles: "", brandIcon: "brand" });

test("shell forwards live readings and requests to real rail range handlers; arrows stay native", async () => {
  const calls = [], readings = { brightness: { available: true, value: "50%", percent: 50 }, volume: { available: true, value: "40%", percent: 40 } };
  const onRequest = async (...args) => { calls.push(args); };
  const tree = Shell({ onClose() {}, utilityReadings: readings, onUtilityRequest: onRequest });
  const rails = flatten(tree).filter(node => node.type === Rail);
  assert.equal(rails.length, 2);
  const left = rails.find(node => node.props.side === "left");
  assert.equal(left.props.readings, readings);
  assert.equal(left.props.onRequest, onRequest);
  const rendered = Rail(left.props);
  const sliders = flatten(rendered).filter(node => node.type === "input");
  sliders[0].props.onChange({ currentTarget: { value: "23" } });
  sliders[1].props.onChange({ currentTarget: { value: "67" } });
  await settle();
  assert.deepEqual(calls, [["brightness", 23], ["volume", 67]]);
  const panel = flatten(tree).find(node => node.props?.["data-ec-panel"] !== undefined);
  for (const key of ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"]) {
    let prevented = false;
    panel.props.onKeyDown({ key, target: { matches: selector => selector === 'input[type="range"]', closest: selector => selector === '[data-utility-side]' ? {} : null }, preventDefault() { prevented = true; }, stopPropagation() { prevented = true; } });
    assert.equal(prevented, false, key);
  }
});

test("rapid range input serializes writes and coalesces to the final requested value", async () => {
  const pending = deferred(), calls = [];
  const tree = Rail({ side: "left", readings: { brightness: { available: true, percent: 50, value: "50%" } }, onRequest: async (...args) => { calls.push(args); if (calls.length === 1) await pending.promise; } });
  const input = flatten(tree).find(node => node.type === "input" && node.props["aria-label"] === "Brightness");
  for (const value of [10, 20, 30, 40]) input.props.onChange({ currentTarget: { value: String(value) } });
  assert.deepEqual(calls, [["brightness", 10]]);
  pending.resolve(); await settle();
  assert.deepEqual(calls, [["brightness", 10], ["brightness", 40]]);
});

test("native menu forwards adapter state and calls into the real shell and rail", async () => {
  const h = systemHarness();
  let modalTree, closed = 0;
  const Native = loadComponent("native.tsx", "createExpandedMenu", {
    ...hooks, createNativeUtilities, testBuildTiles, unavailableTestActions, GamepadButton, EgpuConfirmModal:"confirm", ExpandedCommandCenter: Shell,
    createMenuVisibility: () => ({ source: {}, set() {} }),
    loadMenuBinding: () => "none", saveMenuBinding: () => true, menuBindingOptions: [],
    startMenuShortcut: () => ({ available: true, stop() {}, reset() {} }),
    Button: "button", Dropdown: "select", Focusable: "div", ModalRoot: "modal",
    ShortcutSettings: "settings", WholeDockControl: "dock",
    showModal: tree => { modalTree = tree; return { Close() { closed++; } }; },
  });
  const menu = Native(undefined, { SteamClient: { System: h.system } });
  menu.open(); await settle(); h.callbacks.get("brightness")({ flBrightness: .5 });
  const view = flatten(modalTree).find(node => typeof node.type === "function");
  const shellElement = view.type(view.props);
  assert.equal(shellElement.type, Shell);
  const renderedShell = Shell(shellElement.props);
  const left = flatten(renderedShell).find(node => node.type === Rail && node.props.side === "left");
  const range = flatten(Rail(left.props)).find(node => node.type === "input" && node.props["aria-label"] === "Brightness");
  range.props.onChange({ currentTarget: { value: "35" } }); await settle();
  assert.deepEqual(h.writes, [["brightness", .35]]);
  const pendingWrite = deferred();
  h.system.Display.SetBrightness = function(value) {
    assert.equal(this, h.system.Display);
    h.writes.push(["brightness", value]);
    return pendingWrite.promise;
  };
  range.props.onChange({ currentTarget: { value: "45" } });
  range.props.onChange({ currentTarget: { value: "85" } });
  assert.deepEqual(h.writes, [["brightness", .35], ["brightness", .45]]);
  shellElement.props.onClose();
  menu.open(); await settle();
  h.callbacks.get("brightness")({ flBrightness: .6 });
  await assert.rejects(shellElement.props.onUtilityRequest("brightness", 95), "old view callbacks must not reach a reopened menu");
  pendingWrite.resolve(); await settle();
  assert.deepEqual(h.writes, [["brightness", .35], ["brightness", .45]], "the old rail's queued value must not write in a new menu generation");
  menu.stop(); assert.equal(closed, 2);
  assert.ok(h.registrations.every(item => item.closed === 1));
  const noSteam = Native(undefined, {}); noSteam.open();
  const plainView = flatten(modalTree).find(node => typeof node.type === "function");
  const plain = plainView.type(plainView.props);
  assert.equal(plain.props.onUtilityRequest, undefined);
  assert.deepEqual(plain.props.utilityReadings, {});
  noSteam.stop();
});

// Append to frontend-tests/native-utilities.test.mjs: uses its Rail, flatten, deferred, settle.
const railDirections = { up: 9, down: 10, left: 11, right: 12 }; // @decky/ui FooterLegend.d.ts
function railHarness({ unavailable = false, onRequest = async () => {} } = {}) {
  const h = { returned: 0, focused: null };
  const tree = Rail({ side: 'left', directions: railDirections,
    readings: { brightness: { available: !unavailable, percent: 50, value: '50%' }, volume: { available: true, percent: 40, value: '40%' } },
    onRequest, onReturnToGrid: () => h.returned++ });
  h.nodes = flatten(tree).filter(n => n.props?.['data-utility-slider'] !== undefined);
  h.wrappers = h.nodes.map((node, index) => {
    const inputNode = flatten(node).find(n => n.type === 'input');
    const input = { tagName: 'INPUT', value: String(inputNode.props.value), disabled: inputNode.props.disabled, focus() { h.focused = input; } };
    const wrapper = { tagName: 'DIV', input, querySelector(selector) { return selector.includes(':not(:disabled)') && input.disabled ? null : input; }, focus() { h.focused = wrapper; } };
    return wrapper;
  });
  for (const wrapper of h.wrappers) wrapper.parentElement = { querySelectorAll: () => h.wrappers };
  h.event = (index, editing = false, button) => ({ target: editing ? h.wrappers[index].input : h.wrappers[index], currentTarget: h.wrappers[index], detail: { button }, prevented: 0, stopped: 0, preventDefault() { this.prevented++; }, stopPropagation() { this.stopped++; } });
  h.direction = (index, editing, button) => { const event = h.event(index, editing, button); h.nodes[index].props.onGamepadDirection(event); return event; };
  return h;
}
test('native rail selects wrappers, enters editing with A, and returns to grid with RIGHT', () => {
  const calls = [], h = railHarness({ onRequest: async (...args) => calls.push(args) });
  const event = h.direction(0, false, railDirections.down);
  assert.equal(h.focused, h.wrappers[1]); assert.equal(event.prevented, 1); assert.equal(event.stopped, 1);
  h.direction(1, false, railDirections.up); assert.equal(h.focused, h.wrappers[0]);
  h.nodes[0].props.onOKButton(h.event(0)); assert.equal(h.focused, h.wrappers[0], "native A retains its registered wrapper");
  h.nodes[0].props.onCancelButton(h.event(0, true)); assert.equal(h.focused, h.wrappers[0]);
  h.direction(0, true, railDirections.right); assert.equal(h.returned, 1);
  h.direction(1, false, railDirections.right); assert.equal(h.returned, 2);
  assert.deepEqual(calls, []);
});
test('native rail editing accumulates repeated directions and coalesces pending requests', async () => {
  const pending = deferred(), calls = [];
  const h = railHarness({ onRequest: async (...args) => { calls.push(args); if (calls.length === 1) await pending.promise; } });
  h.direction(0, true, railDirections.up); h.direction(0, true, railDirections.up); h.direction(0, true, railDirections.up);
  assert.deepEqual(calls, [['brightness', 53]]);
  pending.resolve(); await settle();
  assert.deepEqual(calls, [['brightness', 53], ['brightness', 59]]);
});
test('native direction targeted at Focusable still adjusts its focused input',async()=>{
  const calls=[],h=railHarness({onRequest:async(...args)=>calls.push(args)});
  h.wrappers[0].ownerDocument={activeElement:h.wrappers[0].input};
  h.direction(0,false,railDirections.up);await settle();
  assert.deepEqual(calls,[['brightness',53]]);
  h.nodes[0].props.onCancelButton(h.event(0,false));assert.equal(h.focused,h.wrappers[0]);
});
test('unavailable slider never dispatches and cannot enter editing', async () => {
  const calls = [], h = railHarness({ unavailable: true, onRequest: async (...args) => calls.push(args) });
  h.nodes[0].props.onOKButton(h.event(0)); assert.equal(h.focused, null);
  h.direction(0, true, railDirections.up); await settle(); assert.deepEqual(calls, []);
});
