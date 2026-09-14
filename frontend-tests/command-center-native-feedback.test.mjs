import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/quick-access/expanded-command-center/native.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ES2022,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React}}).outputText.replace(/^import .*;$/gm,'').replace(/export /g,'');
function fixture(find){return new Function('React','Button','findModuleExport',code+';return {createMenuFeedback,NativeMenuButton}')( {createElement:(type,props)=>({type,props})},'button',find);}
test('named Steam mapping preserves receiver and plays one select per native activation',()=>{
 const sounds={IntoGameDetail:101,DefaultOk:102,BasicNav:103},calls=[];
 const dispatcher={PlayNavSound(id){assert.equal(this,dispatcher);calls.push(id)}};
 const find=predicate=>[sounds,dispatcher].find(predicate),api=fixture(find);
 let clicks=0;const button=api.NativeMenuButton({onClick:()=>clicks++});
 const event={preventDefault(){},stopPropagation(){},currentTarget:{click:()=>button.props.onClick()}};
 assert.equal(button.props.onOKButton(event),true);assert.equal(clicks,1);assert.deepEqual(calls,[101]);
 api.createMenuFeedback(find)('back');assert.deepEqual(calls,[101,102]);
 for(const props of [{disabled:true},{'aria-disabled':true}])api.NativeMenuButton(props).props.onOKButton(event);
 assert.equal(clicks,1);assert.deepEqual(calls,[101,102]);
});
test('sound discovery or playback failure never blocks or repeats the click',()=>{
 for(const find of [()=>undefined,()=>{throw Error('missing')},predicate=>[{IntoGameDetail:1,DefaultOk:2,BasicNav:3},{PlayNavSound(){throw Error('muted')}}].find(predicate)]){
  const {NativeMenuButton}=fixture(find);let clicks=0;NativeMenuButton({}).props.onOKButton({preventDefault(){},stopPropagation(){},currentTarget:{click(){clicks++}}});assert.equal(clicks,1);
 }
});
