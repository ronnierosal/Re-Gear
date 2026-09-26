import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const read = path => readFileSync(new URL(`../src/quick-access/expanded-command-center/${path}`, import.meta.url), "utf8");
const compile = source => ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
const visibilityExports = {};
new Function("exports", compile(read("menu-visibility.ts")))(visibilityExports);
const { createMenuVisibility } = visibilityExports;
const actionExports={}; new Function("exports",compile(read("test-build-actions.ts")))(actionExports);

const profileExports={};new Function("exports",compile(readFileSync(new URL("../src/build-profile.ts",import.meta.url),"utf8")))(profileExports);
const utilityExports={};new Function("exports",compile(read("native-utilities.ts")))(utilityExports);
function harness(pendingRecord = null, recoverTerminalDockReceipt = async () => null, policy = "production", system = {}) {
  const h = { modals: [], cleanup: [], timers: new Map(), nextTimer: 1, throwOpen: false, stopped: false, allowed: true };
  const values = new Map(pendingRecord ? [["regear.whole-dock.pending-request", pendingRecord]] : []);
  h.storage = { getItem:key=>values.get(key)??null, setItem:(key,value)=>values.set(key,value), removeItem:key=>values.delete(key) };
  const runtime = {
    createMenuVisibility, ...actionExports, ...profileExports, createNativeUtilities:system=>{h.utilitiesCreated=true;return utilityExports.createNativeUtilities(system);}, GamepadButton:{DIR_UP:9,DIR_DOWN:10,DIR_LEFT:11,DIR_RIGHT:12}, EgpuConfirmModal:"confirm",
    parsePendingRecord: raw => {
      const match = /^v2:(disconnect|disconnect_only|sleep|shutdown):([^:]+):([^:]+)$/.exec(raw ?? "");
      return match ? { intent: match[1], panel: match[2], request: match[3] } : null;
    },
    jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }),
    useEffect: callback => h.cleanup.push(callback()), useState: value => [value, () => {}],
    useSyncExternalStore: (_subscribe, read) => read(),
    Button: "button", Focusable: "focusable", ModalRoot: "modal", Dropdown: "dropdown",
    ExpandedCommandCenter: "expanded", WholeDockControl: "dock", recoverTerminalDockReceipt, ShortcutSettings: "settings",
    loadMenuBinding: () => "view-y", saveMenuBinding: () => true, menuBindingOptions: [],
    startMenuShortcut: options => { h.shortcutOpen = options.open; return { available: true, reset() {}, stop() { h.stopped = true; } }; },
    showModal: (node,parent,options) => {
      if (h.throwOpen) throw Error("host unavailable");
      h.onHostOpen?.();
      const modal = { node, parent, options, closed: false, Close() { this.closed = true; } };
      h.modals.push(modal); return modal;
    },
  };
  const exports = {};
  new Function("require", "exports", compile(read("native.tsx")))(() => runtime, exports);
  h.tiles = { quick: [] };
  h.source = { read: () => h.tiles, subscribe: () => () => {} };
  h.snapshot = () => ({ schema_version: 3 });
  h.detail = () => "existing-detail";
  h.host = {SteamClient:{System:system},localStorage:h.storage,
    setTimeout(callback) { const id=h.nextTimer++;h.timers.set(id,callback);return id; },
    clearTimeout(id) { h.timers.delete(id); }};
  h.runLatestTimer = () => { const entry=[...h.timers.entries()].at(-1);if(!entry)return;h.timers.delete(entry[0]);entry[1](); };
  h.menu = exports.createExpandedMenu(undefined, h.host, () => h.allowed, h.source, h.snapshot, h.detail, undefined, policy);
  h.mount = () => {
    const child = h.modals.at(-1).node.props.children.find(child => typeof child?.type === "function");
    return child.type(child.props);
  };
  return h;
}

let fixtureId = 0;
async function fixture() {
  const compile = path => ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target:ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
  }).outputText.replace(/^import .*;$/gm, "");
  const code = `
    const React = {createElement(type, props, ...children) { return {type, props: {...props, children}}; }};
    const states = []; let cursor = 0;
    const useState = initial => { const i=cursor++; if (!(i in states)) states[i]=initial;
      return [states[i], value => {states[i]=value}]; };
    const useRef = initial => useState({current: initial})[0];
    let effects=[];
    const useLayoutEffect = effect => effects.push(effect);
    const UtilityIcon='utility-icon', UtilityRail='utility-rail', CommandCenterIcon='icon', expandedStyles='', brandIcon='';
    let fixtureTime=1000; const Date={now:()=>fixtureTime};
    const QuickActionRailEditor='right-editor';
    ${compile("../src/quick-access/expanded-command-center/model.ts")}
    ${compile("../src/build-profile.ts")}
    ${compile("../src/quick-access/expanded-command-center/control-registry.ts")}
    ${compile("../src/quick-access/expanded-command-center/utility-layout.ts")}
    ${compile("../src/quick-access/expanded-command-center/layout-preferences.ts")}
    ${compile("../src/quick-access/expanded-command-center/button-catalog.ts")}
    ${compile("../src/quick-access/expanded-command-center/customization-input.ts")}
    ${compile("../src/quick-access/expanded-command-center/layout-customization.tsx")}
    ${compile("../src/quick-access/expanded-command-center/footer-hints.tsx")}
    export function advance(ms){fixtureTime+=ms;}
    ${compile("../src/quick-access/expanded-command-center/shell.tsx")}
    export function render(props) {cursor=0;effects=[];return ExpandedCommandCenter({onClose(){}, ...props});}
    export function restoreFocus() {effects.at(-1)();}
    export function recoverWithdrawnFocus() {effects[0]();}
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

test("production adapter enables native sliders and only the admitted guarded eGPU actions",()=>{
 const h=harness();h.menu.open();const view=h.mount();
 assert.equal(h.utilitiesCreated,true);
 assert.equal(view.props.policy,"production");
 assert.equal(view.props.layoutStorage,undefined);
 assert.equal(view.props.editButtons,undefined);
 assert.equal(view.props.catalogReadings,undefined);
 assert.equal(typeof view.props.onUtilityRequest,"function");
 assert.throws(()=>view.props.onUtilityRequest("wifi"),/Control unavailable/);
 assert.deepEqual(Object.keys(view.props.tiles),["egpu"]);
 assert.deepEqual(view.props.tiles.egpu.map(x=>x.id),["egpu","disconnect","disconnect-sleep","disconnect-shutdown"]);
 assert.equal(nodes(view.props.disconnectControl).some(n=>n.type==="dropdown"),false);
 view.props.onDisconnect("disconnect");
 assert.equal(h.modals.length,1);
 for(const id of ["portable-shutdown","switch-handheld"])
  assert.equal(view.props.onAction("egpu",{id}),false);
 assert.equal(view.props.renderDetail("performance",{id:"auto"}),null);
 view.props.onDisconnect("disconnect_only");
 const dock=nodes(h.modals[1].node).find(n=>n.type==="dock");
 assert.equal(dock.props.intent,"disconnect_only");assert.equal(dock.props.startRequest(),true);
 h.menu.stop();
 for(const [id,intent] of [["disconnect-sleep","sleep"],["disconnect-shutdown","shutdown"]]){
  const actionHarness=harness();actionHarness.menu.open();const actionView=actionHarness.mount();
  assert.equal(actionView.props.onAction("egpu",{id}),true);
  const actionDock=nodes(actionHarness.modals[1].node).find(n=>n.type==="dock");
  assert.equal(actionDock.props.intent,intent);assert.equal(actionDock.props.startRequest(),true);
  actionHarness.menu.stop();
 }
});
test("production shell rejects saved layouts and limits controller navigation to live eGPU tiles",async()=>{
 const app=await fixture();
 let reads=0,actions=0;
 const props={policy:"production",native:true,initialTab:"performance",editButtons:{y:4},
 layoutStorage:{getItem(){reads++;return '{"version":2,"quick":["performance:auto"]}';},setItem(){throw Error("unexpected write");}},
 tiles:{egpu:[{id:"egpu",title:"eGPU",value:"Connected",detail:"Live observation"},{id:"disconnect",title:"Safe Disconnect",value:"Ready",detail:"Guarded action"},{id:"switch-handheld",title:"Hidden",value:"Ready",detail:""}],performance:[{id:"auto",title:"Auto TDP",value:"Running",detail:""}]},
 onAction:()=>{actions++;return true;},onDisconnect(){},catalogReadings:{egpu:[{id:"link",title:"Link",value:"Connected",detail:""}]}};
 let tree=app.render(props);
 const cards=()=>nodes(tree).filter(n=>n.props?.className==="rg-expanded-tile");
 assert.deepEqual(cards().map(n=>n.props["data-ec-control"]),["egpu","disconnect","disconnect-sleep","disconnect-shutdown"]);
 assert.equal(reads,0);
 assert.deepEqual(nodes(tree).filter(n=>n.props?.role==="tab").map(n=>n.props["data-ec-tab"]),["egpu"]);
 assert.deepEqual(nodes(tree).filter(n=>n.type==="utility-rail").map(n=>n.props.side),["left"]);
 assert.doesNotMatch(text(tree),/Switch Tab|Sample data/);
 const panel=nodes(tree).find(n=>n.props?.["data-ec-panel"]!==undefined);
 for(const button of [5,6,4])panel.props.onButtonDown({detail:{button},preventDefault(){},stopPropagation(){}});
 tree=app.render(props);
 assert.deepEqual(cards().map(n=>n.props["data-ec-control"]),["egpu","disconnect","disconnect-sleep","disconnect-shutdown"]);
 cards()[0].props.onClick();tree=app.render(props);assert.equal(actions,0);
});
test("production without readings displays Unknown and Unavailable, never synthetic readiness",async()=>{
 const app=await fixture();const tree=app.render({policy:"production",onDisconnect(){}});
 assert.match(text(tree),/Unknown/);assert.match(text(tree),/Unavailable/);
 assert.doesNotMatch(text(tree),/Sample data|RX 7600M XT|Ready/);
});
test("production retains status-only settlement recovery for existing records",()=>{
 const h=harness("v2:shutdown:panel:"+"a".repeat(32));
 const dock=nodes(h.modals[0].node).find(n=>n.type==="dock");
 assert.equal(dock.props.intent,"shutdown");assert.equal(dock.props.statusOnly,true);
 assert.equal(dock.props.startRequest,undefined);h.menu.stop();
});

test("production unavailable disconnect cannot dispatch or open details, while ready still dispatches",async()=>{
 for(const tiles of [undefined,{egpu:[{id:"disconnect",title:"Safe Disconnect",value:"Unavailable",detail:"Waiting for current status"}]},{egpu:[{id:"disconnect",title:"Safe Disconnect",value:"Unknown",detail:"Stale status",tone:"unavailable"}]}]){
  const app=await fixture();let calls=0;
  const props={policy:"production",tiles,onDisconnect(){calls++;}};
  let tree=app.render(props);
  const button=nodes(tree).find(n=>n.props?.["data-ec-control"]==="disconnect");
  assert.equal(button.props["aria-disabled"],true);
  button.props.onClick();tree=app.render(props);
  assert.equal(calls,0);
  assert.equal(nodes(tree).some(n=>n.props?.className==="rg-expanded-detail-page"),false);
 }
 const app=await fixture();let calls=0;
 const tree=app.render({policy:"production",tiles:{egpu:[{id:"disconnect",title:"Safe Disconnect",value:"Ready",detail:"Guarded flow"}]},onDisconnect(){calls++;}});
 const button=nodes(tree).find(n=>n.props?.["data-ec-control"]==="disconnect");
 assert.equal(button.props["aria-disabled"],false);button.props.onClick();assert.equal(calls,1);
});

test("production read-only eGPU detail enters at the first reading and Back restores its launcher",async()=>{
 const app=await fixture();
 const props={policy:"production",tiles:{egpu:[{id:"egpu",title:"eGPU",value:"Unknown",detail:"Status unavailable"}]},renderDetail:()=>"Connection Unknown; Rendering Unknown"};
 let tree=app.render(props);
 nodes(tree).find(n=>n.props?.["data-ec-control"]==="egpu").props.onClick();
 tree=app.render(props);
 assert.match(text(tree),/Current status . no changes are applied/);
 assert.doesNotMatch(text(tree),/Settings and actions/);
 const contentNode=nodes(tree).find(n=>n.props?.className==="rg-expanded-content");
 const panelNode=nodes(tree).find(n=>n.props?.["data-ec-panel"]!==undefined);
 const nestedNode=nodes(tree).find(n=>n.props?.["data-ec-control"]==="nested-content");
 assert.equal(nestedNode.props.tabIndex,-1);
 const scrolling={scrollTop:240};contentNode.props.ref.current=scrolling;
 let focusOptions,backFocus=0,launcherFocus=0;
 const status={dataset:{ecControl:"nested-content"},focus(options){focusOptions=options;}};
 const launcher={dataset:{ecControl:"egpu"},querySelector(){return null;},matches(){return true;},focus(){launcherFocus++;},scrollIntoView(){}};
 panelNode.props.ref.current={querySelectorAll:()=>[status,launcher],querySelector:()=>({focus(){backFocus++;}})};
 app.restoreFocus();
 assert.deepEqual(focusOptions,{preventScroll:true});
 assert.equal(scrolling.scrollTop,0);assert.equal(backFocus,0);
 nodes(tree).find(n=>n.props?.["data-ec-control"]==="nested-back").props.onClick();
 tree=app.render(props);app.restoreFocus();
 assert.equal(launcherFocus,1);
});


test("production native sliders observe changes, dispatch normalized values and stop across menu lifetimes",async()=>{
 let brightness,volume=.4,unregistered=0;const writes=[];
 const subscription=()=>({unregister(){unregistered++;}});
 const system={Display:{RegisterForBrightnessChanges(cb){brightness=cb;return subscription();},SetBrightness(value){writes.push(["brightness",value]);}},
 Audio:{async GetDevices(){return {activeOutputDeviceId:7,vecDevices:[{id:7,bHasOutput:true,flOutputVolume:volume}]};},async SetDeviceVolume(id,direction,value){writes.push(["volume",id,direction,value]);volume=value;return {result:1};}}};
 const h=harness(null,undefined,"production",system);h.menu.open();brightness({flBrightness:.5});await Promise.resolve();
 let view=h.mount();assert.equal(view.props.utilityReadings.brightness.percent,50);assert.equal(view.props.utilityReadings.volume.percent,40);
 await view.props.onUtilityRequest("brightness",61);assert.equal(h.mount().props.utilityReadings.brightness.percent,50);
 brightness({flBrightness:.61});assert.equal(h.mount().props.utilityReadings.brightness.percent,61);
 await view.props.onUtilityRequest("volume",72);assert.equal(h.mount().props.utilityReadings.volume.percent,72);
 assert.deepEqual(writes,[["brightness",.61],["volume",7,1,.72]]);
 const oldRequest=view.props.onUtilityRequest;view.props.onClose();assert.equal(unregistered,1);
 h.menu.open();view=h.mount();assert.equal(view.props.utilityReadings.brightness.available,false);
 await assert.rejects(oldRequest("brightness",20),/closed|unavailable/i);
 h.menu.stop();assert.equal(unregistered,2);
});

test("production left rail forwards only slider requests and hides while viewing details",async()=>{
 const app=await fixture(),calls=[];
 const props={policy:"production",onUtilityRequest:(...args)=>calls.push(args),utilityReadings:{brightness:{available:true,percent:50,value:"50%"},volume:{available:true,percent:40,value:"40%"}}};
 let tree=app.render(props);const rail=nodes(tree).find(n=>n.type==="utility-rail");
 rail.props.onRequest("brightness",55);rail.props.onRequest("volume",45);
 assert.throws(()=>rail.props.onRequest("wifi"),/Control unavailable/);
 assert.deepEqual(calls,[["brightness",55],["volume",45]]);
 nodes(tree).find(n=>n.props?.["data-ec-control"]==="egpu").props.onClick();tree=app.render(props);
 assert.equal(nodes(tree).some(n=>n.type==="utility-rail"),false);
});

test("production sliders stay unavailable without native capabilities",async()=>{
 const h=harness();h.menu.open();const view=h.mount();
 for(const id of ["brightness","volume"]){assert.equal(view.props.utilityReadings[id].available,false);await assert.rejects(view.props.onUtilityRequest(id,50),/Control unavailable/);}
 h.menu.stop();
});

test("development still exposes both rails on Quick Access",async()=>{
 const app=await fixture();const tree=app.render({policy:"development"});
 assert.deepEqual(nodes(tree).filter(n=>n.type==="utility-rail").map(n=>n.props.side),["left","right"]);
});

test("production D-pad enters the left rail and returns to the launching eGPU card",async()=>{
 const app=await fixture();const tree=app.render({policy:"production",native:true,directions:{up:9,down:10,left:11,right:12}});
 const focused=[];
 const controls=["egpu","utility-brightness"].map(id=>({dataset:{ecControl:id},querySelector(){return null;},matches(){return true;},focus(){focused.push(id);},scrollIntoView(){}}));
 nodes(tree).find(n=>n.props?.["data-ec-panel"]!==undefined).props.ref.current={querySelectorAll:()=>controls};
 let prevented=0,stopped=0;
 const card=nodes(tree).find(n=>n.props?.["data-ec-control"]==="egpu");
 card.props.onGamepadDirection({detail:{button:11},preventDefault(){prevented++;},stopPropagation(){stopped++;}});
 assert.deepEqual(focused,["utility-brightness"]);assert.equal(prevented,1);assert.equal(stopped,1);
 nodes(tree).find(n=>n.type==="utility-rail").props.onReturnToGrid();
 assert.deepEqual(focused,["utility-brightness","egpu"]);
});
