import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const styles = readFileSync(new URL("../src/quick-access/expanded-command-center/styles.ts", import.meta.url), "utf8");
const utility = readFileSync(new URL("../src/quick-access/expanded-command-center/utility-rail.tsx", import.meta.url), "utf8");
const shell = readFileSync(new URL("../src/quick-access/expanded-command-center/shell.tsx", import.meta.url), "utf8");
const nav = readFileSync(new URL("../src/quick-access/expanded-command-center/navigation-contract.ts", import.meta.url), "utf8");
const egpu = readFileSync(new URL("../src/quick-access/expanded-command-center/egpu-actions-ui.tsx", import.meta.url), "utf8");

test("left utility rail stays icon-first and compact", () => {
  assert.match(styles, /width:clamp\(52px,5\.8vw,62px\)/);
  assert.match(styles, /\.rg-utility-rail\[data-utility-side=left\] \.rg-utility-label\{display:none/);
  assert.match(utility, /data-ec-control={`utility-\$\{id\}`}/);
});

test("all menu cards share one fixed-height rhythm", () => {
  assert.match(styles, /height:88px;min-height:88px;max-height:88px/);
  assert.match(styles, /\.rg-expanded-settings-list \.rg-expanded-tile\{height:88px!important;min-height:88px!important;max-height:88px!important\}/);
  assert.doesNotMatch(egpu, /span 2/);
});

test("top-level menu helper/status strips stay removed", () => {
  assert.match(styles, /\.rg-expanded-info\{display:none!important\}/);
  assert.match(styles, /data-ec-tab=settings/);
});

test("safe disconnect remains one-press and normal-view copy stays terse", () => {
  assert.match(nav, /safeDisconnectPress: "start-workflow"/);
  assert.match(nav, /safeDisconnectConfirm: "none"/);
  assert.match(egpu, /Single-press action/);
  assert.match(egpu, /action\.id === "safe-disconnect" \? undefined/);
});

test("shell retains shared navigation entry points for utilities", () => {
  assert.match(shell, /\[data-ec-control\]/);
  assert.match(utility, /aria-orientation="vertical"/);
});
