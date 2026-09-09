import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const adapter = readFileSync(new URL("../src/quick-access/approved-icons.tsx", import.meta.url), "utf8");
for (const name of ["module-auto-tdp", "module-egpu", "module-controller", "mode-tv-docked"]) {
  test(`${name} preserves the approved SVG geometry`, () => {
    const svg = readFileSync(new URL(`../docs/design/command-center/assets/v1/${name}.svg`, import.meta.url), "utf8");
    const geometry = svg.split("</desc>")[1].split("</svg>")[0].trim()
      .replaceAll("stroke-width", "strokeWidth").replaceAll("stroke-linecap", "strokeLinecap").replaceAll("stroke-linejoin", "strokeLinejoin");
    assert.ok(adapter.replaceAll("\r\n", "\n").includes(geometry.replaceAll("\r\n", "\n")));
    assert.ok(adapter.includes(`viewBox="${svg.match(/viewBox="([^"]+)"/)[1]}"`));
  });
}
test("the production panel remains strict UTF-8", () => {
  new TextDecoder("utf-8", { fatal: true }).decode(readFileSync(new URL("../src/index.tsx", import.meta.url)));
});
