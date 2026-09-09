import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const js = ts.transpileModule(
  readFileSync(new URL("../src/display-action.ts", import.meta.url), "utf8"),
  {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ES2022,
    },
  },
).outputText;
const { displayAction } = await import(
  "data:text/javascript;base64," + Buffer.from(js).toString("base64")
);

const action = (mode, over = {}) =>
  displayAction({
    mode,
    busy: false,
    acknowledgementRequired: false,
    journalBlocked: false,
    shortcutAvailable: false,
    ...over,
  });

test("both docked modes offer the way back to the handheld", () => {
  // The defect: only docked_egpu was recognised, so a player on the TV in
  // tv_docked had no return control at all. Both modes put them in front of a
  // television and both must offer the way back.
  for (const mode of ["tv_docked", "docked_egpu"]) {
    assert.equal(action(mode).target, "ally");
    assert.equal(action(mode).title, "Switch to handheld");
    assert.equal(action(mode).disabled, false);
  }
  assert.equal(action("portable").target, "tv");
  assert.equal(action("portable").title, "Switch to TV");
});

test("unknown, degraded and boosted modes do not acquire a transition", () => {
  for (const mode of [undefined, "unknown", "degraded", "boosted_handheld"]) {
    assert.equal(action(mode).target, null);
    assert.equal(action(mode).disabled, true);
    assert.match(action(mode).description, /unverified/);
  }
});

test("TV return retains its gates with actionable explanations", () => {
  assert.equal(action("tv_docked", { acknowledgementRequired: true }).disabled, true);
  assert.match(
    action("tv_docked", { acknowledgementRequired: true }).description,
    /Acknowledge/,
  );
  assert.equal(action("tv_docked", { journalBlocked: true }).disabled, true);
  assert.match(
    action("tv_docked", { journalBlocked: true }).description,
    /prior operation/,
  );
  assert.equal(action("tv_docked", { busy: true }).disabled, true);
  assert.match(action("tv_docked", { busy: true }).description, /Wait/);
  assert.equal(action("tv_docked", { busy: true }).title, "Switching…");
});

test("a gate outranks the shortcut hint, so the reason is never hidden", () => {
  // The hint is what to do when the control works. A blocked control has
  // something more useful to say.
  const blocked = action("tv_docked", {
    journalBlocked: true,
    shortcutAvailable: true,
  });

  assert.match(blocked.description, /prior operation/);
  assert.doesNotMatch(blocked.description, /Back\/View/);
});

test("an offered action is never a claim that switching is authorised", () => {
  // Presentation only. Execution still goes through the backend's approval
  // token, and disabled:false is not permission.
  const view = action("portable");

  assert.deepEqual(Object.keys(view).sort(), [
    "description",
    "disabled",
    "target",
    "title",
  ]);
});

test("every mode produces a title, so no control renders blank", () => {
  for (const mode of [undefined, "unknown", "portable", "tv_docked", "docked_egpu"]) {
    assert.ok(action(mode).title.length > 0);
    assert.ok(action(mode).description.length > 0);
  }
});
