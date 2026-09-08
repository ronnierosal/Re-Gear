import assert from "node:assert/strict";
import test from "node:test";
import { offlineGameChoices } from "../src/offline-native-source.ts";

test("game choices bound cache traversal and exclude remote or non-game entries", () => {
  let reads = 0;
  const source = { store: { m_mapApps: { *values() {
    while (reads < 10000) {
      reads++;
      yield { appid: reads, app_type: reads === 1 ? 2 : 1, display_name: "Game", local_per_client_data: { installed: reads !== 2 } };
    }
  } } } };
  const games = offlineGameChoices(source);
  assert.equal(reads, 257);
  assert.equal(games.length, 254);
  assert.deepEqual(games[0], { data: 3, label: "Game" });
});

test("game choices never expose metadata beyond the local identity and bounded title", () => {
  const app = { appid: 123, app_type: 1, display_name: "x".repeat(500), local_per_client_data: { installed: true }, path: "private", account: "private" };
  const source = { store: { m_mapApps: new Map([[123, app], [124, { ...app, appid: NaN }]]) } };
  assert.deepEqual(offlineGameChoices(source), [{ data: 123, label: "x".repeat(160) }]);
});
