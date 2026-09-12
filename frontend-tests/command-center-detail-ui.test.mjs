import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";

const source=readFileSync(new URL('../src/quick-access/expanded-command-center/detail-ui.tsx',import.meta.url),'utf8');

test('nested UI primitives stay presentation-only',()=>{
  assert.doesNotMatch(source,/backend|@decky\/api|getSnapshot|invoke|fetch\(/);
  for(const name of ['CommandDetailSurface','CommandSection','CommandStatusRow','CommandNotice','CommandActionRow','CommandValue'])
    assert.match(source,new RegExp(`export function ${name}\\b`));
});

test('nested UI exposes the shared status tone vocabulary',()=>{
  for(const tone of ['neutral','active','success','warning','error','unavailable'])
    assert.match(source,new RegExp(`\\b${tone}\\b`));
  assert.match(source,/#39d8ff/);
  assert.match(source,/#49e6b1/);
  assert.match(source,/#ffc247/);
});
