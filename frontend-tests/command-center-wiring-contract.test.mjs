import assert from "node:assert/strict";
import test from "node:test";
import { existsSync, readFileSync } from "node:fs";
import ts from "typescript";

const modelUrl = new URL("../src/quick-access/expanded-command-center/model.ts", import.meta.url);
const modelJs = ts.transpileModule(readFileSync(modelUrl, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.ES2022 },
}).outputText;
const { sampleTiles } = await import(`data:text/javascript;base64,${Buffer.from(modelJs).toString("base64")}`);

const approved = Object.fromEntries(
  Object.entries(sampleTiles).map(([tab, tiles]) => [tab, tiles.map(tile => tile.id)]),
);

const tileSourceUrl = new URL("../src/quick-access/expanded-command-center/tile-source.ts", import.meta.url);

/**
 * Integration guard for the wiring workstream.
 *
 * The UI owns tab composition and stable tile IDs. A live source may change
 * values, tones and detail text, but it must not shrink/reorder the approved
 * menu or reintroduce an older composition. This test is intentionally dormant
 * on the UI-only branch and becomes active as soon as tile-source.ts is present
 * in an integration tree.
 */
test("live Command Center source preserves the approved UI tile contract", {
  skip: !existsSync(tileSourceUrl),
}, async () => {
  const source = readFileSync(tileSourceUrl, "utf8");

  // Keep this source-level on purpose: tile-source.ts imports runtime modules
  // that are outside this UI-only test's ownership. The assertions pin the
  // public contract without mocking backend behavior.
  const expectedIds = Object.values(approved).flat();
  for (const id of new Set(expectedIds)) {
    assert.match(source, new RegExp(`(?:id:\\s*["']${id}["']|\\[["']${id}["'])`),
      `live source must preserve approved tile id: ${id}`);
  }

  // Older wiring used these eGPU-only IDs/titles as the primary menu shape.
  // They may exist internally, but they cannot replace the approved module IDs.
  assert.match(source, /["']device["']/, "eGPU wiring must expose the External GPU card as device");
  assert.match(source, /["']dock["']/, "eGPU wiring must expose Dock Mode");
  assert.match(source, /["']link["']/, "eGPU wiring must expose Connection Link");
  assert.match(source, /["']profile["']/, "performance wiring must preserve Performance Profile");
  assert.match(source, /["']refresh["']/, "performance wiring must preserve Refresh Rate");
  assert.match(source, /["']battery["']/, "controller wiring must preserve Controller Battery");
  assert.match(source, /["']tv-controller["']/, "controller wiring must preserve TV Dock Behavior");
  assert.match(source, /["']quick-actions["']/, "settings wiring must preserve Quick Actions");
  assert.match(source, /["']updates["']/, "settings wiring must preserve Updates");
  assert.match(source, /["']about["']/, "settings wiring must preserve About Re-Gear");
});
