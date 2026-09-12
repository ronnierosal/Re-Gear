import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const shell = readFileSync(new URL("../src/quick-access/expanded-command-center/shell.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/quick-access/expanded-command-center/styles.ts", import.meta.url), "utf8");

const tree=ts.createSourceFile('shell.tsx',shell,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
function nodes(predicate){const found=[];function visit(node){if(predicate(node))found.push(node);ts.forEachChild(node,visit);}visit(tree);return found;}
const dock=nodes(node=>ts.isVariableDeclaration(node)&&node.name.getText(tree)==='dockControl')[0];
const headers=nodes(node=>ts.isJsxElement(node)&&node.openingElement.tagName.getText(tree)==='header');
function headerCopy(native,nestedId,disconnectControl,synthetic){
  const dockControl=new Function('native','nestedId','disconnectControl',`return ${dock.initializer.getText(tree)}`)(native,nestedId,disconnectControl);
  const values=[];
  function visit(node){
    if(ts.isJsxExpression(node)&&node.expression&&ts.isConditionalExpression(node.expression)){
      const code=ts.transpileModule(`const result=${node.expression.getText(tree)}`,{compilerOptions:{target:ts.ScriptTarget.ES2020}}).outputText;
      values.push(new Function('dockControl','synthetic','renderDetail',code+';return result;')(dockControl,synthetic,()=>null));return;
    }
    ts.forEachChild(node,visit);
  }
  for(const header of headers)visit(header);
  return values.join(' ');
}

test("runtime wiring retains generic headers outside the guarded native disconnect detail", () => {
  assert.ok(dock?.initializer);assert.equal(headers.length,1);
  for(const [native,nestedId,control] of [[true,null,{}],[true,'manual',{}],[true,'disconnect',null],[false,'disconnect',{}]]){
    const copy=headerCopy(native,nestedId,control,false);
    assert.match(copy,/Application status/);
    assert.doesNotMatch(copy,/Disconnect trial|Keep the cable connected/);
  }
});

test("existing native disconnect trial copy remains scoped to its supplied guarded detail", () => {
  const copy=headerCopy(true,'disconnect',{},false);
  assert.match(copy,/Disconnect trial/);assert.match(copy,/Keep the cable connected/);
  assert.match(shell,/const detailContent = dockControl \? disconnectControl/);
  // Injection selects an existing control; the shared shell cannot dispatch RPCs.
  assert.doesNotMatch(shell,/from ["'][^"']*(?:backend|@decky\/api)["']/);
});

test("approved responsive geometry remains owned by UI", () => {
  assert.match(styles, /width:min\(74vw,1120px\)/);
  assert.match(styles, /@media\(max-width:900px\)\{\.rg-expanded\{width:76vw\}\}/);
  assert.match(styles, /@media\(max-width:760px\)[\s\S]*\.rg-expanded\{width:78vw\}/);
  assert.match(styles, /@media\(max-width:620px\)[\s\S]*\.rg-expanded\{width:80vw\}/);
  assert.doesNotMatch(styles, /width:min\(64vw/);
});

test("wiring does not reintroduce duplicate Quick Access copy", () => {
  assert.match(styles, /data-ec-tab=quick/);
  assert.match(styles, />h2/);
  assert.match(styles, />\.rg-expanded-context/);
  assert.match(styles, /display:none/);
});
