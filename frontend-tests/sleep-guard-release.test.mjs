import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/sleep-guard-release.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
});
const m = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const guard = (required, active) => ({ snapshot: { sleep_guard: { required, active, confidence: "verified", reason: "", error: "" } } });

function rig(payloads, { reconcile = () => true } = {}) {
  const calls = [];
  const seen = [];
  let i = 0;
  const ports = {
    async read() {
      calls.push("read");
      const next = payloads[Math.min(i++, payloads.length - 1)];
      if (next instanceof Error) throw next;
      return next;
    },
    reconcile(payload) { calls.push("reconcile"); seen.push(payload); return reconcile(payload); },
    async wait(ms) { calls.push(`wait:${ms}`); },
  };
  return { ports, calls, seen };
}

test("a guard that is neither required nor held releases on the first read", async () => {
  const r = rig([guard(false, false)]);
  assert.deepEqual(await m.awaitSleepGuardRelease(r.ports), { released: true });
  assert.deepEqual(r.calls, ["read", "reconcile"], "no wait before the first read");
});

test("a guard still held after the backend stopped wanting it is waited for, with evidence", async () => {
  // The backend decides `required` from presence; the login1 lease drops on its
  // next 1 s reconcile. That gap is the race the manual trial hit.
  const clear = guard(false, false);
  const r = rig([guard(false, true), guard(false, true), clear]);
  assert.deepEqual(await m.awaitSleepGuardRelease(r.ports), { released: true });
  assert.equal(r.calls.filter((c) => c === "read").length, 3);
  // The preflight decides from the same evidence that passed, not an earlier read.
  assert.equal(r.seen.length, 1);
  assert.equal(r.seen[0], clear);
  assert.equal(r.calls.filter((c) => c.startsWith("wait")).length, 2, "one wait between each read");
});

test("a guard the backend still requires never releases, and says why", async () => {
  // An eGPU that still needs a sleep guard would wake the handheld straight
  // back up. Refusing is the smaller harm.
  const r = rig([guard(true, true)]);
  const result = await m.awaitSleepGuardRelease(r.ports);
  assert.deepEqual(result, { released: false, code: "guard_required" });
  assert.equal(r.calls.filter((c) => c === "read").length, m.RELEASE_ATTEMPTS, "the whole budget is spent");
  assert.ok(!r.calls.includes("reconcile"), "the preflight is never asked to drop a blocker that is still needed");
});

test("a guard held for the whole budget refuses rather than sleeping into it", async () => {
  const r = rig([guard(false, true)]);
  assert.deepEqual(await m.awaitSleepGuardRelease(r.ports), { released: false, code: "guard_held" });
});

test("the preflight has the last word even when the backend says clear", async () => {
  // Only `reconcile` may drop the Steam-side blocker, and it decides from the
  // same payload. If it still wants the blocker, sleep is refused.
  const r = rig([guard(false, false)], { reconcile: () => false });
  assert.deepEqual(await m.awaitSleepGuardRelease(r.ports), { released: false, code: "blocker_required" });
});

test("an unreadable snapshot is not evidence of a released guard", async () => {
  const r = rig([new Error("rpc down")]);
  assert.deepEqual(await m.awaitSleepGuardRelease(r.ports), { released: false, code: "unreadable" });
  const missing = rig([{ snapshot: {} }]);
  assert.deepEqual(await m.awaitSleepGuardRelease(missing.ports), { released: false, code: "unreadable" });
});

test("a transient read failure is retried, not treated as final", async () => {
  const r = rig([new Error("blip"), guard(false, false)]);
  assert.deepEqual(await m.awaitSleepGuardRelease(r.ports), { released: true });
});

test("the budget is bounded and never leaves a timer running", async () => {
  const r = rig([guard(true, true)]);
  await m.awaitSleepGuardRelease(r.ports);
  const waits = r.calls.filter((c) => c.startsWith("wait"));
  assert.equal(waits.length, m.RELEASE_ATTEMPTS - 1);
  assert.ok(waits.every((c) => c === `wait:${m.RELEASE_INTERVAL_MS}`));
});
