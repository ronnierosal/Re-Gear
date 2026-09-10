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

test("the disconnect press and the pending reopen both go through the wiring", () => {
  for (const symbol of ["runGameClosePress", "pressFromDialog", "claimRelaunchOnMount"]) {
    assert.ok(
      indexCode.includes(symbol),
      `src/index.tsx no longer uses ${symbol}. The press path or the mount ` +
        "reopen has been detached from the owning flow.",
    );
  }
});

test("game-close-ports is the only production route to the removal RPC", () => {
  assert.ok(
    /executeEgpuDisconnect\s*\(/.test(code(portsSource)),
    "game-close-ports.ts no longer calls executeEgpuDisconnect, so the wiring " +
      "has no route to the removal it is supposed to gate.",
  );
});

/** The gates have to be in the artifact, not only in the repository.
 *
 * Every refusal below is a decision that stops a press before it reaches the
 * device. If a build drops them -- tree-shaken, mis-bundled, an import removed
 * in a refactor -- the panel still compiles and still presses, and the gate is
 * simply gone. Reading them out of the built bundle is the only check that
 * notices.
 */
const SHIPPED_GATES = [
  "wiring.cancelled",
  "wiring.status_unavailable",
  "wiring.consent_required",
  "wiring.game_changed",
  "wiring.display_approval_required",
  "wiring.needs_attention",
];

test("the shipped bundle still carries the press gates", () => {
  const bundle = readFileSync(new URL("../dist/index.js", import.meta.url), "utf8");
  for (const gate of SHIPPED_GATES) {
    assert.ok(
      bundle.includes(gate),
      `The built bundle does not contain ${gate}. A gate that is not in the ` +
        "artifact does not protect the device it ships to.",
    );
  }
});
