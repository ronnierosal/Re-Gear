import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/single-flight.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } });
const { createSingleFlight } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
};

test("two activations in the same tick dispatch exactly once", () => {
  // The defect this exists for: React state is not synchronous, so both
  // presses read the old busy value and both dispatch.
  const flight = createSingleFlight();
  const gate = deferred();
  let invocations = 0;
  const press = () => flight.run(async () => { invocations += 1; await gate.promise; });
  press();
  press();
  press();
  assert.equal(invocations, 1, "one confirmation must produce one operation");
  gate.resolve();
});

test("a refused press is reported as refused, not as a silent success", () => {
  const flight = createSingleFlight();
  const gate = deferred();
  const first = flight.run(async () => { await gate.promise; return "done"; });
  const second = flight.run(async () => "should not run");
  gate.resolve();
  return Promise.all([first, second]).then(([a, b]) => {
    assert.deepEqual(a, { ran: true, value: "done" });
    assert.equal(b.ran, false, "the caller must be able to tell it did not run");
  });
});

test("the claim is released after success, so the next press runs", async () => {
  const flight = createSingleFlight();
  let invocations = 0;
  await flight.run(async () => { invocations += 1; });
  await flight.run(async () => { invocations += 1; });
  assert.equal(invocations, 2);
});

test("a failure releases the claim rather than wedging the control", async () => {
  // A refused or failed attempt must never leave the button permanently dead.
  const flight = createSingleFlight();
  await assert.rejects(flight.run(async () => { throw new Error("backend refused"); }));
  assert.equal(flight.busy, false);
  let ran = false;
  await flight.run(async () => { ran = true; });
  assert.equal(ran, true, "the control still works after a failure");
});

test("a cancellation path releases the claim too", async () => {
  // Cancelling is an outcome, not an absence of one.
  const flight = createSingleFlight();
  await flight.run(async () => { /* the player dismissed the confirmation */ });
  assert.equal(flight.busy, false);
  const second = await flight.run(async () => "ran");
  assert.deepEqual(second, { ran: true, value: "ran" });
});

test("busy reports in-flight state without being the lock itself", async () => {
  const flight = createSingleFlight();
  const gate = deferred();
  assert.equal(flight.busy, false);
  const running = flight.run(async () => { await gate.promise; });
  assert.equal(flight.busy, true);
  gate.resolve();
  await running;
  assert.equal(flight.busy, false);
});

test("the claim is taken with nothing awaited before it", () => {
  // If anything were awaited between the check and the claim, a second press
  // could slip through the gap; this is the property the whole module rests on.
  const text = readFileSync(new URL("../src/quick-access/single-flight.ts", import.meta.url), "utf8");
  // Comments are stripped first: prose about awaiting is not an await, and
  // matching one made this assertion pass for the wrong reason.
  const body = text.slice(text.indexOf("async run"), text.indexOf("} finally"))
    .replace(/\/\/[^\n]*/g, "");
  const claim = body.indexOf("active = true");
  const firstAwait = body.indexOf("await");
  assert.ok(claim > 0, "the claim must exist");
  assert.ok(firstAwait > claim, "the claim must precede any await");
});
