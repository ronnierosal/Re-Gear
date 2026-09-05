import assert from "node:assert/strict";
import test from "node:test";
import { projectOfflinePreparation, assessOfflineConfidence } from "../src/offline-confidence.ts";

const complete = () => ({ nBuildID: 123, bHasAnyLocalContent: true, bIsSubscribedTo: true,
  bIsThirdPartyUpdater: false, eDisplayStatus: 11, eCloudStatus: 3,
  bCloudAvailable: true, bCloudEnabledForAccount: true, bCloudEnabledForApp: true,
  deckDerivedProperties: { requires_internet_for_singleplayer: false, requires_internet_for_setup: false } });
const assess = (raw = complete(), installed = true, tested = false) =>
  assessOfflineConfidence(projectOfflinePreparation(raw), installed, tested, true);

test("projection rejects missing and malformed facts without converting them to false", () => {
  for (const value of [null, undefined, [], "game", 1])
    assert.ok(Object.values(projectOfflinePreparation(value)).every(v => v === null));
  const raw = complete();
  for (const key of Object.keys(raw).filter(key => key.startsWith("b"))) raw[key] = "false";
  raw.nBuildID = "123"; raw.eDisplayStatus = true; raw.eCloudStatus = NaN;
  raw.deckDerivedProperties = { requires_internet_for_singleplayer: 0, requires_internet_for_setup: "false" };
  assert.ok(Object.values(projectOfflinePreparation(raw)).every(v => v === null));
  for (const build of [0, -1, 1.5, Infinity, Number.MAX_SAFE_INTEGER + 1])
    assert.equal(projectOfflinePreparation({ nBuildID: build }).buildId, null);
});

test("projection copies only allowlisted scalar evidence and no private identity", () => {
  const raw = { ...complete(), appid: 123, steamid: "secret", path: "/secret", name: "private",
    deckDerivedProperties: { ...complete().deckDerivedProperties, account: "secret" } };
  const projected = projectOfflinePreparation(raw);
  assert.equal(Object.keys(projected).length, 11);
  assert.equal(JSON.stringify(projected).includes("secret"), false);
  raw.deckDerivedProperties.requires_internet_for_setup = true;
  assert.equal(projected.internetSetup, false);
});

test("likely offline-ready requires every independent preparation and compatibility fact", () => {
  assert.equal(assess().status, "likely_offline_ready");
  for (const key of Object.keys(complete())) {
    const raw = complete(); delete raw[key];
    assert.equal(assess(raw).status, "unverified", key);
  }
  for (const installed of [false, undefined, null, "true", 1])
    assert.notEqual(assessOfflineConfidence(projectOfflinePreparation(complete()), installed).status, "likely_offline_ready");
});

test("all recognized negative facts override even a prior offline confirmation", () => {
  const changes = [
    { bHasAnyLocalContent: false }, { bIsSubscribedTo: false }, { bIsThirdPartyUpdater: true },
    ...[3, 6, 7, 9, 10, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 34, 35, 38, 39].map(eDisplayStatus => ({ eDisplayStatus })),
    ...[4, 5, 6, 7, 8, 9, 10].map(eCloudStatus => ({ eCloudStatus })),
    ...["requires_internet_for_singleplayer", "requires_internet_for_setup"].map(key => ({
      deckDerivedProperties: { ...complete().deckDerivedProperties, [key]: true },
    })),
  ];
  for (const change of changes) {
    const result = assess({ ...complete(), ...change }, true, true);
    assert.equal(result.status, "needs_preparation", JSON.stringify(change));
    assert.equal(result.canConfirm, false);
    assert.ok(result.reasons.length);
  }
  assert.equal(assess(complete(), false, true).status, "needs_preparation");
});

test("unknown compatibility permits user confirmation only after complete preparation", () => {
  const raw = complete(); delete raw.deckDerivedProperties; delete raw.bIsThirdPartyUpdater;
  assert.equal(assess(raw).status, "unverified");
  assert.equal(assess(raw).canConfirm, true);
  assert.equal(assess(raw, true, true).status, "tested_offline");
  for (const key of ["nBuildID", "bHasAnyLocalContent", "bIsSubscribedTo", "eDisplayStatus", "eCloudStatus", "bCloudAvailable", "bCloudEnabledForAccount", "bCloudEnabledForApp"]) {
    const incomplete = { ...raw }; delete incomplete[key];
    assert.equal(assess(incomplete, true, true).status, "unverified", key);
    assert.equal(assess(incomplete).canConfirm, false, key);
  }
  assert.equal(assess(complete(), true, "true").status, "likely_offline_ready");
});

test("explicit disabled or unavailable cloud is usable but never masks known cloud problems", () => {
  for (const key of ["bCloudAvailable", "bCloudEnabledForAccount", "bCloudEnabledForApp"]) {
    const raw = complete(); raw[key] = false; delete raw.eCloudStatus;
    assert.equal(assess(raw).status, "likely_offline_ready");
    assert.match(assess(raw).reasons.join(" "), /does not verify save freshness/);
    raw.eCloudStatus = 9;
    assert.equal(assess(raw, true, true).status, "needs_preparation");
  }
});

test("unrecognized display and cloud states fail closed and explanatory text limits claims", () => {
  for (const change of [{ eDisplayStatus: 999 }, { eCloudStatus: 999 }]) {
    assert.equal(assess({ ...complete(), ...change }, true, true).status, "unverified");
    assert.equal(assess({ ...complete(), ...change }).canConfirm, false);
  }
  assert.match(assess().reasons.join(" "), /file integrity is not verified/);
  assert.match(assess().reasons.join(" "), /authorization is not guaranteed/);
  assert.match(assess(complete(), true, true).reasons.join(" "), /does not guarantee/);
});


test("single-player category is required for likely, not enough on its own", () => {
  const prep = projectOfflinePreparation(complete());
  for (const category of [false, null, undefined, 1])
    assert.equal(assessOfflineConfidence(prep, true, false, category).status, "unverified");
  assert.equal(assessOfflineConfidence(projectOfflinePreparation({}), true, false, true).status, "unverified");
});
