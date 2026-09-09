import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

/** Audit the shipped bundle, not the sources.
 *
 * The sources are checked thoroughly elsewhere. This checks the artifact that
 * actually reaches a device, because that is what a person greps when they
 * want to know whether a build tells players the cable is safe -- and the
 * answer has to be trustworthy.
 *
 * It caught a real near-miss: a docstring quoting the old wording verbatim to
 * explain why it was removed. Harmless on screen, since a comment cannot
 * render, and quietly poisonous to every audit of a built archive.
 */

const bundle = readFileSync(new URL("../dist/index.js", import.meta.url), "utf8");

/** Anchored on the cable, not on the word "disconnect".
 *
 * In this product's vocabulary "disconnect" is the *software* operation: it is
 * what the button does, what `execute_egpu_disconnect` does, and what the
 * "Safe to disconnect:" readiness field reports. An audit that flagged the bare
 * word would fire on every legitimate label and be turned off within a day.
 *
 * What must never appear is a claim about the physical cable. Each pattern
 * below requires the cable to be named, or a verb that only means the cable.
 */
const GRANTS_UNPLUG = [
  /unplug\w*\s+(is|are)\s+safe/i,
  /safe\s+to\s+unplug/i,
  /you\s+(can|may)\s+(now\s+)?unplug/i,
  /ok(ay)?\s+to\s+unplug/i,
  /ready\s+to\s+unplug/i,
  /remove\s+the\s+cable/i,
  /(unplug|disconnect|remove)[^.!?]{0,40}cable[^.!?]{0,20}(now|safely)/i,
  /you\s+(can|may)\s+(now\s+)?(unplug|disconnect|remove)[^.!?]{0,40}cable/i,
];

test("the shipped bundle contains no wording that grants an unplug", () => {
  for (const pattern of GRANTS_UNPLUG) {
    const match = bundle.match(pattern);
    assert.equal(
      match,
      null,
      match ? `bundle contains ${pattern}: ...${bundle.slice(Math.max(0, match.index - 90), match.index + 60)}...` : "",
    );
  }
});

test("the bundle still carries the wording that replaced it", () => {
  // A bundle with neither string is a bundle where the block vanished, which
  // would pass the audit above for the wrong reason.
  assert.match(bundle, /not yet clearance to unplug the cable/);
  assert.match(bundle, /shut the handheld down first/i);
});
