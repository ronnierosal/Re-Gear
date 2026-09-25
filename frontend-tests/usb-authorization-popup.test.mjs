import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const read = file => readFileSync(new URL("../src/" + file, import.meta.url), "utf8");
const js = ts.transpileModule(read("usb-authorization-model.ts"), {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {usbAuthorizationView: view, usbAuthorizationRequest: request, usbDeviceLabel: label} = await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));

const offered = (extra = {}) => ({schema_version:1, state:"offered", code:"device_authorization.offered", token:"tok-1", vendor:"Example", model:"eGPU Dock 9", generation:3, confirmation_open:true, ...extra});

test("an offered, named device shows Allow once and Not now; Always trust only when offered by the backend", () => {
  const v = view({status: offered()});
  assert.equal(v.phase, "offer");
  assert.equal(v.headline, "Allow this eGPU?");
  assert.equal(v.deviceLabel, "Example eGPU Dock 9");
  assert.deepEqual(v.allowOnce, {visible:true, enabled:true});
  assert.deepEqual(v.alwaysTrust, {visible:false, enabled:false});
  assert.equal(v.notNow.label, "Not now");
  assert.match(v.body, /asked again/);
  assert.doesNotMatch(v.body, /remember|automatically/i, "without remembered trust the copy never promises to remember");
  const r = view({status: offered({remembered_grant_offered:true})});
  assert.deepEqual(r.alwaysTrust, {visible:true, enabled:true});
  assert.match(r.body, /trust it so it connects automatically/);
});

test("nothing is offered without a live token, a name and state=offered", () => {
  for (const status of [null, {}, offered({state:"unavailable"}), offered({token:""}), offered({vendor:"", model:""}), offered({state:"OFFERED"})]) {
    const v = view({status});
    assert.notEqual(v.phase, "offer", JSON.stringify(status));
    assert.equal(v.allowOnce.visible, false);
    assert.equal(v.alwaysTrust.visible, false);
  }
  assert.equal(view({status: offered({state:"unavailable", already_offered:true})}).phase, "gone");
});

test("device names are sanitized and bounded", () => {
  assert.equal(label({vendor:"Acme", model:"Acme TB4 Dock"}), "Acme TB4 Dock");
  assert.equal(label({vendor:"Ac\u0000me\n", model:""}), "Acme");
  assert.equal(label({vendor:"x".repeat(200)}).length, 64);
  assert.equal(label({vendor:42, model:{}}), "");
});

test("a confirmation always carries literal consent and the chosen action", () => {
  assert.deepEqual(request("tok-1", "authorize"), {token:"tok-1", consent:true, action:"authorize"});
  assert.deepEqual(request("tok-1", "enroll"), {token:"tok-1", consent:true, action:"enroll"});
});

test("submitted is not success; only a verified readback is approval", () => {
  const sending = view({status: offered(), pending:"authorize"});
  assert.equal(sending.phase, "submitting");
  assert.equal(sending.allowOnce.visible, false, "no second press while a choice is in flight");
  const checking = view({status: offered(), pending:"authorize", result: offered({requested:true, verified:null})});
  assert.equal(checking.phase, "checking");
  assert.equal(checking.headline, "Approval sent — checking");
  const once = view({status: offered(), pending:"authorize", result: offered({requested:true, verified:true})});
  assert.equal(once.phase, "approved");
  assert.equal(once.headline, "Approved for this connection");
  assert.doesNotMatch(once.body, /GPU (is )?ready|TV|connected to/i, "approval never claims GPU or display success");
  const always = view({status: offered({remembered_grant_offered:true}), pending:"enroll", result: offered({requested:true, verified:true})});
  assert.match(always.headline, /remember/);
  const failed = view({status: offered(), pending:"authorize", result: offered({requested:true, verified:false})});
  assert.equal(failed.phase, "not_approved");
});

test("refusals keep the device blocked and never read as approval", () => {
  const r = view({status: offered(), pending:"enroll", result: offered({requested:false, code:"device_authorization.remembered_grant_not_offered"})});
  assert.equal(r.phase, "refused");
  assert.match(r.body, /Always trust isn't available/);
  assert.equal(r.allowOnce.visible, true, "the same live token can still be used for Allow once");
  const gone = view({status: offered({token:"tok-2"}), pending:"enroll", result: offered({requested:false, code:"device_authorization.remembered_grant_not_offered"})});
  assert.equal(gone.allowOnce.visible, false, "a replaced attachment is never retried with another token");
  const unknown = view({status: offered(), pending:"authorize", result: offered({requested:false, code:"device_authorization.identity_unresolved"})});
  assert.match(unknown.body, /can't tell which device/);
  assert.equal(unknown.allowOnce.visible, false);
});

test("popup: Not now never authorizes, Always trust renders only when offered, no I/O or timers", () => {
  const popup = read("usb-authorization-popup.tsx");
  assert.match(popup, /view\.notNow\.visible && <DialogButton onClick=\{onDismiss\}>/);
  assert.match(popup, /view\.alwaysTrust\.visible && onAlwaysTrust &&/);
  assert.match(popup, /view\.allowOnce\.visible && onAllowOnce &&/);
  for (const file of ["usb-authorization-popup.tsx", "usb-authorization-model.ts"]) {
    assert.doesNotMatch(read(file), /setInterval|setTimeout|fetch\(|callable|from "\.\/backend"|boltctl|\/sys\//, file);
  }
  assert.doesNotMatch(read("index.tsx"), /usb-authorization/, "not wired: no runtime caller yet");
});
