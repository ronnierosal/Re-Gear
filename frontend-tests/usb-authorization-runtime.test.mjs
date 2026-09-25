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
  for (const payload of [
    null,
    offer({schema_version: 2}),
    offer({state: "unavailable"}),
    offer({code: "device_authorization.already_offered"}),
    offer({token: "A".repeat(32)}),
    offer({token: "a".repeat(31)}),
    offer({model: ""}),
    offer({already_offered: true}),
    offer({intentional_disconnect: true}),
    offer({confirmation_open: true}),
    offer({generation: 1.5}),
    offer({remembered_grant_offered: undefined}),
  ]) assert.equal(authorizationOffer(payload), null);
});

test("monitor polls without overlap, keeps one popup and retires stale work", async () => {
  const {startUsbAuthorizationMonitor} = loadRuntime();
  const timers = new Map(); let next = 1;
  const host = {
    setTimeout(callback) { const id = next++; timers.set(id, callback); return id; },
    clearTimeout(id) { timers.delete(id); },
  };
  const shown = [], statuses = [offer(), offer({intentional_disconnect: true})];
  let reads = 0, closed = 0;
  const monitor = startUsbAuthorizationMonitor({
    timers: host,
    async read() { reads++; return statuses.shift() ?? offer({state: "unavailable"}); },
    show(status, onClosed) {
      const shownItem = {status, onClosed}; shown.push(shownItem);
      return {close() { closed++; onClosed(); }};
    },
  });
  await Promise.resolve(); await Promise.resolve();
  assert.equal(reads, 1); assert.equal(shown.length, 1); assert.equal(timers.size, 1);
  const whileOpen = [...timers.values()][0]; timers.clear(); whileOpen();
  await Promise.resolve(); assert.equal(reads, 1); assert.equal(shown.length, 1);
  shown[0].onClosed();
  const afterClose = [...timers.values()][0]; timers.clear(); afterClose();
  await Promise.resolve(); await Promise.resolve();
  assert.equal(reads, 2); assert.equal(shown.length, 1);
  monitor.stop(); assert.equal(closed, 0); assert.equal(timers.size, 0);

  let finish;
  const stale = startUsbAuthorizationMonitor({
    timers: host,
    read: () => new Promise(resolve => { finish = resolve; }),
    show() { throw new Error("stale read opened a popup"); },
  });
  stale.stop(); finish(offer());
  await Promise.resolve(); await Promise.resolve();
  assert.equal(timers.size, 0);
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
    async acknowledge(token) { calls.push(["acknowledge", token]); return {...status, state:"unavailable", accepted:true, already_offered:true, confirmation_open:true}; },
    async decline(token) { calls.push(["decline", token]); return {...status, state:"unavailable", accepted:true}; },
    async confirm(token, consent, action) { calls.push(["confirm", token, consent, action]); return {...status, requested:true, verified:true, code:"device_authorization.verified"}; },
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

test("an unavailable remembered grant keeps the same-token Allow once fallback actionable", async () => {
  const h = dialogHarness();
  let confirmations = 0;
  h.rpc.confirm = async (token, consent, action) => {
    h.calls.push(["confirm", token, consent, action]);
    confirmations++;
    return confirmations === 1
      ? {...offer(), requested:false, verified:null, code:"device_authorization.remembered_grant_not_offered"}
      : {...offer(), requested:true, verified:true, code:"device_authorization.verified"};
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

test("plugin mounts and retires the authorization monitor with exact RPCs", () => {
  const backend = read("src/backend.ts"), index = read("src/index.tsx");
  for (const name of ["get_device_authorization_status", "acknowledge_device_authorization", "decline_device_authorization", "confirm_device_authorization"])
    assert.match(backend, new RegExp(`"${name}"`));
  assert.match(index, /const authorization = startUsbAuthorizationMonitor\(/);
  assert.match(index, /read: getDeviceAuthorizationStatus/);
  assert.match(index, /authorization\.stop\(\);connection\.stop\(\)/);
});
