import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/disconnect-result.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } });
const { disconnectResult } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const outcome = (over = {}) => ({
  schema_version: 1, stage: "removed", code: "live_disconnect.ok", ok: true, released: true,
  session_disturbed: true, removed: ["0000:08:00.1", "0000:08:00.0"], restored: [],
  display_released: [98], display_release_code: "ok", filter_disarmed: true,
  device_disturbed: false, ...over,
});

const UNPLUG_CLAIMS = [
  /safe to (unplug|disconnect|remove)/i,
  /you (can|may) (now )?(unplug|disconnect|remove)/i,
  /(ok|okay|fine) to (unplug|disconnect|remove)/i,
  /ready to (unplug|disconnect)/i,
];

test("nothing to report renders nothing", () => {
  for (const value of [null, undefined]) {
    assert.equal(disconnectResult(value).show, false);
  }
});

test("a successful removal says what happened", () => {
  const r = disconnectResult(outcome());
  assert.equal(r.show, true);
  assert.equal(r.tone, "done");
  assert.match(r.headline, /detached in software/i);
  assert.ok(r.detail.some((d) => /2 eGPU functions were removed/i.test(d)));
  assert.ok(r.detail.some((d) => /Steam session was restarted/i.test(d)));
  assert.ok(r.detail.some((d) => /external display was turned off/i.test(d)));
});

test("the unplug answer is present on every outcome, not only failures", () => {
  // A reassurance that appears conditionally teaches a player that its absence
  // means go ahead. This one never varies.
  const cases = [
    outcome(),
    outcome({ ok: false, released: false, removed: [], restored: ["0000:08:00.0"] }),
    outcome({ device_disturbed: true }),
    outcome({ session_disturbed: false, display_released: [], filter_disarmed: false }),
  ];
  const answers = new Set();
  for (const value of cases) {
    const r = disconnectResult(value);
    assert.ok(r.unplug.length > 0, "every shown result answers the unplug question");
    assert.match(r.unplug, /do not unplug/i);
    assert.match(r.unplug, /shut the handheld down first/i, "a refusal must say what to do instead");
    answers.add(r.unplug);
  }
  assert.equal(answers.size, 1, "the answer does not vary with the outcome");
});

test("no outcome ever produces an unplug clearance, in any field", () => {
  // Invariant 10 forbids physical live unplug for this hardware, and issue 147
  // asking whether to scope it is open and undecided.
  const cases = [
    outcome(), outcome({ ok: true, released: true, device_disturbed: false }),
    outcome({ ok: false, released: false }), outcome({ device_disturbed: true }),
    outcome({ removed: [], restored: [], display_released: [], session_disturbed: false }),
  ];
  for (const value of cases) {
    const rendered = JSON.stringify(disconnectResult(value));
    for (const claim of UNPLUG_CLAIMS) {
      assert.doesNotMatch(rendered, claim, `${claim} appeared for ${JSON.stringify(value.code)}`);
    }
  }
});

test("a half-detached device outranks success and failure alike", () => {
  // Not a failed button press: reporting it as one invites the player to
  // simply press it again.
  const r = disconnectResult(outcome({ device_disturbed: true, ok: true, released: true }));
  assert.equal(r.attention, true);
  assert.equal(r.tone, "attention");
  assert.match(r.headline, /needs attention/i);
  assert.ok(r.detail.some((d) => /half detached/i.test(d)));
  assert.ok(r.detail.some((d) => /restore it before/i.test(d)));
});

test("a clean failure is distinguished from one that left the device moved", () => {
  const restored = disconnectResult(outcome({ ok: false, released: false, removed: [], restored: ["0000:08:00.0"] }));
  assert.equal(restored.tone, "failed");
  assert.ok(restored.detail.some((d) => /left as it was/i.test(d)));
  const notRestored = disconnectResult(outcome({ ok: false, released: false, removed: [], restored: [] }));
  assert.ok(notRestored.detail.some((d) => /was not detached/i.test(d)));
});

test("only facts the outcome actually reported are stated", () => {
  const quiet = disconnectResult(outcome({
    session_disturbed: false, display_released: [], filter_disarmed: false, removed: [],
  }));
  const rendered = quiet.detail.join(" ");
  assert.doesNotMatch(rendered, /session was restarted/i);
  assert.doesNotMatch(rendered, /display was turned off/i);
  assert.doesNotMatch(rendered, /filter was disarmed/i);
});

test("singular and plural removals both read correctly", () => {
  const one = disconnectResult(outcome({ removed: ["0000:08:00.0"] }));
  assert.ok(one.detail.some((d) => /One eGPU function was removed/i.test(d)));
  const two = disconnectResult(outcome());
  assert.ok(two.detail.some((d) => /2 eGPU functions were removed/i.test(d)));
});
