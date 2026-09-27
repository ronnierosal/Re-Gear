import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const read = (f) => readFileSync(new URL(`../src/${f}`, import.meta.url), "utf8");

test("connection popup is the slim half-width variant", () => {
  const overlay = read("connection-progress-overlay.tsx");
  assert.match(overlay, /compact slim headerMeta/);
  assert.match(read("popup-frame.tsx"), /slim \? " rg-slim" : ""/);
  assert.match(read("connection-panel-style.ts"), /\.rg-popup\.rg-compact\.rg-slim\{width:min\(280px,92vw\)/);
});

test("main view is one bar and one line; step list and path move into Details", () => {
  const overlay = read("connection-progress-overlay.tsx");
  const main = overlay.slice(overlay.indexOf('className="rg-milestones"'), overlay.indexOf("<details"));
  assert.match(main, /rg-milestone-bar/);
  assert.match(main, /rg-milestone-current/);
  assert.doesNotMatch(main, /rg-milestone-list|rg-connection-flow/);
  const details = overlay.slice(overlay.indexOf("<details"));
  assert.match(details, /rg-milestone-list/);
  assert.match(details, /rg-connection-flow/);
  assert.match(details, /keepConnectedMessage/);
});

test("hand-off warns the screen will go dark only while a fresh switch is in progress", () => {
  const overlay = read("connection-progress-overlay.tsx");
  assert.match(overlay, /const handoff=!m\.stale && !m\.attention && !done && props\.phase === "switching"/);
  assert.match(overlay, /Screen will go dark — look at the TV/);
});

test("slim popup keeps one visible Details entry and 44px footer hit areas", () => {
  const css = read("connection-panel-style.ts");
  assert.match(css, /\.rg-popup\.rg-slim \.rg-popup-footer button\{[^}]*min-height:44px!important/);
  assert.match(css, /\.rg-slim \.rg-connection-details>summary\{position:absolute;width:1px;height:1px[^}]*clip:rect\(0 0 0 0\)/);
  const preview = readFileSync(new URL("../scripts/popup_system_preview.mjs", import.meta.url), "utf8");
  assert.match(preview, /import \{connectionPanelCss\} from '\.\.\/\.\.\/src\/connection-panel-style'/);
  assert.match(preview, /Math\.min\(280,viewport\.width\*\.92\)/);
  assert.match(preview, /Footer hit area under 44px/);
});

// Behavioral: render the real overlay with a deterministic React stand-in.
import ts from "typescript";
const compile = (name) => ts.transpileModule(read(name), {compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.ES2022}}).outputText.replace(/^import .*;$/gm, "");
const jsx = "const React={createElement:(type,props,...children)=>({type,props:{...props,children}}),Fragment:'fragment'};";
const detailsRef = {current:{open:false}};
globalThis.__slimRef = detailsRef;
const {ConnectionProgressOverlay: render} = await import("data:text/javascript;base64," + Buffer.from(jsx + "const useRef=()=>globalThis.__slimRef,DialogButton='button',PopupFrame='frame',PopupStateIcon='status',CommandCenterIcon='icon',handheldIcon='h',tvIcon='t';" + compile("connection-progress-overlay.tsx")).toString("base64"));
const flatten = (v) => Array.isArray(v) ? v.flatMap(flatten) : v && typeof v === "object" ? [v, ...flatten(v.props?.children), ...flatten(v.props?.footer)] : [];
const text = (n) => JSON.stringify(n);
const steps = (states) => ["Detect eGPU","Load GPU driver","Verify connection","Find TV","Prepare and switch display"].map((label, i) => ({label, state: states[i]}));
const ms = (o) => ({activeStep:4, observedDone:4, progressText:"Step 5 of 5", steps: steps(["done","done","done","done","active"]), headline:"Switching to TV", currentDetail:"Switching to TV", complete:false, stale:false, attention:false, ...o});
const base = {rows:[], deviceLabel:"eGPU", onHide(){}, keepConnectedMessage:"Keep eGPU connected · Hide keeps docking active."};
const mainOf = (tree) => flatten(tree).find((n) => n.props?.className === "rg-milestones");
const detailsOf = (tree) => flatten(tree).find((n) => n.type === "details");
const button = (tree, label) => flatten(tree.props.footer).find((n) => n.type === "button" && text(n).includes(label));

test("renders slim: bar and one line in the main view; list, path and guidance only in Details", () => {
  const tree = render({...base, phase:"switching", milestones: ms()});
  assert.equal(tree.type, "frame"); assert.equal(tree.props.slim, true); assert.equal(tree.props.compact, true);
  const main = mainOf(tree), details = detailsOf(tree);
  assert.ok(flatten(main).some((n) => n.props?.className === "rg-milestone-bar"));
  assert.ok(!flatten(main).some((n) => ["rg-milestone-list","rg-connection-flow"].includes(n.props?.className)));
  assert.ok(flatten(details).some((n) => n.props?.className === "rg-milestone-list"));
  assert.ok(flatten(details).some((n) => n.props?.className === "rg-connection-flow"));
  assert.match(text(details), /Keep eGPU connected/);
  assert.doesNotMatch(text(main), /Keep eGPU connected/);
});

test("Y toggles Details open and closed; B only hides", () => {
  let hidden = 0; detailsRef.current = {open:false};
  const tree = render({...base, onHide(){hidden++;}, phase:"connecting", milestones: ms({activeStep:1, observedDone:1, headline:"Connecting eGPU", currentDetail:"Loading GPU driver", steps: steps(["done","active","pending","pending","pending"])})});
  button(tree, "Details").props.onClick(); assert.equal(detailsRef.current.open, true);
  button(tree, "Details").props.onClick(); assert.equal(detailsRef.current.open, false);
  button(tree, "Hide").props.onClick(); assert.equal(hidden, 1); assert.equal(detailsRef.current.open, false);
  assert.equal(button(tree, "Switch to TV"), undefined);
  const manual = render({...base, phase:"connecting", onSwitch(){}, milestones: ms()});
  assert.ok(button(manual, "Switch to TV"), "optional Switch to TV stays in the footer");
});

test("hand-off warning only for a fresh, unblocked, incomplete switch", () => {
  const has = (p) => /Screen will go dark/.test(text(mainOf(render({...base, ...p}))));
  assert.equal(has({phase:"switching", milestones: ms()}), true);
  assert.equal(has({phase:"switching", milestones: ms({stale:true})}), false);
  assert.equal(has({phase:"switching", milestones: ms({attention:true})}), false);
  assert.equal(has({phase:"connecting", milestones: ms({activeStep:1})}), false);
  assert.equal(has({phase:"ready", milestones: ms({complete:true, activeStep:5, observedDone:5})}), false);
});

test("stale evidence reads Not live and never claims current progress", () => {
  const tree = render({...base, phase:"connecting", milestones: ms({stale:true, headline:"Waiting for a fresh update", currentDetail:"Last observed: Load GPU driver", steps: steps(["stale","stale","pending","pending","pending"]), activeStep:-1, observedDone:1})});
  const live = flatten(tree.props.footer).find((n) => n.props?.className === "rg-popup-guidance");
  assert.equal(live.props["data-live"], false); assert.match(text(live), /Not live/);
  assert.equal(mainOf(tree).props["data-stale"], true);
  assert.ok(!flatten(mainOf(tree)).some((n) => n.props?.["data-state"] === "active"));
});
