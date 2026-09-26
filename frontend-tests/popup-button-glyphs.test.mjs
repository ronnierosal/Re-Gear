import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const frame = readFileSync(new URL("../src/popup-frame.tsx", import.meta.url), "utf8");
const commandCenter = readFileSync(new URL("../src/quick-access/expanded-command-center/styles.ts", import.meta.url), "utf8");

test("popup A/B/X/Y glyphs are centred, fixed-size discs matching the Command Center glyph", () => {
  const rule = /\.rg-key\{([^}]*)\}/.exec(frame)?.[1] ?? "";
  for (const part of ["display:inline-grid", "place-items:center", "flex:0 0 auto", "box-sizing:border-box",
    "width:22px", "height:22px", "border-radius:50%", "font:700 11px/1 Arial,sans-serif"]) {
    assert.ok(rule.includes(part), `.rg-key keeps ${part}`);
  }
  // Same palette as the Command Center's round controller glyph.
  for (const token of ["#6099b8", "linear-gradient(#20455b,#0a2538)", "#72e5ff"]) {
    assert.ok(rule.includes(token), `.rg-key uses ${token}`);
    assert.ok(commandCenter.includes(token), `Command Center glyph still uses ${token}`);
  }
  assert.match(frame, /\.rg-popup-footer button:has\(>\.rg-key\)\{display:inline-flex!important;align-items:center;white-space:nowrap\}/);
  assert.match(frame, /\.rg-popup-footer button:focus-visible \.rg-key,\.rg-popup-footer button\.gpfocus \.rg-key\{/);
});
