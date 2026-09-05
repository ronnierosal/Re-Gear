import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import config from '../rollup.config.js';

test('every imported offline badge is embedded rather than emitted as an unpackaged SVG', async()=>{
 const badgeSource=readFileSync(new URL('../src/offline-readiness-badge.tsx',import.meta.url),'utf8');
 const imports=[...badgeSource.matchAll(/from\s+["'](\.\/assets\/offline-readiness\/[^"']+\.svg)["']/g)].map(m=>m[1]);
 assert.equal(imports.length,3);
 const plugin=config.plugins.find(p=>p?.name==='re-gear-offline-badges');
 for(const source of imports){
  const id=await plugin.resolveId(source);assert.ok(id,`Missing inline resolver: ${source}`);
  const code=await plugin.load(id);
  const uri=JSON.parse(code.slice('export default '.length,-1));
  assert.ok(uri.startsWith('data:image/svg+xml;base64,'));
  const svg=Buffer.from(uri.split(',')[1],'base64').toString('utf8');
  assert.equal(svg,readFileSync(new URL('../src/'+source.slice(2),import.meta.url),'utf8'));
  assert.match(svg,/<svg/);
 }
});
