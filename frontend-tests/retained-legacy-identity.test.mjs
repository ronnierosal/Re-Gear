/** Bound former browser addresses to one-way preference migration only. */

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

test("former sleep-warning addresses exist only in the migration module", () => {
  const source = read("../src/identity-storage.ts");

  for (const { key, holds } of STORAGE_KEYS) {
    // Escaped for the regex; the literal is what must survive.
    const pattern = new RegExp(key.replace(/\./g, "\\."));
    assert.match(source, pattern, `${key} holds ${holds}`);
  }
});

test("former keys are read through one bounded migration list", () => {
  const source = read("../src/identity-storage.ts");

  assert.match(source, /FORMER_ATTACHED_EGPU_SLEEP_WARNING_KEYS\.map/);
  assert.match(source, /storage\.getItem\(key\)/);
});

test("only the Re-Gear key is written and former keys are removed after promotion", () => {
  const source = read("../src/identity-storage.ts");

  assert.match(source, /setItem\(ATTACHED_EGPU_SLEEP_WARNING_KEY, dismissed \? "1" : "0"\)/);
  assert.match(source, /setItem\(ATTACHED_EGPU_SLEEP_WARNING_KEY, "1"\)/);
  assert.match(source, /storage\.removeItem\(key\)/);
  assert.doesNotMatch(source, /setItem\([^\n]*FORMER_ATTACHED/);
});
