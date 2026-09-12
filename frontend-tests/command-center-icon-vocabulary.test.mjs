import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import ts from "typescript";

const icons=readFileSync(new URL('../src/quick-access/command-center-icons.tsx',import.meta.url),'utf8');

const required=[
  'profile','refresh-rate','dock-mode','connection-link','battery','controller-priority',
  'tv-dock','controller-settings','quick-actions','shortcut','appearance','updates','diagnostics','about',
];

test('module menus have dedicated icon vocabulary instead of generic status fallbacks',()=>{
  for(const id of required){
    assert.match(icons,new RegExp(`\\| \\"${id}\\"`),`missing ${id} from CommandCenterIconId`);
    assert.match(icons,new RegExp(`case \\"${id}\\"`),`missing ${id} renderer`);
  }
});

test('module icon pack stays monochrome/currentColor for shared focus semantics',()=>{
  const exports={};
  const jsx=(type,props)=>({type,props});
  const compiled=ts.transpileModule(icons,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  new Function('require','exports',compiled)(()=>({jsx,jsxs:jsx}),exports);
  function colors(node){
    if(!node||typeof node!=='object') return [];
    const result=['stroke','fill'].flatMap(key=>node.props?.[key]===undefined?[]:[node.props[key]]);
    const children=node.props?.children;
    return result.concat((Array.isArray(children)?children:[children]).flatMap(colors));
  }
  for(const id of required){
    const values=colors(exports.CommandCenterIcon({id}));
    assert.ok(values.includes('currentColor'),`${id} must inherit focus color`);
    assert.ok(values.every(color=>color==='currentColor'||color==='none'),`${id} introduced a fixed color`);
  }
});
