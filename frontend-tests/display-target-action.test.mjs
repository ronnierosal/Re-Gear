import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source=readFileSync(new URL("../src/quick-access/expanded-command-center/display-target-action.ts",import.meta.url),"utf8").replace(/^import .*;$/gm,"");
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {displayTargetActionTile}=await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);

test("display target describes the next destination with matching artwork",()=>{
 const handheld=displayTargetActionTile({target:"ally",available:true,reason:"Guarded handheld return"});
 assert.deepEqual([handheld.id,handheld.title,handheld.value,handheld.artworkControlId],["display-target","Switch to Handheld","Ready","handheld"]);
 const tv=displayTargetActionTile({target:"tv",available:true,reason:"Guarded TV switch"});
 assert.deepEqual([tv.id,tv.title,tv.value,tv.artworkControlId],["display-target","Switch to TV","Ready","display-target"]);
});

test("unknown and blocked display targets remain visible and unavailable",()=>{
 const unknown=displayTargetActionTile();
 assert.deepEqual([unknown.id,unknown.title,unknown.value,unknown.tone],["display-target","Display Target","Unavailable","unavailable"]);
 const blocked=displayTargetActionTile({target:"tv",available:false,reason:"Resolve the prior operation"});
 assert.equal(blocked.title,"Switch to TV");assert.equal(blocked.value,"Unavailable");assert.equal(blocked.detail,"Resolve the prior operation");
});
