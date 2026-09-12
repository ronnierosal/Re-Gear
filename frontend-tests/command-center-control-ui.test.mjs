import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const controls = readFileSync(new URL("../src/quick-access/expanded-command-center/control-ui.tsx", import.meta.url), "utf8");
const details = readFileSync(new URL("../src/quick-access/expanded-command-center/action-details.tsx", import.meta.url), "utf8");

test("nested control kit stays presentation-only", () => {
  for (const forbidden of ["backend", "getSnapshot", "RPC", "fetch(", "localStorage", "sessionStorage"]) {
    assert.equal(controls.includes(forbidden), false, `control-ui must not own ${forbidden}`);
  }
});

test("performance controls keep approved concepts separate", () => {
  for (const label of ["Profile", "FPS target", "Manual TDP", "Auto TDP", "Resolution", "Refresh rate"]) {
    assert.ok(details.includes(`label=\"${label}\"`), `missing ${label}`);
  }
});

test("safe disconnect layout preserves safety distinctions", () => {
  assert.ok(details.includes("Safe Disconnect · ${readiness.value}"));
  assert.ok(details.includes("Physical unplug clearance is separate"));
  assert.ok(details.includes("successful software command or return to the handheld display"));
  assert.ok(details.includes("CommandProgressSteps"));
});

test("controller detail keeps player battery built-in priority and TV behavior distinct", () => {
  for (const label of ["Player 1", "Battery", "Built-in controller", "Controller priority", "TV dock behavior"]) {
    assert.ok(details.includes(`label=\"${label}\"`), `missing ${label}`);
  }
});

test("control primitives expose compact console patterns without inventing actions", () => {
  for (const component of ["CommandControlRow", "CommandRangePreview", "CommandSegmentedPreview", "CommandTogglePreview", "CommandProgressSteps"]) {
    assert.ok(controls.includes(`function ${component}`), `missing ${component}`);
  }
  assert.equal(controls.includes("onClick="), false);
  assert.equal(controls.includes("onChange="), false);
});
