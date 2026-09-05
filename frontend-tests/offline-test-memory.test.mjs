import assert from "node:assert/strict";
import test from "node:test";
import { OfflineTestMemory } from "../src/offline-test-memory.ts";
const binding = () => ({ appId: 123, buildId: 9, account: "local-scope", store: {}, app: {} });
test("offline test memory invalidates on build, account, object or age changes", () => {
  let now = 100; const memory = new OfflineTestMemory(() => now); const b = binding();
  for (const change of [{buildId:10}, {account:"another"}, {store:{}}, {app:{}}]) {
    memory.confirm(b); assert.equal(memory.has(b),true); assert.equal(memory.has({...b,...change}),false); assert.equal(memory.has(b),false);
  }
  memory.confirm(b); now += 86400000; assert.equal(memory.has(b),false);
  memory.confirm(b); now--; assert.equal(memory.has(b),false);
});
test("confirmations are bounded and never survive a new memory instance", () => {
  const memory = new OfflineTestMemory(); const b=binding(); memory.confirm(b);
  assert.equal(new OfflineTestMemory().has(b),false);
  for(let id=1;id<=33;id++) memory.confirm({...b,appId:id});
  assert.equal(memory.has({...b,appId:1}),false);
  memory.forget(33); assert.equal(memory.has({...b,appId:33}),false);
});
