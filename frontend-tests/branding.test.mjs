import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { PRODUCT_NAME } from "../src/branding.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("Re-Gear is the Decky list, panel, and dialog brand", () => {
  assert.equal(PRODUCT_NAME, "Re-Gear");
  const source = read("../src/index.tsx");
  assert.match(source, /titleView:.*<BrandHeader \/>/);
  assert.match(source, /alt=\{PRODUCT_NAME\}/);
  assert.match(source, /strTitle: PRODUCT_NAME/);
  assert.match(source, /name: PRODUCT_NAME/);
  assert.equal(JSON.parse(read("../plugin.json")).name, "Re-Gear");
  assert.match(source, /hdm\.hideAttachedEgpuSleepWarning/);
  assert.match(source, /hdm\.hideAttachedG1SleepWarning/);
});

test("approved preview uses Re-Gear and keeps sample-data disclosure", () => {
  const preview = read("../output/hdm-neon-dashboard.html");
  assert.match(preview, />Re-Gear<\/div>/);
  assert.match(preview, /SAMPLE DATA/);
  assert.doesNotMatch(preview, /Handheld Dock Mode|\bHDM\b/);
});

test("UI uses the approved compact Re-Gear assets while README keeps its artwork", () => {
  const source = read("../src/index.tsx");
  assert.ok(source.includes('import brandHeaderLogo from "./assets/regear-header-logo.svg"'));
  assert.ok(source.includes('import brandIcon from "./assets/regear-icon.svg"'));
  assert.match(source, /icon: <BrandIcon \/>/);
  assert.match(source, /<BrandHeader \/>/);
  assert.match(read("../README.md"), /src="docs\/images\/re-gear-icon\.png"/);
  const image = readFileSync(new URL("../docs/images/re-gear-icon.png", import.meta.url));
  assert.deepEqual([...image.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
});

test("committed bundle embeds compact transparent SVG artwork without unpackaged asset URLs", () => {
  const bundle = read("../dist/index.js");
  for (const name of ["regear-header-logo", "regear-icon", "mode-handheld", "mode-tv"]) {
    const image = readFileSync(new URL(`../src/assets/${name}.svg`, import.meta.url));
    assert.ok(bundle.includes("data:image/svg+xml;base64," + image.toString("base64")), `${name} must be embedded`);
  }
  assert.doesNotMatch(bundle, /\/assets\/(?:regear|mode)-/);
});
