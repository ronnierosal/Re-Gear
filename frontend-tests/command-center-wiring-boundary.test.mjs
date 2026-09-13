import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const shell = new TextDecoder("utf-8", {fatal:true}).decode(readFileSync(new URL("../src/quick-access/expanded-command-center/shell.tsx", import.meta.url)));
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

test("runtime wiring retains generic headers including the guarded native disconnect detail", () => {
  assert.ok(dock?.initializer);assert.equal(headers.length,1);
  for(const [native,nestedId,control] of [[true,null,{}],[true,'manual',{}],[true,'disconnect',null],[false,'disconnect',{}],[true,'disconnect',{}]]){
    const copy=headerCopy(native,nestedId,control,false);
    assert.match(copy,/Application status/);
    assert.doesNotMatch(copy,/Disconnect trial|Keep the cable connected/);
  }
});

test("native disconnect warning remains inside the supplied guarded detail", () => {
  assert.doesNotMatch(headerCopy(true,'disconnect',{},false),/Disconnect trial|Keep the cable connected/);
  const notices=nodes(node=>ts.isJsxElement(node)&&node.openingElement.tagName.getText(tree)==='CommandNotice');
  assert.equal(notices.length,1);
  const notice=notices[0];
  assert.match(notice.getText(tree),/Keep the cable connected/);
  assert.equal(notice.parent.left.getText(tree),'dockControl');
  let parent=notice.parent;let nested=false;let header=false;
  while(parent){if(ts.isJsxElement(parent)){const tag=parent.openingElement.tagName.getText(tree);if(tag==='header')header=true;if(parent.openingElement.attributes.getText(tree).includes('data-ec-detail-content'))nested=true;}parent=parent.parent;}
  assert.equal(header,false);assert.equal(nested,true);
  assert.match(shell,/const detailContent = dockControl \? disconnectControl/);
  assert.doesNotMatch(shell,/from ["'][^"']*(?:backend|@decky\/api)["']/);
});

test("approved responsive geometry remains owned by UI", () => {
  assert.match(styles, /width:min\(78vw,1120px\)/);
  assert.doesNotMatch(styles, /width:min\(64vw/);
});

test("wiring does not reintroduce duplicate Quick Access copy", () => {
  assert.match(styles, /data-ec-tab=quick/);
  assert.match(styles, />h2/);
  assert.match(styles, />\.rg-expanded-context/);
  assert.match(styles, /display:none/);
});
