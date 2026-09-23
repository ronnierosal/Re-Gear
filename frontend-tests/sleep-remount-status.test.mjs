import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';

const native=readFileSync(new URL('../src/quick-access/expanded-command-center/native.tsx',import.meta.url),'utf8');
const control=readFileSync(new URL('../src/whole-dock-control.tsx',import.meta.url),'utf8');

test('remount recovery is status-only and cannot replay a dock mutation',()=>{
  const recovery=native.slice(native.indexOf('  function resumePendingOperation(){'),native.indexOf('  function disconnect('));
  assert.match(native,/parsePendingRecord/);
  assert.match(recovery,/<WholeDockControl intent=\{intent\} readCurrentSnapshot=\{readCurrentSnapshot\} statusOnly\/>/);
  assert.doesNotMatch(recovery,/startRequest=/);
  assert.match(control,/!startRequest && !statusOnly/);
});
