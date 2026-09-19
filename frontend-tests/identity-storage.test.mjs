import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

async function loadModule() {
  const source = readFileSync(
    new URL("../src/identity-storage.ts", import.meta.url),
    "utf8",
  );
  const js = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ES2022 },
  }).outputText;
  return import(
    "data:text/javascript;base64," + Buffer.from(js).toString("base64")
  );
}

function fakeStorage(initial = {}, failures = {}) {
  const values = new Map(Object.entries(initial));
  const operations = [];
  return {
    values,
    operations,
    getItem(key) {
      operations.push(["get", key]);
      if (failures.get?.has(key)) throw new Error(`get failed: ${key}`);
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      operations.push(["set", key, value]);
      if (failures.set?.has(key)) throw new Error(`set failed: ${key}`);
      values.set(key, value);
    },
    removeItem(key) {
      operations.push(["remove", key]);
      if (failures.remove?.has(key)) throw new Error(`remove failed: ${key}`);
      values.delete(key);
    },
  };
}

test("current preference is authoritative and legacy storage is not read", async () => {
  const module = await loadModule();
  for (const [value, expected] of [["1", true], ["0", false]]) {
    const storage = fakeStorage({
      [module.ATTACHED_EGPU_SLEEP_WARNING_KEY]: value,
      [module.FORMER_ATTACHED_EGPU_SLEEP_WARNING_KEYS[0]]: "1",
    });
    assert.equal(
      module.readAttachedEgpuSleepWarningDismissed(storage),
      expected,
    );
    assert.deepEqual(storage.operations, [
      ["get", module.ATTACHED_EGPU_SLEEP_WARNING_KEY],
    ]);
  }
});

test("a former dismissal is promoted before both former keys are removed", async () => {
  const module = await loadModule();
  const [firstFormer, secondFormer] =
    module.FORMER_ATTACHED_EGPU_SLEEP_WARNING_KEYS;
  const storage = fakeStorage({ [secondFormer]: "1" });

  assert.equal(module.readAttachedEgpuSleepWarningDismissed(storage), true);
  assert.equal(storage.values.get(module.ATTACHED_EGPU_SLEEP_WARNING_KEY), "1");
  assert.equal(storage.values.has(firstFormer), false);
  assert.equal(storage.values.has(secondFormer), false);
  assert.deepEqual(storage.operations, [
    ["get", module.ATTACHED_EGPU_SLEEP_WARNING_KEY],
    ["get", firstFormer],
    ["get", secondFormer],
    ["set", module.ATTACHED_EGPU_SLEEP_WARNING_KEY, "1"],
    ["remove", firstFormer],
    ["remove", secondFormer],
  ]);
});

test("a failed promotion keeps former values while honoring the dismissal", async () => {
  const module = await loadModule();
  const [firstFormer, secondFormer] =
    module.FORMER_ATTACHED_EGPU_SLEEP_WARNING_KEYS;
  const storage = fakeStorage(
    { [firstFormer]: "1", [secondFormer]: "0" },
    { set: new Set([module.ATTACHED_EGPU_SLEEP_WARNING_KEY]) },
  );

  assert.equal(module.readAttachedEgpuSleepWarningDismissed(storage), true);
  assert.equal(storage.values.get(firstFormer), "1");
  assert.equal(storage.values.get(secondFormer), "0");
  assert.equal(storage.operations.some(([operation]) => operation === "remove"), false);
});

test("former values without a dismissal migrate to current false and are removed", async () => {
  const module = await loadModule();
  const [firstFormer, secondFormer] =
    module.FORMER_ATTACHED_EGPU_SLEEP_WARNING_KEYS;
  const storage = fakeStorage({ [firstFormer]: "0", [secondFormer]: "" });

  assert.equal(module.readAttachedEgpuSleepWarningDismissed(storage), false);
  assert.equal(storage.values.get(module.ATTACHED_EGPU_SLEEP_WARNING_KEY), "0");
  assert.equal(storage.values.has(firstFormer), false);
  assert.equal(storage.values.has(secondFormer), false);
  assert.deepEqual(storage.operations.slice(-3), [
    ["set", module.ATTACHED_EGPU_SLEEP_WARNING_KEY, "0"],
    ["remove", firstFormer],
    ["remove", secondFormer],
  ]);
});

test("a former-key read failure performs no writes or removals", async () => {
  const module = await loadModule();
  const [firstFormer, secondFormer] =
    module.FORMER_ATTACHED_EGPU_SLEEP_WARNING_KEYS;
  const storage = fakeStorage(
    { [firstFormer]: "1", [secondFormer]: "1" },
    { get: new Set([secondFormer]) },
  );

  assert.equal(module.readAttachedEgpuSleepWarningDismissed(storage), false);
  assert.equal(storage.values.get(firstFormer), "1");
  assert.equal(storage.values.get(secondFormer), "1");
  assert.equal(
    storage.operations.some(([operation]) =>
      operation === "set" || operation === "remove"),
    false,
  );
});

test("cleanup failures do not undo the promoted current value", async () => {
  const module = await loadModule();
  const [firstFormer, secondFormer] =
    module.FORMER_ATTACHED_EGPU_SLEEP_WARNING_KEYS;
  const storage = fakeStorage(
    { [firstFormer]: "1", [secondFormer]: "1" },
    { remove: new Set([firstFormer]) },
  );

  assert.equal(module.readAttachedEgpuSleepWarningDismissed(storage), true);
  assert.equal(storage.values.get(module.ATTACHED_EGPU_SLEEP_WARNING_KEY), "1");
  assert.equal(storage.values.get(firstFormer), "1");
  assert.equal(storage.values.has(secondFormer), false);
  assert.deepEqual(
    storage.operations.filter(([operation]) => operation === "remove"),
    [["remove", firstFormer], ["remove", secondFormer]],
  );
});

test("explicit dismissal writes current before cleaning former keys", async () => {
  const module = await loadModule();
  const [firstFormer, secondFormer] =
    module.FORMER_ATTACHED_EGPU_SLEEP_WARNING_KEYS;
  const storage = fakeStorage({ [firstFormer]: "1", [secondFormer]: "1" });

  assert.equal(module.dismissAttachedEgpuSleepWarning(storage), true);
  assert.deepEqual(storage.operations, [
    ["set", module.ATTACHED_EGPU_SLEEP_WARNING_KEY, "1"],
    ["remove", firstFormer],
    ["remove", secondFormer],
  ]);
});

test("failed explicit dismissal does not clean former keys", async () => {
  const module = await loadModule();
  const [firstFormer, secondFormer] =
    module.FORMER_ATTACHED_EGPU_SLEEP_WARNING_KEYS;
  const storage = fakeStorage(
    { [firstFormer]: "1", [secondFormer]: "1" },
    { set: new Set([module.ATTACHED_EGPU_SLEEP_WARNING_KEY]) },
  );

  assert.equal(module.dismissAttachedEgpuSleepWarning(storage), false);
  assert.equal(storage.values.get(firstFormer), "1");
  assert.equal(storage.values.get(secondFormer), "1");
  assert.deepEqual(storage.operations, [
    ["set", module.ATTACHED_EGPU_SLEEP_WARNING_KEY, "1"],
  ]);
});

test("explicit reset attempts current and both former keys independently", async () => {
  const module = await loadModule();
  const [firstFormer, secondFormer] =
    module.FORMER_ATTACHED_EGPU_SLEEP_WARNING_KEYS;
  const storage = fakeStorage(
    {
      [module.ATTACHED_EGPU_SLEEP_WARNING_KEY]: "1",
      [firstFormer]: "1",
      [secondFormer]: "1",
    },
    { remove: new Set([firstFormer]) },
  );

  module.resetAttachedEgpuSleepWarning(storage);
  assert.equal(storage.values.has(module.ATTACHED_EGPU_SLEEP_WARNING_KEY), false);
  assert.equal(storage.values.get(firstFormer), "1");
  assert.equal(storage.values.has(secondFormer), false);
  assert.deepEqual(storage.operations, [
    ["remove", module.ATTACHED_EGPU_SLEEP_WARNING_KEY],
    ["remove", firstFormer],
    ["remove", secondFormer],
  ]);
});

test("missing or inaccessible storage fails closed", async () => {
  const module = await loadModule();
  assert.equal(module.readAttachedEgpuSleepWarningDismissed(undefined), false);
  assert.equal(module.dismissAttachedEgpuSleepWarning(undefined), false);
  assert.doesNotThrow(() => module.resetAttachedEgpuSleepWarning(undefined));

  const storage = fakeStorage({}, {
    get: new Set([module.ATTACHED_EGPU_SLEEP_WARNING_KEY]),
  });
  assert.equal(module.readAttachedEgpuSleepWarningDismissed(storage), false);
  assert.deepEqual(storage.operations, [
    ["get", module.ATTACHED_EGPU_SLEEP_WARNING_KEY],
  ]);
});
