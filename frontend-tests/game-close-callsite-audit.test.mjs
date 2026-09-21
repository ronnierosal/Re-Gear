import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

/** Pin the one structural guarantee the call-site change bought.
 *
 * The wiring module's own tests prove its gates refuse correctly. They cannot
 * prove the panel goes through it -- that is a property of the call site, and it
 * is the property that was missing: `game-close-flow.ts` shipped for days with
 * zero production callers while the panel removed the eGPU directly.
 *
 * So this audits reachability rather than behaviour. A removal must not be
 * reachable from the panel except through the gates, and the gates must survive
 * into the artifact that reaches a device.
 *
 * Deliberately not a grep for the bare word. `src/index.tsx` explains in a
 * comment why `executeEgpuDisconnect` is no longer imported, and the sibling
 * bundle audit was itself nearly broken by a docstring quoting the wording it
 * removed. A test that cannot tell code from prose gets switched off.
 */

const INDEX = new URL("../src/index.tsx", import.meta.url);
const PORTS = new URL("../src/quick-access/game-close-ports.ts", import.meta.url);

const indexSource = readFileSync(INDEX, "utf8");
const portsSource = readFileSync(PORTS, "utf8");

/** Source with comments removed, so prose cannot satisfy or fail a claim. */
function code(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^[ \t]*\/\/.*$/gm, "");
}

const indexCode = code(indexSource);

test("the panel cannot reach a removal without the wiring", () => {
  assert.equal(
    /\bexecuteEgpuDisconnect\s*\(/.test(indexCode),
    false,
    "src/index.tsx calls executeEgpuDisconnect directly again. That removes the " +
      "eGPU from underneath a running game without closing it, asking about it, " +
      "or reopening it. Route the press through runGameClosePress instead.",
  );
  assert.equal(
    /import\s*\{[^}]*\bexecuteEgpuDisconnect\b[^}]*\}\s*from\s*"\.\/backend"/s.test(
      indexCode,
    ),
    false,
    "src/index.tsx imports executeEgpuDisconnect again. Dropping the import is " +
      "what makes the bypass unreachable rather than merely unused.",
  );
});

test("the legacy panel retains only pending reopen wiring", () => {
  assert.ok(indexCode.includes("claimRelaunchOnMount"));
  assert.equal(indexCode.includes("runGameClosePress"), false);
  assert.equal(indexCode.includes("pressFromDialog"), false);
  assert.equal(indexCode.includes("continueSleepOnMount"), false);
});

test("game-close-ports is the only production route to the removal RPC", () => {
  assert.ok(
    /executeEgpuDisconnect\s*\(/.test(code(portsSource)),
    "game-close-ports.ts no longer calls executeEgpuDisconnect, so the wiring " +
      "has no route to the removal it is supposed to gate.",
  );
});

/** The active whole-dock gates have to be in the artifact, not only in source.
 *
 * The legacy game-close wiring is deliberately absent now that the production
 * Safe Disconnect tile mounts WholeDockControl directly. Audit the refusal and
 * uncertainty states owned by that shipped route so tree-shaking the real
 * guards still fails this test.
 */
const SHIPPED_GATES = [
  "Disconnect status unavailable. Refresh before continuing.",
  "Close your game and wait for an idle reading before disconnecting.",
  "Status changed. Review the current reading.",
  "Waiting to verify the previous request. Keep the cable connected.",
  "The reply was interrupted. Waiting for backend progress; no retry was sent.",
  "This is not permission to unplug.",
];

test("the shipped bundle still carries the active whole-dock gates", () => {
  const bundle = readFileSync(new URL("../dist/index.js", import.meta.url), "utf8");
  for (const gate of SHIPPED_GATES) {
    assert.ok(
      bundle.includes(gate),
      `The built bundle does not contain ${gate}. A gate that is not in the ` +
        "artifact does not protect the device it ships to.",
    );
  }
});
