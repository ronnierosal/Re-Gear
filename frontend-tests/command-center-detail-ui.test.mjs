import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import { runtimeDependencies } from "./presentation-dependencies.mjs";

const source=readFileSync(new URL('../src/quick-access/expanded-command-center/detail-ui.tsx',import.meta.url),'utf8');

test('nested UI primitives stay presentation-only',()=>{
  assert.deepEqual(runtimeDependencies(source),[]);
  for(const name of ['CommandDetailSurface','CommandSection','CommandStatusRow','CommandNotice','CommandActionRow','CommandValue'])
    assert.match(source,new RegExp(`export function ${name}\\b`));
});

test('presentation dependency check ignores prose but rejects runtime imports and calls',()=>{
  assert.deepEqual(runtimeDependencies('/* No backend or fetch() here. */ const label="getSnapshot";'),[]);
  for (const code of [
    'import {getSnapshot as read} from "../../backend";',
    'export {callable} from "@decky/api";',
    'const api=await import("@decky/api");',
    'const api=require("../../backend");',
    'getSnapshot();', 'api.invoke("action");', 'globalThis["fetch"]("url");',
  ]) assert.notEqual(runtimeDependencies(code).length,0,code);
});

test('nested UI exposes the shared status tone vocabulary',()=>{
  for(const tone of ['neutral','active','success','warning','error','unavailable'])
    assert.match(source,new RegExp(`\\b${tone}\\b`));
  assert.match(source,/#39d8ff/);
  assert.match(source,/#49e6b1/);
  assert.match(source,/#ffc247/);
});
