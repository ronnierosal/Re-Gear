/** Local visual regression harness. Uses production TSX with a native-button host surrogate.
 * Usage: node scripts/check_dashboard_layout.mjs <playwright-package> <browser-executable>
 * This tests layout, not Steam's controller focus engine or hardware behavior.
 */
import assert from "node:assert/strict";
import { readFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import vm from "node:vm";
import ts from "typescript";

const require = createRequire(import.meta.url);
const { chromium } = require(process.argv[2]);
const jsx = (type, props) => ({ type, props });
const cache = new Map();
function load(name, extension) {
  if (cache.has(name)) return cache.get(name);
  const source = readFileSync(new URL(`../src/${name}.${extension}`, import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, require: (id) => {
    if (id === "react/jsx-runtime") return { jsx, jsxs: jsx };
    if (id === "@decky/ui") return { DialogButton: (props) => jsx("button", { ...props, className: "host-button" }) };
    if (id === "./quick-access-overview") return load("quick-access-overview", "tsx");
    if (id === "./quick-access-dashboard") return load("quick-access-dashboard", "ts");
    throw new Error(`Unexpected dependency: ${id}`);
  } });
  cache.set(name, exports);
  return exports;
}
const escape = (value) => String(value).replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const unitless = new Set(["fontWeight", "lineHeight", "flexShrink", "opacity", "flex"]);
function render(node) {
  if (node == null || typeof node === "boolean") return "";
  if (Array.isArray(node)) return node.map(render).join("");
  if (typeof node !== "object") return escape(node);
  if (typeof node.type === "function") return render(node.type(node.props));
  const { children, ...props } = node.props;
  const attrs = Object.entries(props).filter(([key, value]) => key !== "key" && value != null && !key.startsWith("on"))
    .map(([key, value]) => {
      if (key === "disabled") return value ? " disabled" : "";
      if (key === "style") value = Object.entries(value).filter(([, val]) => val !== undefined).map(([prop, val]) =>
        `${prop.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}:${typeof val === "number" && val !== 0 && !unitless.has(prop) ? `${val}px` : val}`).join(";");
      return ` ${key === "className" ? "class" : key}="${escape(value)}"`;
    }).join("");
  return `<${node.type}${attrs}>${render(children)}</${node.type}>`;
}
const { DashboardAction } = load("dashboard-action", "tsx");
const fixtures = [
  { title: "Dock / eGPU", description: "Ready to dock", icon: "connection", expanded: false },
  { title: "Switch to TV now", description: "Checks readiness before switching", icon: "bolt" },
  { title: "Shut down to disconnect", description: "Keep the eGPU connected until fully powered off.", icon: "power" },
  { title: "Troubleshoot", description: "Safety checks, details & support", icon: "tools", expanded: true },
  { title: "Switching…", description: "Checks readiness before switching", icon: "bolt", disabled: true },
];
const html = `<style>body{margin:0;background:#091321;color:#eef5ff;font:16px system-ui}main{padding:8px}.host-button{font:inherit;background:#223651;color:inherit;border:1px solid #496488;min-width:160px}.host-button:focus-visible{outline:3px solid #28caff;outline-offset:1px}.host-button:disabled{opacity:.5}section{margin-bottom:12px}</style><main>${fixtures.map((props) => `<section>${render(jsx(DashboardAction, props))}</section>`).join("")}</main>`;
const output = resolve("out/dashboard-layout");
mkdirSync(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.argv[3], headless: true });
try {
  for (const width of [240, 280, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 700 } });
    await page.setContent(html);
    const checks = await page.evaluate(() => [...document.querySelectorAll("button")].map((button) => {
      const grid = button.firstElementChild;
      const [icon, text, arrow] = grid.children;
      const b = button.getBoundingClientRect(), i = icon.getBoundingClientRect(), t = text.getBoundingClientRect(), a = arrow.getBoundingClientRect();
      return { fits: button.scrollWidth <= button.clientWidth && a.right <= b.right && i.left >= b.left,
        aligned: Math.abs((i.top + i.bottom) / 2 - (a.top + a.bottom) / 2) < 1,
        separated: i.right <= t.left && t.right <= a.left,
        wordBreak: getComputedStyle(text).wordBreak,
        overflow: document.documentElement.scrollWidth > innerWidth };
    }));
    assert.equal(checks.length, fixtures.length);
    for (const check of checks) assert.ok(check.fits && check.aligned && check.separated && !check.overflow && check.wordBreak === "normal", JSON.stringify({ width, check }));
    await page.keyboard.press("Tab");
    assert.equal(await page.locator("button").first().evaluate((el) => el === document.activeElement), true);
    assert.equal(await page.locator("button").last().isDisabled(), true);
    await page.screenshot({ path: resolve(output, `actions-${width}.png`), fullPage: true });
    await page.close();
  }
  console.log("PASS: production action TSX fits 240/280/320px, aligned icons, no horizontal overflow, native keyboard focus and disabled state in host surrogate.");
} finally { await browser.close(); }
