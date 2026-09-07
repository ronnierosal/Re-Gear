import assert from "node:assert/strict";
import test from "node:test";
import { OfflineDetailsSession, minimizeOfflineDetails } from "../src/offline-details-session.ts";

test("reader boundary excludes identities and malformed evidence", () => {
  assert.deepEqual(minimizeOfflineDetails({ appid: 123, name: "private", path: "private", eDisplayStatus: 19, eCloudStatus: "3", bCloudAvailable: true }), { eDisplayStatus: 19, bCloudAvailable: true });
  assert.equal(minimizeOfflineDetails([]), null);
});

test("non-idle context never subscribes and context change rejects a reply", async () => {
  const session = new OfflineDetailsSession();
  let calls = 0;
  let callback;
  let releases = 0;
  const subscribe = (_, cb) => { calls++; callback = cb; return { unregister() { releases++; } }; };
  assert.equal(await session.request(123, subscribe, () => false), null);
  assert.equal(calls, 0);
  const request = session.request(123, subscribe, () => true);
  session.invalidate();
  callback({ eDisplayStatus: 19 });
  assert.equal(await request, null);
  assert.equal(releases, 1);
});

test("result expires and is invalid after game starts or the view changes", async () => {
  const session = new OfflineDetailsSession();
  let clock = 0;
  let idle = true;
  const subscribe = (_, cb) => { cb({ eDisplayStatus: 19 }); return { unregister() {} }; };
  const result = await session.request(123, subscribe, () => idle, () => clock);
  assert.equal(result.isValid(), true);
  idle = false;
  assert.equal(result.isValid(), false);
  idle = true;
  assert.equal(result.isValid(), false);
  clock = 1000;
  assert.equal(result.isValid(), false);
  clock = -1;
  assert.equal(result.isValid(), false);
  clock = 0;
  session.invalidate();
  assert.equal(result.isValid(), false);
});

test("a newer request cancels the previous lease", async () => {
  const session = new OfflineDetailsSession();
  let releases = 0;
  const first = session.request(123, () => ({ unregister() { releases++; } }), () => true);
  const second = session.request(456, (_, cb) => { cb({ eDisplayStatus: 19 }); return { unregister() { releases++; } }; }, () => true);
  assert.equal(await first, null);
  assert.deepEqual((await second).details, { eDisplayStatus: 19 });
  assert.equal(releases, 2);
});
