import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const js=ts.transpileModule(readFileSync(new URL('../src/ui-status.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {statusAppearance:s}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
test('waiting and blockers are amber, unavailable pending are gray, only errors are red',()=>{
 assert.equal(s.blocked.color,s.waiting.color);assert.equal(s.unavailable.color,s.pending.color);
 assert.notEqual(s.blocked.color,s.error.color);assert.notEqual(s.ready.color,s.checking.color);
 assert.deepEqual(Object.entries(s).filter(([,v])=>v.motion).map(([k])=>k),['checking','switching']);
});
