import assert from "node:assert/strict";
import test from "node:test";
import {
  DISABLED,
  MAX_INTERVAL_MINUTES,
  MIN_INTERVAL_MINUTES,
  createSyncPreferences,
  isUsableInterval,
  sanitizeSyncPreferences,
} from "../src/offline-sync-preferences.ts";

function store(initial) {
  const state = { value: initial, writes: [], failRead: false, failWrite: false };
  return {
    state,
    port: {
      read: () => { if (state.failRead) throw new Error("unreadable"); return state.value; },
      write: (v) => {
        if (state.failWrite) throw new Error("read-only");
        state.writes.push(v); state.value = v;
      },
    },
  };
}

test("anything not explicitly enabled and in range reads back as disabled", () => {
  for (const bad of [
    undefined, null, 0, "", "enabled", [], [{ enabled: true }],
    {}, { enabled: false }, { enabled: "true", intervalMinutes: 60 },
    { enabled: true }, { enabled: true, intervalMinutes: null },
    { enabled: true, intervalMinutes: 0 }, { enabled: true, intervalMinutes: -60 },
    { enabled: true, intervalMinutes: MIN_INTERVAL_MINUTES - 1 },
    { enabled: true, intervalMinutes: MAX_INTERVAL_MINUTES + 1 },
    { enabled: true, intervalMinutes: 60.5 }, { enabled: true, intervalMinutes: "60" },
    { enabled: true, intervalMinutes: NaN }, { enabled: true, intervalMinutes: Infinity },
  ]) {
    assert.deepEqual(sanitizeSyncPreferences(bad), DISABLED,
      `${JSON.stringify(bad)} must not enable a schedule`);
  }
});

test("an explicitly enabled in-range preference survives", () => {
  for (const good of [MIN_INTERVAL_MINUTES, 60, 1440, MAX_INTERVAL_MINUTES]) {
    assert.deepEqual(sanitizeSyncPreferences({ enabled: true, intervalMinutes: good }),
      { enabled: true, intervalMinutes: good });
  }
});

test("unreadable storage is not consent to run on a schedule", () => {
  const s = store({ enabled: true, intervalMinutes: 60 });
  s.state.failRead = true;
  assert.deepEqual(createSyncPreferences(s.port).get(), DISABLED);
});

test("a stored preference is loaded, and get returns a copy", () => {
  const s = store({ enabled: true, intervalMinutes: 120 });
  const prefs = createSyncPreferences(s.port);
  const a = prefs.get();
  assert.deepEqual(a, { enabled: true, intervalMinutes: 120 });
  a.enabled = false;
  assert.equal(prefs.get().enabled, true, "a caller cannot mutate the stored value");
});

test("set persists and returns true only for a usable value", () => {
  const s = store(undefined);
  const prefs = createSyncPreferences(s.port);
  assert.equal(prefs.set({ enabled: true, intervalMinutes: 60 }), true);
  assert.deepEqual(prefs.get(), { enabled: true, intervalMinutes: 60 });
  assert.deepEqual(s.state.writes.at(-1), { enabled: true, intervalMinutes: 60 });
});

test("set refuses an unusable value and changes nothing", () => {
  const s = store({ enabled: true, intervalMinutes: 60 });
  const prefs = createSyncPreferences(s.port);
  for (const bad of [null, undefined, {}, { enabled: "yes" },
    { enabled: true, intervalMinutes: 1 }, { enabled: true, intervalMinutes: null }]) {
    assert.equal(prefs.set(bad), false);
  }
  assert.deepEqual(prefs.get(), { enabled: true, intervalMinutes: 60 });
  assert.equal(s.state.writes.length, 0, "nothing unusable is ever written");
});

test("disabling clears the interval and is always usable", () => {
  const s = store({ enabled: true, intervalMinutes: 60 });
  const prefs = createSyncPreferences(s.port);
  assert.equal(prefs.set({ enabled: false, intervalMinutes: 60 }), true);
  assert.deepEqual(prefs.get(), DISABLED);
  assert.deepEqual(s.state.writes.at(-1), DISABLED);
});

test("a store that refuses the write leaves the in-memory value untouched", () => {
  const s = store({ enabled: false, intervalMinutes: null });
  const prefs = createSyncPreferences(s.port);
  s.state.failWrite = true;
  assert.equal(prefs.set({ enabled: true, intervalMinutes: 60 }), false);
  assert.deepEqual(prefs.get(), DISABLED,
    "a setting that did not stick must not be reported as set");
});

test("the interval guard is explicit about its bounds", () => {
  assert.equal(isUsableInterval(MIN_INTERVAL_MINUTES), true);
  assert.equal(isUsableInterval(MIN_INTERVAL_MINUTES - 1), false);
  assert.equal(isUsableInterval(MAX_INTERVAL_MINUTES), true);
  assert.equal(isUsableInterval(MAX_INTERVAL_MINUTES + 1), false);
  assert.equal(Object.isFrozen(DISABLED), true);
});
