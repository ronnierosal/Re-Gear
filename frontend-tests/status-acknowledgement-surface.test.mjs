import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

// Execute the actual status-view expressions published by Content. A fixture
// of the acknowledgement component alone cannot prove native reachability.
const source=readFileSync(new URL('../src/index.tsx',import.meta.url),'utf8');
const tree=ts.createSourceFile('index.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let production,views;
function visit(node){
 if(ts.isVariableDeclaration(node)&&node.name.getText(tree)==='productionEgpuDetail')production=node.initializer;
 if(ts.isPropertyAssignment(node)&&node.name.getText(tree)==='views'&&node.getText(tree).includes('productionEgpuDetail'))views=node.initializer;
 ts.forEachChild(node,visit);
}visit(tree);
assert.ok(production&&views);
const jsx=(type,props)=>({type,props});
const guarded=Symbol('existing guarded acknowledgement');
function evaluate(node,values){
 const js=ts.transpileModule(`const value=${node.getText(tree)};`,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 return new Function('require','exports',...Object.keys(values),`${js};return value;`)(()=>({jsx,jsxs:jsx,Fragment:'fragment'}),{},...Object.values(values));
}
function nodes(t){return !t||typeof t!=='object'?[]:Array.isArray(t)?t.flatMap(nodes):[t,...nodes(t.props?.children)];}
for(const profile of ['development','production'])test(`${profile} real eGPU Status publishes the existing guarded action directly`,()=>{
 const payload={snapshot:{schema_version:3},connection_readiness:{stage:'disconnected'}};
 const env={PanelSection:'panel',PanelSectionRow:'row',EgpuModule:'egpu',ButtonItem:'button',TransitionAcknowledgementControl:guarded,
  egpuPresentation:p=>({hasReading:!!p}),payload,menuFresh:true,buildProfile:profile,
  wrapDetail:node=>node,egpuDetail:null,diagnosticDetail:null,displayDetail:null,runtimeDetails:{source:{navigate(){throw Error('unexpected navigation')}}}};
 env.productionEgpuDetail=evaluate(production,env);
 const status=evaluate(views,env).egpu;
 assert.equal(nodes(status).filter(n=>n.type===guarded).length,1,'status must mount the existing exact-ID guarded component');
 assert.equal(nodes(status).filter(n=>n.type==='egpu').length,1);
 assert.equal(nodes(status).filter(n=>n.type===guarded)[0].props.onClick,undefined,'surface must not replace guarded activation');
 assert.match(source,/import\s*\{\s*TransitionAcknowledgementControl\s*\}\s*from\s*["']\.\/transition-acknowledgement-control/);
});
