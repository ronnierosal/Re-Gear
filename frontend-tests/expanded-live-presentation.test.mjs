import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

// Execute the real TSX with a deterministic hook/element fixture. This checks
// rendered copy and update behavior; it does not simulate native Decky focus.
let fixtureId = 0;
async function fixture() {
  const compile = path => ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.React },
  }).outputText.replace(/^import .*;$/gm, "");
  const code = `
    const React = {createElement(type, props, ...children) { return {type, props: {...props, children}}; }};
    const states = []; let cursor = 0;
    const useState = initial => { const i=cursor++; if (!(i in states)) states[i]=initial;
      return [states[i], value => {states[i]=value}]; };
    const useRef = initial => useState({current: initial})[0];
    let effects=[];
    const useLayoutEffect = effect => effects.push(effect);
    const CommandCenterIcon='icon', expandedStyles='', brandIcon='';
    ${compile("../src/quick-access/expanded-command-center/model.ts")}
    ${compile("../src/quick-access/expanded-command-center/shell.tsx")}
    export function render(props) {cursor=0;effects=[];return ExpandedCommandCenter({onClose(){}, ...props});}
    export function restoreFocus() {effects.at(-1)();}
  `;
  return import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}#${++fixtureId}`);
}
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
function text(tree) {
  if (tree == null || typeof tree === "boolean") return "";
  if (Array.isArray(tree)) return tree.map(text).join(" ");
  return typeof tree === "object" ? text(tree.props?.children) : String(tree);
}
const auto = (value, detail) => ({id:"auto",title:"Auto TDP",value,detail});

test("supplied observations never render fabricated summary identity or demo claims", async () => {
  const app = await fixture();
  const tree = app.render({tiles:{quick:[auto("Running", "Controller running")]}});
  assert.match(text(tree), /Application status/);
  assert.doesNotMatch(text(tree), /RX 7600M XT|eGPU connected|Sample data|P1/);
});

test("nested Auto TDP follows changed and missing readings without stale Off copy", async () => {
  const app = await fixture();
  const props = {tiles:{quick:[auto("Running", "Controller running")]}};
  let tree = app.render(props);
  nodes(tree).find(node => node.props?.["data-ec-control"] === "auto").props.onClick();
  tree = app.render(props);
  assert.match(text(tree), /Controller running/);
  assert.doesNotMatch(text(tree), /off and not configured|Sample data/);
  tree = app.render({tiles:{quick:[auto("Stopping…", "Stop pending")]}});
  assert.match(text(tree), /Stopping….*Stop pending/);
  assert.doesNotMatch(text(tree), /Controller running/);
  tree = app.render({tiles:{quick:[]}});
  assert.match(text(tree), /Status unavailable.*Unknown/);
  assert.doesNotMatch(text(tree), /Stopping|Controller running/);
  assert.ok(nodes(tree).find(node => node.props?.["data-ec-control"] === "nested-back"));
});

test("empty supplied tabs remain unavailable instead of falling back to sample values", async () => {
  const app = await fixture();
  const tree = app.render({tiles:{quick:[]}});
  assert.doesNotMatch(text(tree), /18 W|Connected|RX 7600M XT|Sample data/);
});

test("Back from a removed reading focuses the active tab when no controls remain", async () => {
  const app = await fixture();
  let tree=app.render({tiles:{quick:[auto("Running", "Controller running")]}});
  nodes(tree).find(node=>node.props?.["data-ec-control"] === "auto").props.onClick();
  tree=app.render({tiles:{quick:[]}});
  nodes(tree).find(node=>node.props?.["data-ec-control"] === "nested-back").props.onClick();
  tree=app.render({tiles:{quick:[]}});
  let focused;
  nodes(tree).find(node=>node.props && "data-ec-panel" in node.props).props.ref.current={
    querySelectorAll:()=>[],
    querySelector:selector=>({focus(){focused=selector;}}),
  };
  app.restoreFocus();
  assert.equal(focused, '[data-ec-tab="quick"]');
});

test("unconnected preview tabs retain explicit sample labeling", async () => {
  const app = await fixture();
  assert.match(text(app.render({})), /Demo · Sample data/);
});

test("supplied disconnect readiness retains no clearance without claiming its source is disconnected", async () => {
  const app = await fixture();
  const props={tiles:{quick:[{id:"disconnect",title:"Safe Disconnect",value:"Blocked",detail:"Game is running"}]}};
  let tree=app.render(props);
  nodes(tree).find(node=>node.props?.["data-ec-control"] === "disconnect").props.onClick();
  tree=app.render(props);
  assert.match(text(tree), /Game is running/);
  assert.match(text(tree), /No unplug clearance/);
  assert.doesNotMatch(text(tree), /readiness and confirmation are not connected/);
});

test("application detail controls receive updated tiles and preserve pending and error results", async () => {
  const app=await fixture();
  let calls=0;
  const props={tiles:{quick:[auto("Ready", "Configure")]},renderDetail:(tab,tile)=>{
    assert.equal(tab,"quick");
    return {type:"button",props:{disabled:tile.value === "Pending",onClick(){calls++;},children:[`Action: ${tile.value}`]}};
  }};
  let tree=app.render(props);
  assert.equal(calls,0);
  nodes(tree).find(node=>node.props?.["data-ec-control"] === "auto").props.onClick();
  tree=app.render(props);
  assert.match(text(tree),/Status and controls.*Settings and actions.*Action: Ready/);
  assert.doesNotMatch(text(tree),/No operation is available from this view/);
  nodes(tree).find(node=>node.props?.children?.[0] === "Action: Ready").props.onClick();
  assert.equal(calls,1);
  tree=app.render({...props,tiles:{quick:[auto("Pending", "Waiting")]}});
  assert.equal(nodes(tree).find(node=>node.props?.children?.[0] === "Action: Pending").props.disabled,true);
  tree=app.render({...props,tiles:{quick:[auto("Failed", "Try again")]}});
  assert.match(text(tree),/Action: Failed/);
  nodes(tree).find(node=>node.props?.["data-ec-control"] === "nested-back").props.onClick();
  app.render(props);
  assert.equal(calls,1,"rendering, updates and Back never dispatch an action");
});

test("sample and removed tiles never invoke application control content", async () => {
  const app=await fixture();
  let calls=0;
  const renderDetail=()=>{calls++;return "Control";};
  let tree=app.render({renderDetail});
  nodes(tree).find(node=>node.props?.["data-ec-control"] === "auto").props.onClick();
  app.render({renderDetail});
  assert.equal(calls,0);
  tree=app.render({renderDetail,tiles:{quick:[]}});
  assert.equal(calls,0);
  assert.doesNotMatch(text(tree),/Settings and actions/);
});

test("null detail content keeps unavailable reason readable", async () => {
  const app=await fixture();
  const props={tiles:{quick:[auto("Unknown", "Provider unavailable")]},renderDetail:()=>null};
  let tree=app.render(props);
  nodes(tree).find(node=>node.props?.["data-ec-control"] === "auto").props.onClick();
  tree=app.render(props);
  assert.match(text(tree),/Provider unavailable.*No operation is available/);
});

test("embedded editing keys are left to the input instead of switching tabs", async () => {
  const app=await fixture();
  const tree=app.render({});
  const panel=nodes(tree).find(node=>node.props && "data-ec-panel" in node.props);
  for (const key of ["ArrowLeft","ArrowDown","q","e","Home"]) {
    panel.props.onKeyDown({key,target:{closest:()=>({}),matches:()=>true},preventDefault(){assert.fail("editor key intercepted");},stopPropagation(){assert.fail("editor key intercepted");}});
  }
});
