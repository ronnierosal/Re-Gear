import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import ts from "typescript";

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const compile = (path, jsx = false) => ts.transpileModule(read(path), {compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
  jsx: jsx ? ts.JsxEmit.ReactJSX : undefined,
}}).outputText;
const model = {};
new Function("exports", compile("src/usb-authorization-model.ts"))(model);

function loadRuntime(react = {}) {
  const jsx = (type, props) => ({type, props});
  const imports = {
    "@decky/ui": {Focusable: "focusable", ModalRoot: "modal", showModal: () => ({Close(){}})},
    react,
    "react/jsx-runtime": {jsx, jsxs: jsx},
    "./usb-authorization-model": model,
    "./usb-authorization-popup": {UsbAuthorizationPopup: "popup"},
  };
  const exports = {};
  new Function("exports", "require", "window", compile("src/usb-authorization-runtime.tsx", true))(
    exports, name => imports[name], {},
  );
  return exports;
}

const offer = overrides => ({
  schema_version: 1,
  state: "offered",
  code: "device_authorization.available",
  token: "a".repeat(32),
  vendor: "GPD",
  model: "G1",
  generation: 1,
  already_offered: false,
  intentional_disconnect: false,
  confirmation_open: false,
  remembered_grant_offered: true,
  ...overrides,
});

test("only an exact live schema-1 offer can mount; software-down stays silent", () => {
  const {authorizationOffer} = loadRuntime();
  assert.equal(authorizationOffer(offer())?.token, "a".repeat(32));
  assert.equal(authorizationOffer(offer({vendor:"Named Dock", model:""}))?.vendor, "Named Dock");
  for (const payload of [
    null,
    offer({schema_version: 2}),
    offer({state: "unavailable"}),
    offer({code: "device_authorization.already_offered"}),
    offer({token: "A".repeat(32)}),
    offer({token: "a".repeat(31)}),
    offer({vendor: "", model: ""}),
    offer({already_offered: true}),
    offer({intentional_disconnect: true}),
    offer({confirmation_open: true}),
    offer({generation: 1.5}),
    offer({remembered_grant_offered: undefined}),
  ]) assert.equal(authorizationOffer(payload), null);
});

test("monitor consumes the shared connection cycle, keeps one popup and retires stale work", () => {
  const {startUsbAuthorizationMonitor} = loadRuntime();
  const shown = [];
  let closed = 0;
  const monitor = startUsbAuthorizationMonitor({
    show(status, onClosed) {
      const shownItem = {status, onClosed}; shown.push(shownItem);
      return {close() { closed++; onClosed(); }};
    },
  });
  monitor.observe(offer());
  monitor.observe(offer());
  assert.equal(shown.length, 1);
  shown[0].onClosed();
  monitor.observe(offer({intentional_disconnect: true}));
  assert.equal(shown.length, 1);
  monitor.observe(offer());
  assert.equal(shown.length, 2);
  monitor.stop(); assert.equal(closed, 1);
  monitor.observe(offer());
  assert.equal(shown.length, 2);
});

test("shared-cycle refresh is single-flight and never joins the connection read promise", async () => {
  const {startUsbAuthorizationMonitor} = loadRuntime();
  let reads = 0, finish;
  const monitor = startUsbAuthorizationMonitor({show() { throw new Error("no offer expected"); }});
  const read = () => { reads++; return new Promise(resolve => { finish = resolve; }); };
  monitor.refresh(read); monitor.refresh(read);
  assert.equal(reads, 1);
  finish(offer({state:"unavailable"}));
  await Promise.resolve(); await Promise.resolve();
  monitor.refresh(read);
  assert.equal(reads, 2);
  monitor.stop();
  finish(offer());
  await Promise.resolve(); await Promise.resolve();
});

test("a late authorization offer pauses connection progress and resolves it without stacked modals", () => {
  const {startUsbAuthorizationMonitor} = loadRuntime();
  const shown = [];
  const monitor = startUsbAuthorizationMonitor({
    show(status, onClosed) { shown.push({status, onClosed}); return {close(){}}; },
  });
  let opened = 0, connectionClosed = 0, finished = 0;
  monitor.deferConnection(() => {
    opened++;
    return {Close() { connectionClosed++; }};
  }, () => { finished++; });
  assert.equal(opened, 1);
  monitor.observe(offer());
  assert.equal(connectionClosed, 1);
  assert.equal(shown.length, 1);
  shown[0].onClosed(true);
  assert.equal(opened, 2);
  monitor.observe(offer());
  assert.equal(connectionClosed, 2);
  shown[1].onClosed(false);
  assert.equal(finished, 1);
});

function dialogHarness(status = offer()) {
  const states = [], refs = [], effects = [];
  let stateCursor = 0, refCursor = 0, effectCursor = 0;
  const react = {
    useState(initial) { const index = stateCursor++; if (!(index in states)) states[index] = initial;
      return [states[index], value => { states[index] = typeof value === "function" ? value(states[index]) : value; }]; },
    useRef(initial) { const index = refCursor++; return refs[index] ??= {current: initial}; },
    useMemo(factory) { return factory(); },
    useEffect(effect) { const index = effectCursor++; if (!(index in effects)) effects[index] = effect; },
  };
  const runtime = loadRuntime(react);
  const calls = [], closed = [];
  const rpc = {
    async acknowledge(token) { calls.push(["acknowledge", token]); return {...status, state:"unavailable", code:"device_authorization.already_offered", accepted:true, already_offered:true, confirmation_open:true}; },
    async decline(token) { calls.push(["decline", token]); return {...status, state:"unavailable", accepted:true}; },
    async confirm(token, consent, action) { calls.push(["confirm", token, consent, action]); return {...status, requested:true, verified:true, code:"device_authorization.requested", already_offered:true, confirmation_open:false}; },
  };
  const render = () => { stateCursor = 0; refCursor = 0; effectCursor = 0;
    return runtime.UsbAuthorizationDialog({status, rpc, onClose:() => closed.push(true)}); };
  return {runtime, rpc, calls, closed, effects, render};
}

test("mounted popup acknowledges its displayed token before A authorizes", async () => {
  const h = dialogHarness(); let tree = h.render();
  const focusable = () => tree.props.children;
  assert.equal(focusable().props.children.props.view.allowOnce.enabled, false);
  h.effects[0](); await Promise.resolve(); await Promise.resolve();
  tree = h.render(); assert.equal(focusable().props.children.props.view.allowOnce.enabled, true);
  let prevented = 0, stopped = 0;
  focusable().props.onOKButton({preventDefault(){prevented++;},stopPropagation(){stopped++;}});
  await Promise.resolve(); await Promise.resolve();
  assert.deepEqual(h.calls.map(call => [call[0], ...call.slice(2)]), [
    ["acknowledge"], ["confirm", true, "authorize"],
  ]);
  assert.equal(prevented, 1); assert.equal(stopped, 1);
});

test("X enroll is conditional and B declines without authorizing", async () => {
  const trusted = dialogHarness(); let tree = trusted.render(); trusted.effects[0]();
  await Promise.resolve(); tree = trusted.render();
  tree.props.children.props.onSecondaryButton({preventDefault(){},stopPropagation(){}});
  await Promise.resolve(); await Promise.resolve();
  assert.deepEqual(trusted.calls.at(-1).slice(2), [true, "enroll"]);

  const once = dialogHarness(offer({remembered_grant_offered:false})); tree = once.render(); once.effects[0]();
  await Promise.resolve(); tree = once.render();
  assert.equal(tree.props.children.props.onSecondaryActionDescription, undefined);
  tree.props.children.props.onSecondaryButton({preventDefault(){},stopPropagation(){}});
  await Promise.resolve(); assert.equal(once.calls.some(call => call[0] === "confirm"), false);

  const declined = dialogHarness(); tree = declined.render(); declined.effects[0]();
  await Promise.resolve(); tree = declined.render();
  tree.props.children.props.onCancelButton({preventDefault(){},stopPropagation(){}});
  await Promise.resolve(); await Promise.resolve();
  assert.equal(declined.calls.some(call => call[0] === "confirm"), false);
  assert.equal(declined.calls.at(-1)[0], "decline");
  assert.equal(declined.closed.length, 1);
});

test("B waits for display acknowledgement before declining the shown token", async () => {
  const h = dialogHarness();
  let finish;
  h.rpc.acknowledge = token => new Promise(resolve => {
    h.calls.push(["acknowledge", token]); finish = resolve;
  });
  let tree = h.render(); h.effects[0]();
  tree.props.children.props.onCancelButton({preventDefault(){},stopPropagation(){}});
  await Promise.resolve();
  assert.deepEqual(h.calls.map(call => call[0]), ["acknowledge"]);
  finish({...offer(), state:"unavailable", code:"device_authorization.already_offered", accepted:true, already_offered:true, confirmation_open:true});
  await Promise.resolve(); await Promise.resolve();
  assert.deepEqual(h.calls.map(call => call[0]), ["acknowledge", "decline"]);
});

test("an unavailable remembered grant keeps the same-token Allow once fallback actionable", async () => {
  const h = dialogHarness();
  let confirmations = 0;
  h.rpc.confirm = async (token, consent, action) => {
    h.calls.push(["confirm", token, consent, action]);
    confirmations++;
    return confirmations === 1
      ? {...offer(), requested:false, verified:null, code:"device_authorization.remembered_grant_not_offered", already_offered:true, confirmation_open:true}
      : {...offer(), requested:true, verified:true, code:"device_authorization.requested", already_offered:true, confirmation_open:false};
  };
  let tree = h.render(); h.effects[0]();
  await Promise.resolve(); tree = h.render();
  tree.props.children.props.onSecondaryButton({preventDefault(){},stopPropagation(){}});
  await Promise.resolve(); await Promise.resolve();
  tree = h.render();
  const popup = tree.props.children.props.children;
  assert.equal(popup.props.view.allowOnce.enabled, true);
  popup.props.onAllowOnce();
  await Promise.resolve(); await Promise.resolve();
  assert.deepEqual(h.calls.filter(call => call[0] === "confirm").map(call => call.slice(2)), [
    [true, "enroll"], [true, "authorize"],
  ]);
});

test("malformed replies fail closed and enroll cannot claim remembered trust without enrollment proof", async () => {
  const malformed = dialogHarness();
  malformed.rpc.acknowledge = async token => ({...offer(), state:"unavailable", code:"device_authorization.runtime_unavailable", accepted:true, token, already_offered:true, confirmation_open:true});
  let tree = malformed.render(); malformed.effects[0]();
  await Promise.resolve(); await Promise.resolve();
  assert.equal(malformed.closed.length, 1);

  const contradictory = dialogHarness();
  contradictory.rpc.confirm = async (token, consent, action) => {
    contradictory.calls.push(["confirm", token, consent, action]);
    return {...offer(), requested:true, verified:true, code:"device_authorization.denied", already_offered:true, confirmation_open:false};
  };
  tree = contradictory.render(); contradictory.effects[0](); await Promise.resolve(); tree = contradictory.render();
  tree.props.children.props.onOKButton({preventDefault(){},stopPropagation(){}});
  await Promise.resolve(); await Promise.resolve();
  assert.equal(contradictory.closed.length, 1);

  const trusted = dialogHarness();
  tree = trusted.render(); trusted.effects[0](); await Promise.resolve(); tree = trusted.render();
  tree.props.children.props.onSecondaryButton({preventDefault(){},stopPropagation(){}});
  await Promise.resolve(); await Promise.resolve(); tree = trusted.render();
  assert.equal(tree.props.children.props.children.props.view.phase, "checking");
  assert.doesNotMatch(tree.props.children.props.children.props.view.headline, /remember/i);
  assert.equal(tree.props.children.props.onOKActionDescription, undefined);
  assert.equal(tree.props.children.props.onSecondaryActionDescription, undefined);
});

test("Y toggles Details through the native Options semantic", () => {
  const h = dialogHarness();
  const tree = h.render();
  const details = {open:false};
  // The first ref belongs to the Focusable root.
  h.render();
  const focusable = tree.props.children;
  focusable.props.ref.current = {querySelector: selector => selector === "details" ? details : null};
  focusable.props.onOptionsButton({preventDefault(){},stopPropagation(){}});
  assert.equal(details.open, true);
  assert.equal(focusable.props.onOptionsActionDescription, "Details");
});

test("plugin mounts and retires the authorization monitor with exact RPCs", () => {
  const backend = read("src/backend.ts"), index = read("src/index.tsx");
  for (const name of ["get_device_authorization_status", "acknowledge_device_authorization", "decline_device_authorization", "confirm_device_authorization"])
    assert.match(backend, new RegExp(`"${name}"`));
  assert.match(index, /const authorization = startUsbAuthorizationMonitor\(/);
  assert.match(index, /authorization\.refresh\(getDeviceAuthorizationStatus\)/);
  assert.match(index, /Promise\.all\(\[\s*getSnapshot\(\), getAutomaticDockStatus\(\), getTransitionJournalStatus\(\),/);
  assert.doesNotMatch(index, /Promise\.all\(\[[^\]]*getDeviceAuthorizationStatus/s);
  assert.doesNotMatch(read("src/usb-authorization-runtime.tsx"), /setTimeout|setInterval/);
  assert.match(index, /authorization\.stop\(\);connection\.stop\(\)/);
});
