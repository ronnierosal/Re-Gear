import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/modules/controller-presentation.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } });
const { controllerPresentation, PLANNED_CONTROLLER_FEATURES } =
  await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const peripheral = (controller) => ({
  schema_version: 1,
  controller: { complete: true, exact: true, builtin_available: true, external_connected: false, code: "peripheral.ok", ...controller },
  audio: { complete: true, exact: true, external_available: null, portable_available: null, code: "peripheral.ok" },
});

test("no peripheral reading says status unavailable", () => {
  const p = controllerPresentation({ peripheral: null });
  assert.equal(p.available, false);
  assert.match(p.reason, /unavailable/i);
  assert.equal(p.builtin.known, false);
  assert.equal(p.external.known, false);
});

test("exact and complete facts are reported as facts", () => {
  const p = controllerPresentation({ peripheral: peripheral({}) });
  assert.equal(p.available, true);
  assert.equal(p.precision, "exact");
  assert.equal(p.precisionNote, null);
  assert.deepEqual(p.builtin, { text: "Available", known: true });
  assert.deepEqual(p.external, { text: "Not connected", known: true });
});

test("null fields stay Unknown and are never inferred from the other", () => {
  // An attached external pad says nothing about whether the built-in one works.
  const p = controllerPresentation({ peripheral: peripheral({ builtin_available: null, external_connected: true }) });
  assert.equal(p.builtin.known, false);
  assert.equal(p.builtin.text, "Unknown");
  assert.equal(p.external.text, "Connected");
});

test("an incomplete reading shows what it knows and flags the caveat", () => {
  // Incomplete is not absent: collapsing it to "no controller" loses evidence.
  const p = controllerPresentation({ peripheral: peripheral({ complete: false }) });
  assert.equal(p.precision, "partial");
  assert.match(p.precisionNote, /incomplete/i);
  assert.equal(p.available, true, "partial evidence is still evidence");
  assert.equal(p.builtin.text, "Available");
});

test("a reading with no usable facts is unavailable, not silently empty", () => {
  const p = controllerPresentation({ peripheral: peripheral({ builtin_available: null, external_connected: null }) });
  assert.equal(p.available, false);
  assert.match(p.reason, /no usable facts/i);
});

test("shortcut input is reported separately and is not controller presence", () => {
  // A usable input source does not mean a controller is attached.
  const p = controllerPresentation({ peripheral: null, shortcutAvailable: true });
  assert.deepEqual(p.shortcut, { text: "Available", known: true });
  assert.equal(p.builtin.known, false, "shortcut availability must not imply presence");
  assert.equal(p.available, false);
});

test("shortcut availability is unknown when not observed", () => {
  const p = controllerPresentation({ peripheral: peripheral({}) });
  assert.equal(p.shortcut.known, false);
  assert.equal(p.shortcut.text, "Unknown");
});

test("no device name, Player 1, or handoff state is ever produced", () => {
  const inputs = [
    { peripheral: null },
    { peripheral: peripheral({}), shortcutAvailable: true },
    { peripheral: peripheral({ complete: false, exact: false }) },
  ];
  for (const input of inputs) {
    const rendered = JSON.stringify(controllerPresentation(input));
    assert.doesNotMatch(rendered, /player\s*[12]/i, "no player assignment");
    assert.doesNotMatch(rendered, /xbox|dualsense|raikiri|steam deck|ally/i, "no invented identity");
  }
});

test("planned features are listed as planned, not as working controls", () => {
  const p = controllerPresentation({ peripheral: peripheral({}) });
  assert.deepEqual(p.planned, PLANNED_CONTROLLER_FEATURES);
  assert.ok(p.planned.includes("Player order"));
  // The model exposes no callable action anywhere: a page cannot accidentally
  // render a planned capability as a live toggle.
  for (const value of Object.values(p)) {
    assert.notEqual(typeof value, "function");
  }
});

test("planned features are reported the same whatever the evidence says", () => {
  // Their absence is a fact about the build, not about this device.
  const a = controllerPresentation({ peripheral: null });
  const b = controllerPresentation({ peripheral: peripheral({}), shortcutAvailable: true });
  assert.deepEqual(a.planned, b.planned);
});

const catalog = (values = {}) => ({ schema_version: 1, provider: "known", profile_metadata: "partial", virtual_target: "unknown", relationships: "unavailable", ...values });
const catalogTexts = (value) => Object.values(controllerPresentation({ peripheral: value }).catalog).map(f => f.text);
test("frozen catalog facts are independent and legacy facts stay intact", () => {
  const value = { ...peripheral({}), catalog: catalog() };
  assert.deepEqual(catalogTexts(value), ["Known", "Partial", "Unknown", "Unavailable"]);
  assert.deepEqual(controllerPresentation({ peripheral: value }).builtin, { text: "Available", known: true });
});
test("old denied malformed unsupported and private catalog replies clear all facts", () => {
  for (const value of [null, {}, Object.create({ catalog: catalog() }), { catalog: null }, { catalog: [] }, { catalog: catalog({ schema_version: 2 }) }, { catalog: catalog({ schema_version: "1" }) }, { catalog: catalog({ name: "private-path" }) }, { catalog: Object.create(catalog()) }]) {
    assert.deepEqual(catalogTexts(value), ["Unknown", "Unknown", "Unknown", "Unknown"]);
  }
});
test("valid catalog independently rejects missing inherited and arbitrary facts without stale fallback", () => {
  for (const bad of [undefined, null, {}, [], "KNOWN", "private-path", 1]) {
    assert.deepEqual(catalogTexts({ catalog: catalog({ provider: bad }) }), ["Unknown", "Partial", "Unknown", "Unavailable"]);
  }
  catalogTexts({ catalog: catalog() });
  assert.deepEqual(catalogTexts(null), ["Unknown", "Unknown", "Unknown", "Unknown"]);
});

function loadModule(url){
 const exports={};
 const jsx=(type,props)=>({type,props:props??{}});
 const code=ts.transpileModule(readFileSync(url,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
 new Function('exports','require',code)(exports,name=>{
  if(name==='react/jsx-runtime')return{jsx,jsxs:jsx};
  if(name==='@decky/ui')return{Field:'Field',Focusable:'Focusable',DialogButton:'DialogButton',GamepadButton:{DIR_UP:9,DIR_DOWN:10}};
  if(name.startsWith('.'))return loadModule(new URL(`${name}.tsx`,url));
  throw new Error(`Unexpected runtime dependency: ${name}`);
 });
 return exports;
}
function mount(node){
 if(Array.isArray(node))return node.flatMap(mount);
 if(!node||typeof node!=='object')return[];
 if(typeof node.type==='function')return mount(node.type(node.props));
 return[node,...mount(node.props.children)];
}

test("actual controller rows register read-only focus and preserve touch/Back ownership", () => {
  const { ControllerModule } = loadModule(new URL("../src/quick-access/modules/controller.tsx", import.meta.url));
  const presentation = controllerPresentation({ peripheral: { ...peripheral({}), catalog: catalog() }, shortcutAvailable: true });
  const tree = ControllerModule({ presentation });
  const fields = mount(tree).filter(n => n.type === "Field");
  assert.deepEqual(fields.slice(0,7).map(n => n.props["aria-label"]), ["Built-in controls: Available", "External controller: Not connected", "Shortcut input: Available", "Provider: Known", "Profile metadata: Partial", "Virtual target: Unknown", "Relationships: Unavailable"]);
  assert.equal(tree.props["flow-children"], "vertical");
  const previous = globalThis.HTMLElement;
  class Element { closest() { return null; } scrollIntoView(options) { this.options = options; } }
  globalThis.HTMLElement = Element;
  try {
    for (const field of fields) {
      assert.equal(field.props.focusable, true);
      assert.equal(field.props.highlightOnFocus, false);
      for (const handler of ["onClick", "onOKButton", "onActivate", "onCancelButton"]) assert.equal(field.props[handler], undefined);
      assert.equal(typeof field.props.onGamepadDirection, "function");
      const target = new Element();
      field.props.onGamepadFocus({ currentTarget: target });
      assert.deepEqual(target.options, { block: "nearest", inline: "nearest" });
    }
  } finally { globalThis.HTMLElement = previous; }
  const reopened = mount(ControllerModule({ presentation: controllerPresentation({ peripheral: null }) })).filter(n => n.type === "Field");
  assert.ok(reopened.some(n => n.props["aria-label"] === "Provider: Unknown"));
});
test("catalog accessors never run or expose private values", () => {
  const value = catalog();
  Object.defineProperty(value, "provider", { get() { throw new Error("private getter"); }, enumerable: true });
  assert.deepEqual(catalogTexts({ catalog: value }), ["Unknown", "Partial", "Unknown", "Unavailable"]);
  Object.defineProperty(value, "schema_version", { get() { throw new Error("private schema getter"); } });
  assert.deepEqual(catalogTexts({ catalog: value }), ["Unknown", "Unknown", "Unknown", "Unknown"]);
});

test("real request lifetime expires and rejects cancelled or superseded catalog responses", async () => {
  const path = new URL("../src/quick-access/expanded-command-center/controller-reading-lifetime.ts", import.meta.url);
  const code = ts.transpileModule(readFileSync(path, "utf8"), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
  const { createControllerReadingLifetime } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
  let now = 0;
  const store = createControllerReadingLifetime({ now: () => now, schedule: () => () => {} });
  store.setEligible(true);
  const reading = { ...peripheral({}), catalog: catalog() };
  const first = store.start(); now = 3500; store.complete(first, reading);
  assert.equal(catalogTexts(store.source.read())[0], "Known");
  now = 10000; assert.equal(catalogTexts(store.source.read())[0], "Unknown");
  const old = store.start(); const fresh = store.start();
  store.complete(fresh, { ...reading, catalog: catalog({ provider: "partial" }) });
  store.complete(old, reading);
  assert.equal(catalogTexts(store.source.read())[0], "Partial");
  store.setEligible(false); store.setEligible(true); store.complete(fresh, reading);
  assert.deepEqual(catalogTexts(store.source.read()), ["Unknown", "Unknown", "Unknown", "Unknown"]);
});
