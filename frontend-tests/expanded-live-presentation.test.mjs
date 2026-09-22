import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

// Execute the real TSX with a deterministic hook/element fixture. This checks
// rendered copy and update behavior; it does not simulate native Decky focus.
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
const auto = (value, detail) => ({id:"auto",title:"Auto TDP",value,detail});

test('saved eGPU widget retains identity across fresh stale fresh and A never acts',async()=>{
 const app=await fixture(),storage=storageFixture();storage.setItem('regear.command-center-layout.v1',JSON.stringify({version:2,quick:['egpu:widget-link']}));let calls=0;
 const props={...prefsProps(storage),tiles:{quick:[],egpu:[]},onAction:()=>{calls++;return false;},catalogReadings:{egpu:[{id:'link',title:'Link',value:'Connected',detail:'Observed connection',tone:'quiet'}]}};
 let tree=app.render(props),widget=card(tree,'custom:egpu:widget-link');assert.match(text(widget),/Connected/);widget.props.onClick();assert.equal(calls,0);
 props.catalogReadings={egpu:[]};tree=app.render(props);widget=card(tree,'custom:egpu:widget-link');assert.match(text(widget),/Unknown/);assert.equal(widget.props['data-empty'],undefined);
 props.catalogReadings={egpu:[{id:'link',title:'Link',value:'Connected',detail:'Verified link observation',tone:'active'}]};tree=app.render(props);assert.match(text(card(tree,'custom:egpu:widget-link')),/Connected/);
 frame(tree).props.onFocus({target:{closest:()=>({dataset:{ecControl:'custom:egpu:widget-link'}})}});yGesture(app,tree);tree=app.render(props);assert.ok(card(tree,'choice:egpu:widget-link'));
 card(tree,'filter:widgets').props.onClick();tree=app.render(props);assert.ok(card(tree,'choice:egpu:widget-link'));assert.equal(nodes(tree).filter(n=>n.props?.['data-ec-control']?.startsWith('choice:')).length,2,'one widget plus Remove');
});

test('Wi-Fi can be placed on Quick Access without dispatching an unavailable adapter',async()=>{
 const app=await fixture(),storage=storageFixture();storage.setItem('regear.command-center-layout.v1',JSON.stringify({version:2,quick:['empty:0']}));let calls=0;
 const props={...prefsProps(storage),tiles:{quick:[]},utilityReadings:{wifi:{available:false,value:'Unavailable'}},onUtilityRequest:async()=>calls++};
 let tree=app.render(props);yGesture(app,tree);tree=app.render(props);card(tree,'choice:settings:utility-wifi').props.onClick();tree=app.render(props);const wifi=card(tree,'custom:settings:utility-wifi');assert.equal(wifi.props['aria-disabled'],true);wifi.props.onClick();assert.equal(calls,0);
 const fresh=await fixture();tree=fresh.render(props);assert.ok(card(tree,'custom:settings:utility-wifi'));
});

test('Settings reset is a real confirmed layout write, About is shared, and shortcut/help stay on landing',async()=>{
 const app=await fixture(),storage=storageFixture();storage.setItem('regear.command-center-layout.v1',JSON.stringify({version:2,quick:['egpu:widget-link'],right:[null,null,null,null]}));
 const props={...prefsProps(storage),initialTab:'settings',tiles:{settings:['shortcut','about','help-guides','diagnostics','reset-layout'].map(id=>({id,title:id,value:'Open',detail:''}))}};
 let tree=app.render(props);assert.deepEqual(nodes(tree).filter(n=>n.props?.className==='rg-expanded-tile').map(n=>n.props['data-ec-control']),['about','diagnostics','reset-layout']);
 card(tree,'reset-layout').props.onClick();tree=app.render(props);const confirm=nodes(tree).find(n=>n.type==='button'&&text(n)==='Reset layout');assert.ok(confirm);assert.deepEqual(JSON.parse(storage.getItem('regear.command-center-layout.v1')).quick,['egpu:widget-link']);confirm.props.onClick();assert.deepEqual(JSON.parse(storage.getItem('regear.command-center-layout.v1')).quick,[]);
});

test('cancelled Y hold cannot rearm on native or keyboard repeats after focus changes',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});
 for(const keyboard of [false,true]){
  const app=await fixture(),props=prefsProps(storageFixture());let tree=app.render(props);
  const down=repeat=>keyboard?frame(tree).props.onKeyDown({key:'y',repeat,preventDefault(){},stopPropagation(){}}):frame(tree).props.onButtonDown({...nativeEvent(4),detail:{button:4,is_repeat:repeat}});
  down(false);frame(tree).props.onGamepadBlur();down(true);t.mock.timers.tick(550);tree=app.render(props);
  assert.equal(nodes(tree).some(n=>n.props?.['data-layout-customizing']),false);
  frame(tree).props.onButtonUp(nativeEvent(4));tree=app.render(props);
  assert.equal(nodes(tree).some(n=>n.props?.['data-ec-picker']),false);
  down(false);t.mock.timers.tick(550);tree=app.render(props);
  assert.equal(nodes(tree).some(n=>n.props?.['data-layout-customizing']),true,'new press still enters Move before release');
  frame(tree).props.onButtonUp(nativeEvent(4));
 }
});

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

test("a tabindex-bearing detail wrapper focuses its editor rather than itself", async () => {
  const app=await fixture();
  const props={tiles:{quick:[auto("Ready", "Configure")]},renderDetail:()=>"Editor"};
  let tree=app.render(props);
  nodes(tree).find(node=>node.props?.["data-ec-control"] === "auto").props.onClick();
  tree=app.render(props);
  let focused;
  const editor={focus(){focused="editor";},scrollIntoView(){}};
  const wrapper={dataset:{ecControl:"nested-content"},matches:()=>true,querySelector:()=>editor,focus(){focused="wrapper";}};
  nodes(tree).find(node=>node.props && "data-ec-panel" in node.props).props.ref.current={querySelectorAll:()=>[wrapper]};
  app.restoreFocus();
  assert.equal(focused,"editor");
});

test("withdrawn focused controls recover Back without stealing retained dialog focus", async () => {
  for (const removed of [false,true]) {
    const app=await fixture();
    const props={tiles:{quick:[auto("Ready","Configure")]},renderDetail:()=>"Editor"};
    let tree=app.render(props);
    nodes(tree).find(node=>node.props?.["data-ec-control"] === "auto").props.onClick();
    tree=app.render(props);
    let panel=nodes(tree).find(node=>node.props && "data-ec-panel" in node.props);
    panel.props.onFocus({target:{closest:()=>({dataset:{ecControl:"nested-content"}})}});
    const body={isConnected:true};
    const doc={body,activeElement:body};
    let calls=0;
    const back={dataset:{ecControl:"nested-back"},matches:()=>true,querySelector:()=>null,focus(){calls++;},scrollIntoView(){}};
    panel.props.ref.current={ownerDocument:doc,querySelectorAll:()=>[back]};
    // A normal update must not reset an editor's focus/caret.
    tree=app.render(props);
    app.recoverWithdrawnFocus();
    assert.equal(calls,0);
    tree=app.render(removed?{...props,tiles:{quick:[]}}:{...props,renderDetail:()=>null});
    // If native focus has already moved to a surviving control, keep it there.
    doc.activeElement={isConnected:true};
    app.recoverWithdrawnFocus();
    assert.equal(calls,0);
    doc.activeElement=body;
    app.recoverWithdrawnFocus();
    assert.equal(calls,1);
  }
});

test("compact cards present icon and label before the value and secondary detail",async()=>{
 const app=await fixture();const tree=app.render({tiles:{quick:[{id:'manual',title:'Manual TDP',value:'18 W',detail:'Current limit'}]}});
 const tile=nodes(tree).find(node=>node.props?.['data-ec-control']==='manual');
 const body=text(tile);assert.ok(body.indexOf('Manual TDP')<body.indexOf('18 W'));
 assert.ok(body.indexOf('18 W')<body.indexOf('Current limit'));
 const heading=nodes(tile).find(node=>node.props?.className==='rg-expanded-tile-heading');
 assert.match(text(heading),/Manual TDP/);
 assert.ok(nodes(heading).some(node=>node.props?.className==='rg-expanded-tile-icon'));
});

test("Quick Access mounts both unavailable utility rails and details hide them",async()=>{
 const app=await fixture(); const props={tiles:{quick:[auto('Unknown','No observation')]}};
 let tree=app.render(props);
 assert.deepEqual(nodes(tree).filter(node=>node.type==='utility-rail').map(node=>node.props.side),['left','right']);
 nodes(tree).find(node=>node.props?.['data-ec-control']==='auto').props.onClick();tree=app.render(props);
 assert.equal(nodes(tree).filter(node=>node.type==='utility-rail').length,0);
});

// Steam wraps logical direction callbacks: only an explicit false
// leaves the event available for parent navigation. Verified on installed102.
function steamEvent(handler, button) {
  const event={detail:{button},prevented:false,stopped:false,
    preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}};
  if (handler(event)!==false) {event.stopPropagation();event.preventDefault();}
  return event;
}
test("native tile directions bubble to Steam grid unless the rail entry is handled", async () => {
  const app=await fixture();
  const tree=app.render({native:true,directions:{up:9,down:10,left:11,right:12}});
  const tile=nodes(tree).find(node=>node.props?.["data-ec-control"]==="manual");
  for(const button of [9,10,11,12]) {
    const event=steamEvent(tile.props.onGamepadDirection,button);
    assert.equal(event.stopped,false,`direction ${button} must reach parent grid`);
    assert.equal(event.prevented,false);
  }

});

test("native LEFT enters Quick Access rail only from its first column",async()=>{
 const app=await fixture();let focused;
 const tree=app.render({native:true,directions:{up:9,down:10,left:11,right:12}});
 const slider={dataset:{ecControl:'utility-brightness'},querySelector:()=>null,matches:()=>true,focus(){focused='brightness'},scrollIntoView(){}};
 nodes(tree).find(node=>node.props&&'data-ec-panel' in node.props).props.ref.current={querySelectorAll:()=>[slider]};
 const fps=nodes(tree).find(node=>node.props?.['data-ec-control']==='fps');
 assert.equal(steamEvent(fps.props.onGamepadDirection,11).stopped,true);
 assert.equal(focused,'brightness');
 const other=await fixture();
 const performance=other.render({native:true,initialTab:'performance',directions:{up:9,down:10,left:11,right:12}});
 const profile=nodes(performance).find(node=>node.props?.['data-ec-control']==='profile');
 assert.equal(steamEvent(profile.props.onGamepadDirection,11).stopped,false);
});

function storageFixture(){const writes=[];let value=null;return {writes,getItem:()=>value,setItem:(_,next)=>{value=next;writes.push(JSON.parse(next));}};}
const nativeEvent=button=>({detail:{button},preventDefault(){},stopPropagation(){}});
const frame=tree=>nodes(tree).find(node=>node.props&&'data-ec-panel' in node.props);
const card=(tree,id)=>nodes(tree).find(node=>node.props?.['data-ec-control']===id);
const prefsProps=storage=>({native:true,layoutStorage:storage,editButtons:{x:3,y:4},directions:{up:9,down:10,left:11,right:12}});
function yGesture(app,tree,ms=0){frame(tree).props.onButtonDown(nativeEvent(4));app.advance(ms);frame(tree).props.onButtonUp(nativeEvent(4));}
test('Y imported card resolves live original detail and withdraws unavailable origin',async()=>{
 const app=await fixture(),storage=storageFixture(),calls=[];
 const props={...prefsProps(storage),tiles:{quick:[auto('Off','current')],performance:[{id:'display',title:'Resolution',value:'1080',detail:'observed'}]},renderDetail:(tab,tile)=>{calls.push([tab,tile.value]);return 'live detail'}};
 let tree=app.render(props);yGesture(app,tree);tree=app.render(props);
 card(tree,'choice:performance:display').props.onClick();tree=app.render(props);
 assert.equal(storage.writes.length,1);assert.deepEqual(storage.writes[0].quick.slice(0,1),['performance:display']);
 const reopened=await fixture();assert.ok(card(reopened.render(props),'custom:performance:display'),'saved IDs survive reopening');
 card(tree,'custom:performance:display').props.onClick();tree=app.render(props);
 assert.deepEqual(calls.at(-1),['performance','1080']);
 props.tiles.performance[0]={...props.tiles.performance[0],value:'1440'};tree=app.render(props);
 assert.deepEqual(calls.at(-1),['performance','1440']);
 const previous=calls.length;props.tiles.performance=[];tree=app.render(props);
 assert.equal(calls.length,previous);assert.match(text(tree),/Status unavailable/);
});
test('empty Quick Access slots render as accessible outlines without visible copy',async()=>{
 const app=await fixture(),storage=storageFixture();
 storage.setItem('regear.command-center-layout.v1',JSON.stringify({version:2,quick:['empty:0']}));
 const tree=app.render(prefsProps(storage));
 const empty=card(tree,'empty:0');
 assert.equal(empty.props['data-empty'],true);
 assert.equal(empty.props['aria-label'],'Empty Quick Access slot. Press Y to add a button.');
 assert.equal(text(empty),'');
});
test('hold Y moves draft only, B cancels, A places without dispatching the action',async()=>{
 const app=await fixture(),storage=storageFixture();let starts=0;
 const props={...prefsProps(storage),tiles:{quick:[{id:'disconnect',title:'Safe Disconnect',value:'Unknown',detail:''},auto('Off','')]},onDisconnect:()=>starts++};
 let tree=app.render(props);card(tree,'disconnect').props.onGamepadFocus();yGesture(app,tree,550);tree=app.render(props);
 card(tree,'disconnect').props.onGamepadDirection(nativeEvent(12));tree=app.render(props);
 assert.equal(storage.writes.length,0);
 frame(tree).props.onCancelButton(nativeEvent(2));tree=app.render(props);
 assert.equal(storage.writes.length,0);assert.equal(starts,0);
 card(tree,'disconnect').props.onGamepadFocus();yGesture(app,tree,550);tree=app.render(props);
 card(tree,'disconnect').props.onGamepadDirection(nativeEvent(12));tree=app.render(props);card(tree,'disconnect').props.onClick();tree=app.render(props);
 assert.deepEqual(storage.writes.at(-1).quick.slice(0,2),['quick:auto','quick:disconnect']);assert.equal(starts,0);
 card(tree,'disconnect').props.onClick();assert.equal(starts,1);
});
test('tab routing clears slider adjustment and pending Y gesture',async()=>{
 const app=await fixture(),props=prefsProps(storageFixture());let tree=app.render(props);
 const rail=nodes(tree).find(node=>node.type==='utility-rail'&&node.props.side==='left');rail.props.onEditingChange('brightness');tree=app.render(props);assert.match(text(tree),/D-pad Adjust/);
 frame(tree).props.onButtonDown(nativeEvent(6));tree=app.render(props);assert.doesNotMatch(text(tree),/D-pad Adjust/);
 frame(tree).props.onButtonDown(nativeEvent(4));frame(tree).props.onButtonDown(nativeEvent(5));tree=app.render(props);app.advance(600);frame(tree).props.onButtonUp(nativeEvent(4));tree=app.render(props);
 assert.ok(!nodes(tree).some(node=>node.props?.['data-layout-customizing']===true));
});

test('other tabs ignore Y tap and persist reorder without replacing membership',async()=>{
 const app=await fixture(),storage=storageFixture(),props={...prefsProps(storage),initialTab:'performance'};
 let tree=app.render(props);yGesture(app,tree);tree=app.render(props);
 assert.ok(!nodes(tree).some(node=>String(node.props?.['data-ec-control']).startsWith('choice:')));
 yGesture(app,tree,550);tree=app.render(props);card(tree,'profile').props.onGamepadDirection(nativeEvent(12));tree=app.render(props);card(tree,'profile').props.onClick();tree=app.render(props);
 assert.deepEqual(storage.writes.at(-1).order.performance,['fps','profile','manual','auto','display','refresh']);
});
test('Y edits focused unavailable right slot without dispatch; X is unused',async()=>{
 const app=await fixture(),storage=storageFixture();let calls=0;
 const props={...prefsProps(storage),utilityReadings:{},onUtilityRequest:async()=>calls++};
 let tree=app.render(props);frame(tree).props.onButtonDown(nativeEvent(3));tree=app.render(props);
 assert.ok(!nodes(tree).some(node=>node.props?.['data-ec-picker']!==undefined));
 frame(tree).props.onFocus({target:{closest:selector=>selector==='[data-ec-control]'?{dataset:{ecControl:'utility-slot-0'}}:null}});
 yGesture(app,tree);tree=app.render(props);
 assert.equal(card(tree,'right-choice:audio').props.disabled,undefined,'unavailable slots can be selected as preferences');
 card(tree,'right-choice:audio').props.onClick();tree=app.render(props);
 assert.deepEqual(storage.writes.at(-1).right,['audio','wifi','overlay','recording']);assert.equal(calls,0);
});

test('picker preserves panel but blocks background disconnect and tab changes; B cancels only picker',async()=>{
 const app=await fixture(),storage=storageFixture();let starts=0,closes=0;
 const props={...prefsProps(storage),onDisconnect:()=>starts++,onClose:()=>closes++};
 let tree=app.render(props);yGesture(app,tree);tree=app.render(props);
 assert.ok(nodes(tree).some(node=>node.props?.className==='rg-expanded'&&node.props.inert===''));
 card(tree,'disconnect').props.onClick();
 nodes(tree).find(node=>node.props?.['data-ec-tab']==='egpu').props.onClick();
 tree=app.render(props);assert.equal(starts,0);
 assert.equal(nodes(tree).find(node=>node.props?.['data-ec-tab']==='quick').props['aria-selected'],true);
 frame(tree).props.onCancelButton(nativeEvent(2));tree=app.render(props);
 assert.equal(closes,0);assert.equal(storage.writes.length,0);
 assert.ok(!nodes(tree).some(node=>node.props&&'data-ec-picker' in node.props));
});

test('failed layout save remains visible and never falls through to disconnect',async()=>{
 const app=await fixture();let starts=0;
 const props={...prefsProps({getItem:()=>null,setItem(){throw Error('full')}}),tiles:{quick:[{id:'disconnect',title:'Safe Disconnect',value:'Unknown',detail:''}]},onDisconnect:()=>starts++};
 let tree=app.render(props);yGesture(app,tree,550);tree=app.render(props);card(tree,'disconnect').props.onClick();tree=app.render(props);
 assert.match(text(tree),/Could not save this layout/);assert.equal(starts,0);
 frame(tree).props.onCancelButton(nativeEvent(2));tree=app.render(props);assert.doesNotMatch(text(tree),/Could not save this layout/);
});

test('native raw picker input reaches Steam logical synthesis for A, B and directions',async()=>{
 const app=await fixture(),storage=storageFixture(),props=prefsProps(storage);
 let tree=app.render(props);yGesture(app,tree);tree=app.render(props);
 const synthesized=[];
 const dispatch=(button,logical)=>{const event={detail:{button},cancelBubble:false,preventDefault(){},stopPropagation(){this.cancelBubble=true;}};frame(tree).props.onButtonDown(event);if(!event.cancelBubble){synthesized.push(button);logical?.();}};
 dispatch(9);dispatch(10);dispatch(11);dispatch(12);
 dispatch(1,()=>card(tree,'choice:performance:display').props.onClick());tree=app.render(props);
 assert.deepEqual(synthesized,[9,10,11,12,1]);assert.ok(storage.writes.at(-1).quick.includes('performance:display'));
 yGesture(app,tree);tree=app.render(props);dispatch(2,()=>frame(tree).props.onCancelButton(nativeEvent(2)));tree=app.render(props);
 assert.ok(!nodes(tree).some(n=>n.props&&'data-ec-picker' in n.props));
});

test('right picker cancel and save restore the focused rail control',async()=>{
 const app=await fixture(),storage=storageFixture(),props=prefsProps(storage);let tree=app.render(props),focused;
 const markRight=()=>frame(tree).props.onFocus({target:{closest:selector=>selector==='[data-ec-control]'?{dataset:{ecControl:'utility-slot-0'}}:null}});
 const restore=()=>{frame(tree).props.ref.current={querySelectorAll:()=>['utility-slot-0','utility-slot-0'].map(id=>({dataset:{ecControl:id},querySelector(){},matches:()=>true,focus(){focused=id},scrollIntoView(){}})),querySelector:()=>({focus(){focused='fallback'}})};app.restoreFocus();};
 markRight();yGesture(app,tree);tree=app.render(props);frame(tree).props.onCancelButton(nativeEvent(2));tree=app.render(props);restore();assert.equal(focused,'utility-slot-0');
 markRight();yGesture(app,tree);tree=app.render(props);card(tree,'right-choice:audio').props.onClick();tree=app.render(props);restore();assert.equal(focused,'utility-slot-0');
});


test('unavailable choices stay focusable for Y removal without dispatch',async()=>{
 const app=await fixture(),storage=storageFixture();let actions=0,disconnects=0;
 const props={...prefsProps(storage),tiles:{quick:[auto('Off','')],egpu:[{id:'switch-handheld',title:'Handheld',value:'Unavailable',detail:''}]},unavailableActions:{'switch-handheld':'No adapter'},onAction:()=>{actions++;return true},onDisconnect:()=>disconnects++};
 let tree=app.render(props);yGesture(app,tree);tree=app.render(props);card(tree,'choice:egpu:switch-handheld').props.onClick();tree=app.render(props);
 const unavailable=card(tree,'custom:egpu:switch-handheld');assert.equal(unavailable.props.disabled,undefined);assert.equal(unavailable.props['aria-disabled'],true);
 unavailable.props.onClick();assert.equal(actions,0);assert.equal(disconnects,0);
 unavailable.props.onGamepadFocus();yGesture(app,tree);tree=app.render(props);card(tree,'choice:remove').props.onClick();tree=app.render(props);
 assert.ok(storage.writes.at(-1).quick[0].startsWith('empty:'));assert.equal(actions,0);
});
