import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const read = path => readFileSync(new URL(`../src/${path}`, import.meta.url), "utf8");
const compile = source => ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React,
} }).outputText;
function load(path, dependencies = {}) {
  const exports = {};
  new Function("exports", "require", compile(read(path)))(exports, name => {
    assert.ok(name in dependencies, `unexpected dependency ${name}`);
    return dependencies[name];
  });
  return exports;
}
const controller = load("controller-safe-disconnect.ts");
const { createDisplayShortcutRuntime } = load("display-shortcut-runtime.ts", {
  "./controller-safe-disconnect": controller,
});
const { createRuntimeDetailPublisher } = load("quick-access/expanded-command-center/runtime-detail-source.ts");
const source = read("index.tsx");
const tree = ts.createSourceFile("index.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const nodes = {};
function visit(node) {
  if (ts.isVariableDeclaration(node) && ["activateDisplay", "openConnectionProgress"].includes(node.name.getText(tree))) {
    nodes[node.name.getText(tree)] = node.initializer;
  }
  if (ts.isFunctionDeclaration(node) && node.name?.text === "showControllerDisplayConfirmation") nodes.modal = node;
  ts.forEachChild(node, visit);
}
visit(tree);
assert.ok(nodes.activateDisplay && nodes.openConnectionProgress && nodes.modal);
function evaluate(expression, env) {
  return new Function(...Object.keys(env), compile(`const value = ${expression};`) + "\nreturn value;")(...Object.values(env));
}
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };

// Run the real index activation, real runtime publisher and confirmation owner.
// Only modal rendering and backend RPC ports are fake; no device is accessed.
function harness(options = {}) {
  const calls = [], modals = [];
  const show = evaluate(`(${nodes.modal.getText(tree)})`, {
    React: { createElement: (type, props, ...children) => ({ type, props: { ...props, children } }) },
    ConfirmModal: "confirm", PRODUCT_NAME: "Re-Gear", window: {},
    showModal(node) {
      const modal = { node, Close() { calls.push("close"); } };
      modals.push(modal); calls.push("confirm"); return modal;
    },
  });
  const shortcut = createDisplayShortcutRuntime({
    input: {}, readContext: async () => null, show,
    approve: async target => {
      calls.push(`approve:${target}`);
      return { approval_token: "exact-token", blockers: options.blockers ?? [] };
    },
    execute: async (target, token) => {
      assert.equal(token, "exact-token"); calls.push(`execute:${target}`);
      return { accepted: true, code: "accepted" };
    },
    report() {},
  });
  const activate = evaluate(nodes.activateDisplay.getText(tree), {
    runtimeOwner: { stopped: options.stopped ?? false }, menuFresh: options.fresh ?? true,
    primaryDisplayAction: { target: options.target ?? "tv", disabled: options.disabled ?? false },
    requestControllerDisplaySwitch: shortcut.request,
    executeTvSwitch: async () => { calls.push("direct-tv"); },
  });
  const publisher = createRuntimeDetailPublisher();
  publisher.publish({ views: {}, displayAction: {
    target: options.target ?? "tv", available: options.available ?? true, reason: "", request: activate,
  } });
  return { calls, modals, activate, request: () => publisher.source.requestDisplayTarget(),
    stop() { publisher.stop(); shortcut.stop(); } };
}

test("manual TV activation confirms before any approval or execution", async () => {
  const h = harness();
  try {
    h.request(); await flush();
    assert.deepEqual(h.calls, ["confirm"]);
    assert.equal(h.modals[0].node.props.strTitle, "Switch to TV?");
    h.modals[0].node.props.onOK(); await flush();
    assert.deepEqual(h.calls, ["confirm", "close", "approve:tv", "execute:tv"]);
  } finally { h.stop(); }
});

test("cancelled manual TV confirmation sends zero approval and execute RPCs", async () => {
  const h = harness();
  try {
    h.request(); await flush();
    assert.equal(h.modals.length, 1);
    h.modals[0].node.props.onCancel(); await flush();
    assert.deepEqual(h.calls, ["confirm", "close"]);
    h.request(); assert.equal(h.modals.length, 2, "cancel releases the modal lock");
  } finally { h.stop(); }
});

test("repeated manual activation has one modal and one confirmed dispatch", async () => {
  const h = harness();
  try {
    h.request(); h.request(); h.activate();
    assert.equal(h.modals.length, 1);
    h.modals[0].node.props.onOK(); h.modals[0].node.props.onOK(); await flush();
    assert.equal(h.calls.filter(call => call === "approve:tv").length, 1);
    assert.equal(h.calls.filter(call => call === "execute:tv").length, 1);
  } finally { h.stop(); }
});

test("confirmed manual TV request preserves backend blocker rejection", async () => {
  const h = harness({ blockers: ["running_game"] });
  try {
    h.request(); h.modals[0].node.props.onOK(); await flush();
    assert.deepEqual(h.calls, ["confirm", "close", "approve:tv"]);
  } finally { h.stop(); }
});

for (const [name, options] of Object.entries({
  stale: { fresh: false }, stopped: { stopped: true }, disabled: { disabled: true },
  unavailable: { available: false }, noTarget: { target: "unknown" },
})) test(`manual display ${name} admission has no modal or RPC`, async () => {
  const h = harness(options);
  try { h.request(); await flush(); assert.deepEqual(h.calls, []); } finally { h.stop(); }
});

test("handheld manual route still uses the same confirmation owner", async () => {
  const h = harness({ target: "ally" });
  try {
    h.request(); assert.equal(h.modals[0].node.props.strTitle, "Switch to Handheld?");
    h.modals[0].node.props.onOK(); await flush();
    assert.deepEqual(h.calls, ["confirm", "close", "approve:ally", "execute:ally"]);
  } finally { h.stop(); }
});

test("connection standing-consent callback retains direct TV execution", () => {
  const calls = [];
  const open = evaluate(nodes.openConnectionProgress.arguments[0].getText(tree), {
    connection: { open(callback) { calls.push("connection"); callback(); } },
    executeTvSwitch() { calls.push("direct-tv"); },
    requestControllerDisplaySwitch() { calls.push("unexpected-confirmation"); },
  });
  open(); assert.deepEqual(calls, ["connection", "direct-tv"]);
});
