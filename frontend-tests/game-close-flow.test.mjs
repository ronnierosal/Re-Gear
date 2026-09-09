import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(
  new URL("../src/game-close-flow.ts", import.meta.url),
  "utf8",
).replace(/^import type [\s\S]*?;$/m, "");
const js = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const {
  runDisconnectWithGameClose,
  runSleepWithGameClose,
  claimPendingRelaunch,
  closeFlowMessage,
} = await import(
  "data:text/javascript;base64," + Buffer.from(js).toString("base64")
);

const outcome = (over = {}) => ({
  schema_version: 1,
  stage: "removed",
  code: "live_disconnect.removed",
  ok: true,
  released: true,
  session_disturbed: true,
  removed: ["0000:08:00.1", "0000:08:00.0"],
  restored: [],
  display_released: [98],
  display_release_code: "display_release.released",
  filter_disarmed: true,
  device_disturbed: false,
  ...over,
});

const status = (decision) => ({
  schema_version: 1,
  availability: decision === "nothing_to_close" ? "ready" : "blocked",
  code: "removal_safety.game_running",
  ready: false,
  attemptable: false,
  busy: false,
  holders: [],
  scan_complete: true,
  external_display_committed: false,
  display_release_required: false,
  game: null,
  close_prompt: { schema_version: 1, decision, code: "x", intent: "disconnect",
    may_proceed: false, progress_at_risk: false, save_known: false,
    remember_offered: false, relaunch_offered: false, relaunch_requested: false },
  last: null,
});

/** A rig that records every effect, and closes the game after N polls. */
function rig({ closesAfter = 1, disconnectOutcome = outcome(), throwOn = null } = {}) {
  const calls = [];
  let polls = 0;
  let clock = 0;
  // Stands in for the backend's durable record: written with the disconnect,
  // consumed exactly once by claiming.
  let recorded = "";
  return {
    calls,
    effects: {
      async terminateGame(appId) {
        calls.push(["terminate", appId]);
        if (throwOn === "terminate") throw new Error("no steam");
      },
      async readStatus() {
        polls += 1;
        calls.push(["status", polls]);
        if (throwOn === "status") throw new Error("unreadable");
        return status(polls >= closesAfter ? "nothing_to_close" : "confirm");
      },
      async disconnect(releaseDisplay, relaunchAppId, relaunchIntent) {
        calls.push(["disconnect", releaseDisplay, relaunchAppId, relaunchIntent]);
        if (throwOn === "disconnect") throw new Error("rpc down");
        recorded = relaunchAppId;
        return disconnectOutcome;
      },
      async suspend() {
        calls.push(["suspend"]);
        if (throwOn === "suspend") throw new Error("steam refused");
      },
      async takePendingRelaunch() {
        calls.push(["take", recorded]);
        if (throwOn === "take") throw new Error("unreadable");
        const claimed = recorded;
        recorded = "";
        return { steam_app_id: claimed, code: claimed ? "relaunch.approved" : "relaunch.nothing_recorded" };
      },
      async relaunchGame(appId) {
        calls.push(["relaunch", appId]);
        if (throwOn === "relaunch") throw new Error("cannot launch");
      },
      async rememberChoice(appId, skip, relaunch) {
        calls.push(["remember", appId, skip, relaunch]);
        if (throwOn === "remember") throw new Error("write failed");
        return { ok: true, code: "game_close.preference_stored" };
      },
      async wait(ms) {
        clock += ms;
      },
      now() {
        return clock;
      },
    },
  };
}

const request = (over = {}) => ({
  appId: "1145360",
  releaseDisplay: false,
  remember: false,
  relaunch: false,
  ...over,
});

const names = (calls) => calls.map(([name]) => name);

test("the happy path closes, waits for the backend, then disconnects", async () => {
  const r = rig();
  const result = await runDisconnectWithGameClose(request(), r.effects);

  assert.equal(result.ok, true);
  assert.equal(result.gameClosed, true);
  assert.deepEqual(names(r.calls), ["terminate", "status", "disconnect", "take"]);
});

test("nothing is removed until the backend says the game is gone", async () => {
  // Not a timer, not the terminate call returning: the status saying so.
  const r = rig({ closesAfter: 4 });
  await runDisconnectWithGameClose(request(), r.effects);

  const order = names(r.calls);
  assert.deepEqual(order.slice(0, 5), ["terminate", "status", "status", "status", "status"]);
  // Every status came first; the removal came last of the two.
  assert.ok(order.indexOf("disconnect") > order.lastIndexOf("status"));
});

test("a game that will not close stops the flow rather than escalating", async () => {
  // A game that will not exit gracefully is a game with something to lose.
  const r = rig({ closesAfter: Number.POSITIVE_INFINITY });
  const result = await runDisconnectWithGameClose(request(), r.effects);

  assert.equal(result.ok, false);
  assert.equal(result.code, "flow.game_did_not_close");
  assert.equal(result.gameClosed, false);
  assert.ok(!names(r.calls).includes("disconnect"));
  assert.match(closeFlowMessage(result), /did not close/i);
});

test("an unreadable status is never read as the game having closed", async () => {
  const r = rig({ throwOn: "status" });
  const result = await runDisconnectWithGameClose(request(), r.effects);

  assert.equal(result.code, "flow.game_did_not_close");
  assert.ok(!names(r.calls).includes("disconnect"));
});

test("a status with no prompt at all is not read as clear", async () => {
  // An older backend, or a status that could not answer. Either way, not yet.
  const calls = [];
  let clock = 0;
  const effects = {
    async terminateGame() {},
    async readStatus() {
      return { close_prompt: null };
    },
    async disconnect() {
      calls.push("disconnect");
      return outcome();
    },
    async relaunchGame() {},
    async rememberChoice() {
      return { ok: true, code: "" };
    },
    async wait(ms) {
      clock += ms;
    },
    now: () => clock,
  };
  const result = await runDisconnectWithGameClose(request(), effects);

  assert.equal(result.code, "flow.game_did_not_close");
  assert.deepEqual(calls, []);
});

test("Steam refusing the close disconnects nothing", async () => {
  const r = rig({ throwOn: "terminate" });
  const result = await runDisconnectWithGameClose(request(), r.effects);

  assert.equal(result.code, "flow.close_request_failed");
  assert.deepEqual(names(r.calls), ["terminate"]);
});

test("no game to close goes straight to the disconnect", async () => {
  const r = rig();
  const result = await runDisconnectWithGameClose(
    request({ appId: null }),
    r.effects,
  );

  assert.equal(result.ok, true);
  assert.equal(result.gameClosed, false);
  assert.deepEqual(names(r.calls), ["disconnect", "take"]);
});

test("the answer is stored before it is acted on", async () => {
  // A flow that fails halfway must not also lose the box they ticked.
  const r = rig({ throwOn: "terminate" });
  await runDisconnectWithGameClose(
    request({ remember: true, relaunch: true }),
    r.effects,
  );

  assert.deepEqual(r.calls[0], ["remember", "1145360", true, true]);
});

test("a preference that could not be written does not stop the disconnect", async () => {
  // Being asked again next time is the harmless failure.
  const r = rig({ throwOn: "remember" });
  const result = await runDisconnectWithGameClose(
    request({ remember: true }),
    r.effects,
  );

  assert.equal(result.ok, true);
});

test("no answer means no write at all", async () => {
  const r = rig();
  await runDisconnectWithGameClose(request(), r.effects);

  assert.ok(!names(r.calls).includes("remember"));
});

test("a game closed for a disconnect is reopened when asked", async () => {
  const r = rig();
  const result = await runDisconnectWithGameClose(
    request({ relaunch: true }),
    r.effects,
  );

  assert.equal(result.relaunched, true);
  assert.equal(names(r.calls).at(-1), "relaunch");
});

test("a failed disconnect still puts the game back", async () => {
  // Having closed someone's game and left them with neither the game nor the
  // disconnect is the worst outcome available here.
  const r = rig({ throwOn: "disconnect" });
  const result = await runDisconnectWithGameClose(
    request({ relaunch: true }),
    r.effects,
  );

  assert.equal(result.ok, false);
  assert.equal(result.code, "flow.disconnect_failed");
  assert.equal(result.gameClosed, true);
  assert.equal(result.relaunched, true);
});

test("a refused disconnect still puts the game back", async () => {
  const r = rig({
    disconnectOutcome: outcome({ ok: false, stage: "refused", code: "removal_safety.declined" }),
  });
  const result = await runDisconnectWithGameClose(
    request({ relaunch: true }),
    r.effects,
  );

  assert.equal(result.ok, false);
  assert.equal(result.relaunched, true);
});

test("nothing is relaunched onto a disturbed device", async () => {
  // That state needs a person; launching into it stacks a second problem on
  // the one that already needs attention.
  const r = rig({ disconnectOutcome: outcome({ device_disturbed: true, ok: false }) });
  const result = await runDisconnectWithGameClose(
    request({ relaunch: true }),
    r.effects,
  );

  assert.equal(result.attention, true);
  assert.equal(result.relaunched, false);
  assert.ok(!names(r.calls).includes("relaunch"));
  assert.match(closeFlowMessage(result), /unexpected state/i);
});

test("a game that was never closed is never launched", async () => {
  const r = rig();
  const result = await runDisconnectWithGameClose(
    request({ appId: null, relaunch: true }),
    r.effects,
  );

  assert.equal(result.relaunched, false);
  assert.ok(!names(r.calls).includes("relaunch"));
});

test("a relaunch that fails is reported, not hidden", async () => {
  const r = rig({ throwOn: "relaunch" });
  const result = await runDisconnectWithGameClose(
    request({ relaunch: true }),
    r.effects,
  );

  assert.equal(result.ok, true);
  assert.equal(result.relaunched, false);
});

test("the display approval is passed through, never assumed", async () => {
  const r = rig();
  await runDisconnectWithGameClose(
    request({ releaseDisplay: true }),
    r.effects,
  );

  assert.deepEqual(
    r.calls.find(([name]) => name === "disconnect"),
    ["disconnect", true, "", "disconnect"],
  );
});

test("every success message keeps the cable sentence", async () => {
  for (const over of [{}, { relaunch: true }, { appId: null }]) {
    const r = rig();
    const result = await runDisconnectWithGameClose(request(over), r.effects);
    const message = closeFlowMessage(result);
    assert.match(message, /Keep the cable connected/i);
    assert.doesNotMatch(message, /safe to unplug|you can unplug|remove the cable/i);
  }
});

test("an unmapped failure still says something a bug report can carry", () => {
  const message = closeFlowMessage({
    ok: false,
    code: "live_disconnect.some_future_fact",
    outcome: null,
    gameClosed: false,
    relaunched: false,
    attention: false,
  });

  assert.match(message, /live_disconnect\.some_future_fact/);
});


test("the reopen is asked for with the removal, not remembered by this panel", () => {
  // The session restart that frees the eGPU destroys this panel. A wish held
  // only in this closure dies with it.
  return (async () => {
    const r = rig();
    await runDisconnectWithGameClose(request({ relaunch: true }), r.effects);

    assert.deepEqual(
      r.calls.find(([name]) => name === "disconnect"),
      ["disconnect", false, "1145360", "disconnect"],
    );
  })();
});

test("no reopen is recorded when none was asked for", async () => {
  const r = rig();
  await runDisconnectWithGameClose(request(), r.effects);

  assert.deepEqual(
    r.calls.find(([name]) => name === "disconnect"),
    ["disconnect", false, "", "disconnect"],
  );
});

test("a reopen is never recorded for a game that did not close", async () => {
  const r = rig();
  await runDisconnectWithGameClose(
    request({ appId: null, relaunch: true }),
    r.effects,
  );

  assert.deepEqual(
    r.calls.find(([name]) => name === "disconnect"),
    ["disconnect", false, "", "disconnect"],
  );
});

test("the record is claimed exactly once, so no one launches it twice", async () => {
  const r = rig();
  const result = await runDisconnectWithGameClose(
    request({ relaunch: true }),
    r.effects,
  );

  assert.equal(result.relaunched, true);
  // The record is now empty: a panel loading afterwards gets nothing.
  assert.equal(await claimPendingRelaunch(r.effects), null);
});

test("a disturbed device does not even claim the record", async () => {
  // Leaving it to expire is better than firing it later at something that
  // still needs a person.
  const r = rig({ disconnectOutcome: outcome({ device_disturbed: true, stage: "removal_unrecoverable", ok: false }) });
  await runDisconnectWithGameClose(request({ relaunch: true }), r.effects);

  assert.ok(!names(r.calls).includes("take"));
});

test("a transport failure still puts the game back", async () => {
  // The call may have failed before the backend recorded anything. Claiming
  // first means the fallback cannot double-launch.
  const r = rig({ throwOn: "disconnect" });
  const result = await runDisconnectWithGameClose(
    request({ relaunch: true }),
    r.effects,
  );

  assert.equal(result.relaunched, true);
  assert.deepEqual(r.calls.at(-1), ["relaunch", "1145360"]);
});

test("a panel loading afterwards claims and launches what is pending", async () => {
  const launched = [];
  const appId = await claimPendingRelaunch({
    async takePendingRelaunch() {
      return { steam_app_id: "1145360", code: "relaunch.approved" };
    },
    async relaunchGame(id) {
      launched.push(id);
    },
  });

  assert.equal(appId, "1145360");
  assert.deepEqual(launched, ["1145360"]);
});

test("a panel loading with nothing pending launches nothing", async () => {
  const launched = [];
  const appId = await claimPendingRelaunch({
    async takePendingRelaunch() {
      return { steam_app_id: "", code: "relaunch.nothing_recorded" };
    },
    async relaunchGame(id) {
      launched.push(id);
    },
  });

  assert.equal(appId, null);
  assert.deepEqual(launched, []);
});

test("a refused claim launches nothing", async () => {
  // Every guard lives in the backend's decision; this must not widen them.
  const launched = [];
  const appId = await claimPendingRelaunch({
    async takePendingRelaunch() {
      return { steam_app_id: "", code: "relaunch.different_boot" };
    },
    async relaunchGame(id) {
      launched.push(id);
    },
  });

  assert.equal(appId, null);
  assert.deepEqual(launched, []);
});

test("sleeping closes the game, disconnects, then suspends in that order", async () => {
  const r = rig();
  const result = await runSleepWithGameClose(request(), r.effects);

  assert.equal(result.ok, true);
  assert.equal(result.code, "flow.slept");
  assert.deepEqual(names(r.calls), ["terminate", "status", "disconnect", "suspend"]);
});

test("nothing suspends unless the disconnect succeeded", async () => {
  // A handheld put to sleep with the eGPU still attached is the state the
  // sleep guard exists to prevent, and it wakes seconds later having closed
  // the player's game for nothing.
  const r = rig({
    disconnectOutcome: outcome({ ok: false, stage: "holders_remain", code: "removal_safety.holders_remain" }),
  });
  const result = await runSleepWithGameClose(request(), r.effects);

  assert.equal(result.ok, false);
  assert.ok(!names(r.calls).includes("suspend"));
});

test("a game that will not close never reaches the suspend", async () => {
  const r = rig({ closesAfter: Number.POSITIVE_INFINITY });
  const result = await runSleepWithGameClose(request(), r.effects);

  assert.equal(result.code, "flow.game_did_not_close");
  assert.ok(!names(r.calls).includes("suspend"));
  assert.ok(!names(r.calls).includes("disconnect"));
});

test("sleeping records the reopen against the sleep clock", async () => {
  // Which decides how it ages: a sleep is meant to be reopened when the
  // player comes back, not within five minutes of pressing sleep.
  const r = rig();
  await runSleepWithGameClose(request({ relaunch: true }), r.effects);

  assert.deepEqual(
    r.calls.find(([name]) => name === "disconnect"),
    ["disconnect", false, "1145360", "sleep"],
  );
});

test("the game is not reopened before the machine suspends", async () => {
  // Launching it seconds before the machine goes off is worse than not
  // reopening it at all. The record waits for the panel that comes up after.
  const r = rig();
  const result = await runSleepWithGameClose(request({ relaunch: true }), r.effects);

  assert.equal(result.relaunched, false);
  assert.ok(!names(r.calls).includes("relaunch"));
  assert.ok(!names(r.calls).includes("take"));
});

test("the waiting record is claimable after waking", async () => {
  const r = rig();
  await runSleepWithGameClose(request({ relaunch: true }), r.effects);

  assert.equal(await claimPendingRelaunch(r.effects), "1145360");
});

test("a suspend Steam refuses is reported, not hidden", async () => {
  const r = rig({ throwOn: "suspend" });
  const result = await runSleepWithGameClose(request(), r.effects);

  assert.equal(result.ok, false);
  assert.equal(result.code, "flow.suspend_failed");
  assert.match(closeFlowMessage(result), /did not sleep the handheld/i);
});

test("a sleep whose disconnect failed still puts the game back", async () => {
  // The player is awake with a closed game and no sleep. Reopening is the
  // only thing left that helps them.
  const r = rig({ throwOn: "disconnect" });
  const result = await runSleepWithGameClose(request({ relaunch: true }), r.effects);

  assert.equal(result.relaunched, true);
  assert.ok(!names(r.calls).includes("suspend"));
});

test("the sleep message keeps the cable sentence too", async () => {
  const r = rig();
  const result = await runSleepWithGameClose(request(), r.effects);
  const message = closeFlowMessage(result);

  assert.match(message, /Keep the cable connected/i);
  assert.doesNotMatch(message, /safe to unplug|you can unplug|remove the cable/i);
});

test("a disconnect asked for as a disconnect still reopens immediately", async () => {
  // The sleep behaviour must not leak into the ordinary path.
  const r = rig();
  const result = await runDisconnectWithGameClose(
    request({ relaunch: true }),
    r.effects,
  );

  assert.equal(result.relaunched, true);
});
