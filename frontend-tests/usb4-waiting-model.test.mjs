import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const code = ts.transpileModule(readFileSync(new URL("../src/usb4-waiting-model.ts", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { usb4WaitingObservation, createUsb4WaitingMemory, validUsb4WaitingReceipt, USB4_WAITING_TEXT } =
  await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
const key = n => `uw-${n.toString(16).padStart(32, "0")}`;
const wire = (state = "unauthorized", notice_key = key(1)) => ({ schema_version: 1, state, notice_key });
const reply = (waiting = wire(), admission = {}) => ({
  runtime_admission: { schema_version: 1, sleep_interceptor_admission: "observation-only",
    mode: "observation-only", mutation_allowed: false, ...admission }, usb4_waiting: waiting,
});

test("same-response exact observation-only admission qualifies closed categorical evidence", () => {
  assert.deepEqual(usb4WaitingObservation(reply()), { state: "unauthorized", noticeKey: key(1) });
  for (const state of ["none", "authorized", "unknown", "ambiguous"]) {
    assert.deepEqual(usb4WaitingObservation(reply(wire(state, null))), { state, noticeKey: null });
  }
  assert.equal(USB4_WAITING_TEXT, "An attached USB4 device is waiting for system authorization. Re-Gear cannot approve devices on this handheld. Inspect the system device prompt and verify the attached device before deciding what to do.");
});
test("missing malformed supported or mutation-capable admission never qualifies", () => {
  for (const admission of [null, {}, [], { schema_version: 2 },
    { schema_version: 1, sleep_interceptor_admission: "supported-runtime", mode: "observation-only", mutation_allowed: false },
    { schema_version: 1, sleep_interceptor_admission: "observation-only", mode: "supported-runtime", mutation_allowed: false },
    { schema_version: 1, sleep_interceptor_admission: "observation-only", mode: "observation-only", mutation_allowed: true }]) {
    assert.equal(usb4WaitingObservation({ runtime_admission: admission, usb4_waiting: wire() }), null);
  }
  assert.equal(usb4WaitingObservation({ usb4_waiting: wire() }), null);
});
test("wire rejects unknown schemas states key grammar private extras and state/key mismatches", () => {
  for (const value of [null, [], {}, wire("UNAUTHORIZED"), wire("none"), wire("unauthorized", null),
    wire("unauthorized", "private-address"), wire("unauthorized", `uw-${"A".repeat(32)}`),
    wire("unauthorized", `uw-${"a".repeat(31)}`), wire("unauthorized", key(1) + "\n"),
    { ...wire(), schema_version: "1" }, { ...wire(), schema_version: 2 },
    { ...wire(), name: "private device" }, { ...wire(), token: "private-token" },
    Object.create(wire()), Object.assign(wire(), { [Symbol("private")]: "private" })]) {
    assert.equal(usb4WaitingObservation(reply(value)), null);
  }
});
test("own data validation never executes getters or trusts inherited fields", () => {
  for (const [container, field] of [[reply(), "runtime_admission"], [reply(), "usb4_waiting"],
    [wire(), "state"], [wire(), "notice_key"]]) {
    Object.defineProperty(container, field, { enumerable: true, get() { throw Error("getter executed"); } });
    assert.equal(usb4WaitingObservation("schema_version" in container ? reply(container) : container), null);
  }
  const inherited = Object.create(reply());
  assert.equal(usb4WaitingObservation(inherited), null);
  const admission = Object.create(reply().runtime_admission);
  assert.equal(usb4WaitingObservation({ runtime_admission: admission, usb4_waiting: wire() }), null);
});
test("shown keys survive withdrawal dismiss/reopen and A to B to A replay", () => {
  const memory = createUsb4WaitingMemory();
  assert.equal(memory.claim(key(1)), true);
  assert.equal(memory.claim(key(1)), false);
  assert.equal(memory.claim(key(2)), true);
  assert.equal(memory.claim(key(1)), false);
  assert.equal(memory.size, 2);
});
test("64-key memory never evicts and suppresses the 65th and later keys", () => {
  const memory = createUsb4WaitingMemory();
  for (let n = 1; n <= 64; n++) assert.equal(memory.claim(key(n)), true);
  assert.equal(memory.saturated, true);
  for (let n = 65; n <= 200; n++) assert.equal(memory.claim(key(n)), false);
  assert.equal(memory.claim(key(1)), false);
  assert.equal(memory.size, 64);
  assert.equal(memory.claim("private-token"), false);
});

const receipt = (changes = {}) => Object.freeze({ payload: { ...reply(), snapshot: { schema_version: 3,
  observed_at: new Date(0).toISOString() } }, requestStartedAtMs: 0, receivedAtMs: 10,
  expiresAtMs: 10000, generation: 0, supportedLifetime: false, ...changes });
test("receipt freshness expires at the earlier request-start or observation boundary", () => {
  assert.equal(validUsb4WaitingReceipt(receipt(), 9999), true);
  assert.equal(validUsb4WaitingReceipt(receipt(), 10000), false);
  assert.equal(validUsb4WaitingReceipt(receipt({ requestStartedAtMs: 5 }), 9999), true);
  assert.equal(validUsb4WaitingReceipt(receipt({ requestStartedAtMs: 5, expiresAtMs: 10005 }), 9999), false);
});
test("receipt rejects future invalid accessor mixed mutable or nonown lifetime evidence", () => {
  for (const value of [null, {}, { ...receipt() }, Object.freeze(Object.create(receipt())),
    receipt({ receivedAtMs: 20 }), receipt({ requestStartedAtMs: 11 }), receipt({ expiresAtMs: Infinity }),
    receipt({ generation: -1 }), receipt({ generation: 0.5 }), receipt({ supportedLifetime: "false" }),
    receipt({ payload: { ...reply(), snapshot: { schema_version: 3, observed_at: "invalid" } } }),
    receipt({ payload: { ...reply(), snapshot: { schema_version: 3, observed_at: new Date(20).toISOString() } } }),
    Object.freeze({ ...receipt(), private: "token" })]) assert.equal(validUsb4WaitingReceipt(value, 10), false);
  const value = { ...receipt() };
  Object.defineProperty(value, "supportedLifetime", { get() { throw Error("getter executed"); } });
  assert.equal(validUsb4WaitingReceipt(Object.freeze(value), 10), false);
});
