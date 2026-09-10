/** Pin the former-name strings on the frontend that a rename must not touch.
 *
 * The Python companion to this file is `tests/test_retained_legacy_identity.py`,
 * which pins the device paths and protocol markers. This one covers the browser
 * side, where the same hazard has a different shape: a localStorage key is not
 * a name, it is an address in storage that already has a value at it.
 *
 * `branding.test.mjs` already asserts these two literals appear in the source.
 * That pin is real, but it lives in a test about branding, and a rename sweep
 * reading it has an easy answer ready: the product is not called HDM any more,
 * so surely the branding test is what needs updating. This file exists to make
 * the reason unmissable, next to the assertion rather than inferable from it.
 *
 * These are not the product's name. They are where a player's answer is kept.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

/** The two keys, and what each one is holding on a device right now. */
const STORAGE_KEYS = [
  {
    key: "hdm.hideAttachedEgpuSleepWarning",
    holds:
      "the current dismissal of the attached-eGPU sleep warning. Renaming it " +
      "reads an empty slot, so the warning returns for every player who " +
      "already told it to go away.",
  },
  {
    key: "hdm.hideAttachedG1SleepWarning",
    holds:
      "the same dismissal under its previous key. It is read but never " +
      "written, which is what makes it a migration: it exists so an answer " +
      "given before the first rename still counts. Dropping it silently " +
      "discards those.",
  },
];

test("the sleep-warning storage keys keep the names already written to devices", () => {
  const source = read("../src/index.tsx");

  for (const { key, holds } of STORAGE_KEYS) {
    // Escaped for the regex; the literal is what must survive.
    const pattern = new RegExp(key.replace(/\./g, "\\."));
    assert.match(source, pattern, `${key} holds ${holds}`);
  }
});

test("the legacy key is still read, not merely mentioned", () => {
  // A constant that no longer reaches getItem is a pin around dead code: the
  // literal survives a rename sweep while the migration it names is gone.
  const source = read("../src/index.tsx");

  assert.match(source, /getItem\(LEGACY_SLEEP_WARNING_KEY\)/);
  assert.match(source, /LEGACY_SLEEP_WARNING_KEY = "hdm\.hideAttachedG1SleepWarning"/);
});

test("the current key is the one written, and the legacy key is never written", () => {
  // If the legacy key were written too, the migration would never end.
  const source = read("../src/index.tsx");

  assert.match(source, /setItem\(SLEEP_WARNING_KEY, "1"\)/);
  assert.doesNotMatch(source, /setItem\(LEGACY_SLEEP_WARNING_KEY/);
});
