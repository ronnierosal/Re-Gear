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
const control=(tree,id)=>nodes(tree).find(n=>n.props?.['data-ec-control']===id);
const tile=id=>({id,title:id==='auto'?'Auto TDP':'Manual TDP',value:'Unknown',detail:'No observation'});

test('both unsaved default grids retain mode and visible read-only Auto settings route',async()=>{
 for(const tab of ['quick','performance']){
  const app=await fixture();let actions=0;const details=[];
  const props={initialTab:tab,tiles:{quick:[tile('manual'),tile('auto')],performance:[tile('manual'),tile('auto')]},tdpCycle:{value:'Performance · Unavailable',detail:'Selected Performance · Applied mode unavailable · No current provider observation'},onAction:()=>{actions++;return true;},renderDetail:(tab,tile)=>{details.push([tab,tile.id,tile.value]);return {type:'existing-auto-settings',props:{children:'Configuration Start Stop Status'}};}};
  let tree=app.render(props);assert.equal(control(tree,'auto'),undefined);assert.ok(control(tree,'manual').props.className.includes('rg-tdp-mode-tile'));assert.match(text(tree),/Performance · Unavailable/);
  const status=nodes(tree).find(n=>n.props?.['data-tdp-cycle-status']!==undefined);assert.equal(text(status),props.tdpCycle.detail);
  control(tree,'auto-settings').props.onClick();tree=app.render(props);assert.equal(actions,0);assert.deepEqual(details,[['performance','auto','Unknown']]);assert.match(text(tree),/Configuration Start Stop Status/);
  props.tiles.performance[1]={...tile('auto'),value:'Stopping…'};tree=app.render(props);assert.equal(details.at(-1)[2],'Stopping…');assert.equal(actions,0);
  props.tiles={quick:[tile('manual')],performance:[tile('manual')]};tree=app.render(props);assert.match(text(tree),/Status unavailable/);assert.equal(details.length,2,'withdrawn source never invokes stale configuration');
  control(tree,'nested-back').props.onClick();tree=app.render(props);assert.equal(control(tree,'auto-settings'),undefined);assert.equal(actions,0);
 }
});
test('all full mode values and long status remain distinct with original cycle dispatch identity',async()=>{
 const app=await fixture(),calls=[];const values=['Chill','Balanced','Performance','Auto','Custom','Applying Performance','Performance · Unavailable'];
 const props={tiles:{quick:[tile('manual')]},onAction:(tab,tile)=>{calls.push([tab,tile.id]);return true;}};
 for(const value of values){const detail=`Selected ${value} · Applied mode unavailable · ${'No current provider observation. '.repeat(12)}`;const tree=app.render({...props,tdpCycle:{value,detail}});const mode=control(tree,'manual');assert.ok(mode.props.className.includes('rg-tdp-mode-tile'));assert.match(text(mode),new RegExp(value.replace('·','\\u00b7')));assert.equal(text(nodes(tree).find(n=>n.props?.['data-tdp-cycle-status']!==undefined)),detail);mode.props.onClick();}
 assert.deepEqual(calls,values.map(()=>['quick','manual']));
});

test('saved Manual aliases receive the same readable cycle and retain canonical dispatch',async()=>{
 for(const key of ['quick:manual','performance:manual']){const app=await fixture(),calls=[];const storage={getItem:()=>JSON.stringify({version:2,quick:[key]}),setItem(){assert.fail('render must not rewrite preferences');}};const props={layoutStorage:storage,tiles:{quick:[tile('manual'),tile('auto')],performance:[tile('manual'),tile('auto')]},tdpCycle:{value:'Applying Performance',detail:'Applying Performance · Last checked: Balanced 15 W'},onAction:(tab,tile)=>{calls.push([tab,tile.id]);return true;}};const tree=app.render(props);const mode=control(tree,key==='quick:manual'?'manual':'custom:performance:manual');assert.ok(mode.props.className.includes('rg-tdp-mode-tile'));assert.match(text(mode),/Applying Performance/);assert.equal(text(nodes(tree).find(n=>n.props?.['data-tdp-cycle-status']!==undefined)),props.tdpCycle.detail);mode.props.onClick();assert.deepEqual(calls,[[key.split(':')[0],'manual']]);}
});
