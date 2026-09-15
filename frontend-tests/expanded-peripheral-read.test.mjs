import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../src/index.tsx',import.meta.url),'utf8');
const start=source.indexOf('let nextPeripheral = optionalDiagnostics.peripheralStatus;');
const end=source.indexOf('const presentationPayload =',start);
assert.ok(start>=0&&end>start,'expanded peripheral read block is missing');
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
const read=new AsyncFunction('optionalDiagnostics','expandedVisible','quickAccessVisible','diagnosticsOnScreen','nextPayload','readPeripheral','isCurrentOwner = () => true',source.slice(start,end)+'return nextPeripheral;');
const payload=game_state=>({snapshot:{game_state}});

test('expanded peripheral read never contaminates skipped diagnostics defaults',async()=>{
  const empty=Object.freeze({peripheralStatus:null});
  const current={controller:{external_connected:true}};let calls=0;
  const fetch=async()=>{calls++;return current;};
  assert.equal(await read(empty,true,false,{current:false},payload('idle'),fetch),current);
  assert.equal(empty.peripheralStatus,null);
  assert.equal(await read(empty,false,false,{current:false},payload('idle'),fetch),null);
  assert.equal(await read(empty,true,false,{current:false},payload('running'),fetch),null);
  assert.equal(await read(empty,true,false,{current:false},payload('unknown'),fetch),null);
  assert.equal(calls,1);
  assert.match(source,/setPeripheralStatus\(nextPeripheral\)/);
});

test('expanded peripheral read reuses observed diagnostics and clears a failed own read',async()=>{
  const current={controller:{builtin_available:true}};let calls=0;
  const fail=async()=>{calls++;throw Error('unavailable');};
  const observed=Object.freeze({peripheralStatus:current});
  assert.equal(await read(observed,true,true,{current:true},payload('idle'),fail),current);
  assert.equal(calls,0);
  assert.equal(await read(observed,true,false,{current:false},payload('idle'),fail),null);
  assert.equal(observed.peripheralStatus,current);
  assert.equal(calls,1);
});
