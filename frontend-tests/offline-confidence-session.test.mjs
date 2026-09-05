import assert from "node:assert/strict";
import test from "node:test";
import { offlineConfidenceForGame, offlineConfirmationBinding } from "../src/offline-confidence-session.ts";
import { projectOfflinePreparation } from "../src/offline-confidence.ts";
import { offlineTestMemory } from "../src/offline-test-memory.ts";
const raw = { nBuildID: 9, bHasAnyLocalContent: true, bIsSubscribedTo: true, bIsThirdPartyUpdater: false,
 eDisplayStatus: 11, eCloudStatus: 3, bCloudAvailable: true, bCloudEnabledForAccount: true, bCloudEnabledForApp: true,
 deckDerivedProperties: {requires_internet_for_singleplayer:false,requires_internet_for_setup:false} };
const report = {schema_version:1,status:"unknown",reason_codes:["install_unknown","download_state_unknown","steam_entitlement_unknown"]};
test("confirmation integrates with selection and backend gates", t => {
  const previous=globalThis.window; globalThis.window={loginStore:{m_strAccountName:"local-account"}};
  t.after(()=>{globalThis.window=previous;offlineTestMemory.forget(123)});
  const app={local_per_client_data:{installed:true},BHasStoreCategory:()=>true};
  const source={store:{GetAppOverviewByAppID:()=>app}};
  let prep=projectOfflinePreparation(raw);
  assert.equal(offlineConfidenceForGame(prep,source,123,report).status,"likely_offline_ready");
  assert.equal(offlineConfidenceForGame(prep,source,123,report,offlineConfirmationBinding(prep,source,123)).status,"tested_offline");
  const blocked={schema_version:1,status:"unknown",reason_codes:["offline_evidence_game_unknown"]};
  assert.equal(offlineConfidenceForGame(prep,source,123,blocked,offlineConfirmationBinding(prep,source,123)).canConfirm,false);
  assert.equal(offlineConfidenceForGame(prep,source,123,report).status,"likely_offline_ready");
  offlineConfidenceForGame(prep,source,123,report,offlineConfirmationBinding(prep,source,123));
  prep=projectOfflinePreparation({...raw,nBuildID:10});
  assert.equal(offlineConfidenceForGame(prep,source,123,report).status,"likely_offline_ready");
  offlineConfidenceForGame(prep,source,123,report,offlineConfirmationBinding(prep,source,123));
  window.loginStore.m_strAccountName="changed";
  assert.equal(offlineConfidenceForGame(prep,source,123,report).status,"likely_offline_ready");
});
test("missing account disables confirmation and known blocker defeats green evidence", t => {
 const previous=globalThis.window;globalThis.window={};t.after(()=>{globalThis.window=previous;offlineTestMemory.forget(123)});
 const source={store:{GetAppOverviewByAppID:()=>({local_per_client_data:{installed:true},BHasStoreCategory:()=>true})}};
 const prep=projectOfflinePreparation(raw);
 assert.equal(offlineConfidenceForGame(prep,source,123,report,offlineConfirmationBinding(prep,source,123)).status,"likely_offline_ready");
 assert.equal(offlineConfidenceForGame(prep,source,123,report,offlineConfirmationBinding(prep,source,123)).canConfirm,false);
 assert.equal(offlineConfidenceForGame(prep,source,123,{schema_version:1,status:"needs_attention",reason_codes:["update_pending"]},offlineConfirmationBinding(prep,source,123)).status,"needs_preparation");
});


test("an old displayed confirmation cannot attest a newly installed build", t => {
 const previous=globalThis.window;globalThis.window={loginStore:{m_strAccountName:"local"}};
 t.after(()=>{globalThis.window=previous;offlineTestMemory.forget(123)});
 const app={local_per_client_data:{installed:true},BHasStoreCategory:()=>true};const source={store:{GetAppOverviewByAppID:()=>app}};
 const displayed=offlineConfirmationBinding(projectOfflinePreparation(raw),source,123);
 const fresh=projectOfflinePreparation({...raw,nBuildID:10});
 assert.equal(offlineConfidenceForGame(fresh,source,123,report,displayed).status,"unverified");
 assert.equal(offlineConfidenceForGame(fresh,source,123,report).status,"likely_offline_ready");
});
