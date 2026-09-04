import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { PRODUCT_NAME } from "../src/branding.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("Re-Gear is the panel and dialog brand without changing Decky identity", () => {
  assert.equal(PRODUCT_NAME, "Re-Gear");
  const source = read("../src/index.tsx");
  assert.match(source, /titleView:.*\{PRODUCT_NAME\}/);
  assert.match(source, /strTitle: PRODUCT_NAME/);
  assert.match(source, /name: "Handheld Dock Mode"/);
  assert.equal(JSON.parse(read("../plugin.json")).name, "Handheld Dock Mode");
  assert.match(source, /hdm\.hideAttachedEgpuSleepWarning/);
  assert.match(source, /hdm\.hideAttachedG1SleepWarning/);
});

test("approved preview uses Re-Gear and keeps sample-data disclosure", () => {
  const preview = read("../output/hdm-neon-dashboard.html");
  assert.match(preview, />Re-Gear<\/div>/);
  assert.match(preview, /SAMPLE DATA/);
  assert.doesNotMatch(preview, /Handheld Dock Mode|\bHDM\b/);
});

test("UI and README use the supplied local Re-Gear artwork", () => {
  const source = read("../src/index.tsx");
  assert.ok(source.includes('import brandIcon from "../docs/images/re-gear-decky-monochrome.jpg"'));
  assert.match(source, /icon: <BrandIcon \/>/);
  assert.match(source, /<BrandIcon size=\{36\} \/>/);
  assert.match(read("../README.md"), /src="docs\/images\/re-gear-icon\.png"/);
  const image = readFileSync(new URL("../docs/images/re-gear-icon.png", import.meta.url));
  assert.deepEqual([...image.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
});

test("committed bundle embeds the artwork without an unpackaged asset URL", () => {
  const bundle = read("../dist/index.js");
  const image = readFileSync(new URL("../docs/images/re-gear-decky-monochrome.jpg", import.meta.url));
  assert.deepEqual([...image.subarray(0, 3)], [255, 216, 255]);
  assert.ok(bundle.includes("data:image/jpeg;base64," + image.toString("base64")));
  assert.doesNotMatch(bundle, /\/assets\/re-gear-(?:decky-)?icon/);
});
