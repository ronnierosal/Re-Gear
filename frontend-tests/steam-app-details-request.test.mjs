import assert from "node:assert/strict";
import test from "node:test";
import { requestSteamAppDetails } from "../src/steam-app-details-request.ts";

test("adapted helper handles immediate callbacks and unregisters exactly once", async () => {
  let releases = 0;
  const result = await requestSteamAppDetails(123, (id, callback) => {
    assert.equal(id, 123);
    callback({ state: "first" });
    callback({ state: "duplicate" });
    return { unregister() { releases++; } };
  });
  assert.deepEqual(result, { state: "first" });
  assert.equal(releases, 1);
});

test("abort unregisters and ignores late data", async () => {
  const controller = new AbortController();
  let callback;
  let releases = 0;
  const result = requestSteamAppDetails(123, (_, cb) => {
    callback = cb;
    return { unregister() { releases++; } };
  }, controller.signal);
  controller.abort();
  callback({ private: "late" });
  assert.equal(await result, null);
  assert.equal(releases, 1);
});

test("timeout releases a subscription that never replies", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let releases = 0;
  const result = requestSteamAppDetails(123, () => ({ unregister() { releases++; } }));
  t.mock.timers.tick(1000);
  assert.equal(await result, null);
  assert.equal(releases, 1);
});

test("cancellation during registration overrides immediate data", async () => {
  const controller = new AbortController();
  let releases = 0;
  const result = await requestSteamAppDetails(123, (_, cb) => {
    cb({ state: "early" });
    controller.abort();
    return { unregister() { releases++; } };
  }, controller.signal);
  assert.equal(result, null);
  assert.equal(releases, 1);
});

test("source or cleanup errors do not return private exception text", async () => {
  assert.equal(await requestSteamAppDetails(123, () => { throw Error("private"); }), null);
  assert.equal(await requestSteamAppDetails(123, (_, cb) => {
    cb({ state: "early" });
    throw Error("private");
  }), null);
  assert.equal(await requestSteamAppDetails(123, (_, cb) => {
    cb({ state: "early" });
    return { unregister() { throw Error("private"); } };
  }), null);
});

test("invalid identities and already cancelled checks never subscribe", async () => {
  let calls = 0;
  const subscribe = () => { calls++; return { unregister() {} }; };
  for (const id of [0, -1, NaN, 1.2, 2 ** 32, "123", true]) {
    assert.equal(await requestSteamAppDetails(id, subscribe), null);
  }
  assert.equal(await requestSteamAppDetails(123, subscribe, AbortSignal.abort()), null);
  assert.equal(calls, 0);
});
