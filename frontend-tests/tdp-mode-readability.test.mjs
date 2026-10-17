import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

// Execute the real TSX with a deterministic hook/element fixture. This checks
// rendered copy and update behavior; it does not simulate native Decky focus.
let fixtureId = 0;
async function fixture() {
  const compile = path => ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8").replace(/^import (\w+) from "[^"\n]+\.svg[^"\n]*";$/gm, 'const $1="fixture.svg";'), {
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
    const useEffect = ()=>{};
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
    ${compile("../src/quick-access/expanded-command-center/v3-tile-artwork.tsx")}
    ${compile("../src/quick-access/expanded-command-center/regear-tile.tsx")}
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

test('Power settings uses a normal Performance tile; standalone strip and button are absent on every tab',async()=>{
 for(const native of [false,true]) for(const tab of ['quick','performance','egpu','controllers','offline','settings']){
  const app=await fixture();let mutations=0;const details=[];
  const props={native,initialTab:tab,tiles:{quick:[tile('manual'),tile('auto')],performance:[tile('manual'),tile('auto')],egpu:[],controllers:[],offline:[],settings:[]},tdpCycle:{value:'Performance · Unavailable',detail:'Selected Performance · Applied mode unavailable · No current provider observation'},onAction:(tab,item)=>{if(item.id!=='auto')mutations++;return false;},renderDetail:(tab,tile)=>{details.push([tab,tile.id,tile.value]);return {type:'power-settings',props:{children:'Basic Advanced Start Stop Status'}};}};
  let tree=app.render(props);assert.equal(control(tree,'auto-settings'),undefined);assert.equal(nodes(tree).find(n=>n.props?.['data-tdp-cycle-status']!==undefined),undefined);
  if(tab==='quick'||tab==='performance'){const mode=control(tree,'manual');assert.ok(mode.props.className.includes('rg-tdp-mode-tile'));assert.match(text(mode),/Performance · Unavailable/);assert.match(mode.props['aria-label'],/Selected Performance/);}
  if(tab!=='performance'){assert.equal(control(tree,'auto'),undefined);continue;}
  const settings=control(tree,'auto');assert.ok(settings);assert.equal(settings.props.className,'rg-expanded-tile');assert.match(settings.props['aria-label'],/^Power settings:/);if(native)assert.equal(settings.props.label,'Power settings');
  settings.props.onClick();tree=app.render(props);assert.equal(mutations,0);assert.deepEqual(details,[['performance','auto','Unknown']]);assert.match(text(tree),/Basic Advanced Start Stop Status/);
  props.tiles.performance[1]={...tile('auto'),value:'Stopping…'};tree=app.render(props);assert.equal(details.at(-1)[2],'Stopping…');
  props.tiles={quick:[tile('manual')],performance:[tile('manual')]};tree=app.render(props);assert.match(text(tree),/Status unavailable/);assert.equal(details.length,2);
  control(tree,'nested-back').props.onClick();tree=app.render(props);assert.equal(control(tree,'auto'),undefined);assert.equal(mutations,0);
 }
});
test('all full mode values and long status remain distinct with original cycle dispatch identity',async()=>{
 const app=await fixture(),calls=[];const values=['Chill','Balanced','Performance','Auto','Custom','Applying Performance','Performance · Unavailable'];
 const props={tiles:{quick:[tile('manual')]},onAction:(tab,tile)=>{calls.push([tab,tile.id]);return true;}};
 for(const value of values){const detail=`Selected ${value} · Applied mode unavailable · ${'No current provider observation. '.repeat(12)}`;const tree=app.render({...props,tdpCycle:{value,detail}});const mode=control(tree,'manual');assert.ok(mode.props.className.includes('rg-tdp-mode-tile'));assert.match(text(mode),new RegExp(value.replace('·','\\u00b7')));assert.match(mode.props['aria-label'],/Applied mode unavailable/);assert.equal(nodes(tree).find(n=>n.props?.['data-tdp-cycle-status']!==undefined),undefined);mode.props.onClick();}
 assert.deepEqual(calls,values.map(()=>['quick','manual']));
});

test('saved Manual aliases receive the same readable cycle and retain canonical dispatch',async()=>{
 for(const key of ['quick:manual','performance:manual']){const app=await fixture(),calls=[];const storage={getItem:()=>JSON.stringify({version:2,quick:[key]}),setItem(){assert.fail('render must not rewrite preferences');}};const props={layoutStorage:storage,tiles:{quick:[tile('manual'),tile('auto')],performance:[tile('manual'),tile('auto')]},tdpCycle:{value:'Applying Performance',detail:'Applying Performance · Last checked: Balanced 15 W'},onAction:(tab,tile)=>{calls.push([tab,tile.id]);return true;}};const tree=app.render(props);const mode=control(tree,key==='quick:manual'?'manual':'custom:performance:manual');assert.ok(mode.props.className.includes('rg-tdp-mode-tile'));assert.match(text(mode),/Applying Performance/);assert.match(mode.props['aria-label'],/Last checked: Balanced 15 W/);assert.equal(nodes(tree).find(n=>n.props?.['data-tdp-cycle-status']!==undefined),undefined);mode.props.onClick();assert.deepEqual(calls,[[key.split(':')[0],'manual']]);}
});
