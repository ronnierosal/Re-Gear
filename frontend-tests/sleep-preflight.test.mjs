import assert from "node:assert/strict";
import test from "node:test";

import {
  SleepPreflightCoordinator,
  observationFromSnapshotEvidence,
  requiresPreflightBlocker,
  warningForBlockedAttempt,
} from "../src/sleep-preflight.ts";
import {
  createSteamSuspendAdapter,
  isSteamSuspendStore,
} from "../src/steam-suspend-adapter.ts";


function fresh({
  required = true,
  confidence = "verified",
  gameState = "idle",
  gameUsesEgpu = false,
} = {}) {
  return {
    kind: "fresh",
    guardRequired: required,
    guardConfidence: confidence,
    gameState,
    gameUsesEgpu,
  };
}

class FakeAdapter {
  acquireCount = 0;
  releaseCount = 0;
  observeCount = 0;
  unobserveCount = 0;
  handler = null;

  acquireBlocker() {
    this.acquireCount += 1;
    let released = false;
    return () => {
      if (!released) {
        released = true;
        this.releaseCount += 1;
      }
    };
  }

  observeSuspendRequests(handler) {
    this.observeCount += 1;
    this.handler = handler;
    let released = false;
    return () => {
      if (!released) {
        released = true;
        this.unobserveCount += 1;
      }
    };
  }

  requestSleep() {
    this.handler?.();
  }
}

test("startup acquires and patches exactly once before any snapshot", () => {
  const adapter = new FakeAdapter();
  const coordinator = new SleepPreflightCoordinator(adapter, () => {});

  const first = coordinator.start();
  const second = coordinator.start();

  assert.equal(adapter.acquireCount, 1);
  assert.equal(adapter.observeCount, 1);
  assert.equal(first.state, "active");
  assert.equal(first.reason, "loading");
  assert.deepEqual(second, first);
});

test("loading, stale, unavailable, unknown, and required states retain one blocker", () => {
  const adapter = new FakeAdapter();
  const coordinator = new SleepPreflightCoordinator(adapter, () => {});
  coordinator.start();

  for (const observation of [
    { kind: "loading" },
    { kind: "stale" },
    { kind: "unavailable" },
    fresh({ required: false, confidence: "unknown" }),
    fresh({ required: true, confidence: "verified" }),
  ]) {
    assert.equal(requiresPreflightBlocker(observation), true);
    assert.equal(coordinator.reconcile(observation).blocking, true);
  }
  assert.equal(adapter.acquireCount, 1);
  assert.equal(adapter.releaseCount, 0);
});

test("only current schema-3 evidence is classified as fresh", () => {
  const now = Date.parse("2026-08-31T05:30:00Z");
  const evidence = {
    schemaVersion: 3,
    observedAt: "2026-08-31T05:29:55Z",
    guardRequired: false,
    guardConfidence: "verified",
    gameState: "idle",
    gameUsesEgpu: false,
  };

  assert.equal(observationFromSnapshotEvidence(evidence, now, 10_000).kind, "fresh");
  assert.equal(
    observationFromSnapshotEvidence({ ...evidence, schemaVersion: 2 }, now, 10_000).kind,
    "stale",
  );
  assert.equal(
    observationFromSnapshotEvidence({ ...evidence, observedAt: "invalid" }, now, 10_000).kind,
    "stale",
  );
  assert.equal(
    observationFromSnapshotEvidence(
      { ...evidence, observedAt: "2026-08-31T05:29:40Z" },
      now,
      10_000,
    ).kind,
    "stale",
  );
});

test("only fresh verified absence releases and later uncertainty reacquires once", () => {
  const adapter = new FakeAdapter();
  const coordinator = new SleepPreflightCoordinator(adapter, () => {});
  coordinator.start();

  const absent = coordinator.reconcile(fresh({ required: false }));
  assert.equal(absent.state, "inactive");
  assert.equal(adapter.releaseCount, 1);

  coordinator.reconcile({ kind: "stale" });
  coordinator.reconcile({ kind: "unavailable" });
  assert.equal(adapter.acquireCount, 2);
  assert.equal(coordinator.status().blocking, true);
});

test("blocked attempts use game, standard, and fail-closed warning variants", () => {
  assert.equal(
    warningForBlockedAttempt(fresh({ gameState: "running", gameUsesEgpu: true })).kind,
    "game",
  );
  assert.equal(warningForBlockedAttempt(fresh()).kind, "standard");
  assert.equal(
    warningForBlockedAttempt(fresh({ gameState: "unknown" })).kind,
    "unknown",
  );
  assert.equal(warningForBlockedAttempt({ kind: "stale" }).kind, "unknown");
});

test("every blocked request emits feedback independently of passive preferences", () => {
  const adapter = new FakeAdapter();
  const warnings = [];
  const coordinator = new SleepPreflightCoordinator(adapter, (warning) => warnings.push(warning));
  coordinator.start();
  coordinator.reconcile(fresh({ gameState: "running", gameUsesEgpu: true }));

  adapter.requestSleep();
  adapter.requestSleep();

  assert.equal(warnings.length, 2);
  assert.equal(warnings[0].kind, "game");
  assert.equal(coordinator.status().blockedAttemptCount, 2);
});

test("an unavailable resolver never claims complete protection", () => {
  const coordinator = new SleepPreflightCoordinator(null, () => {});
  const status = coordinator.start();

  assert.equal(status.state, "unavailable");
  assert.equal(status.blocking, false);
  assert.match(status.error, /could not be resolved/i);
});

test("a failed native acquisition is terminal for the plugin lifecycle", () => {
  let acquireCount = 0;
  const adapter = {
    acquireBlocker() {
      acquireCount += 1;
      throw new Error("native acquire failed");
    },
    observeSuspendRequests() {
      throw new Error("must not patch without a blocker");
    },
  };
  const coordinator = new SleepPreflightCoordinator(adapter, () => {});

  assert.equal(coordinator.start().state, "unavailable");
  coordinator.reconcile({ kind: "stale" });
  coordinator.reconcile(fresh());

  assert.equal(acquireCount, 1);
  assert.match(coordinator.status().error, /acquisition failed/i);
});

test("warning-hook failure retains enforcement and reports degraded feedback", () => {
  const adapter = new FakeAdapter();
  adapter.observeSuspendRequests = () => {
    throw new Error("patch failed");
  };
  const coordinator = new SleepPreflightCoordinator(adapter, () => {});

  const status = coordinator.start();

  assert.equal(status.state, "active");
  assert.equal(status.blocking, true);
  assert.equal(status.attemptWarningAvailable, false);
  assert.match(status.error, /warning is unavailable/i);
});

test("dismount unpatches and releases exactly once", () => {
  const adapter = new FakeAdapter();
  const coordinator = new SleepPreflightCoordinator(adapter, () => {});
  coordinator.start();

  coordinator.stop();
  coordinator.stop();

  assert.equal(adapter.unobserveCount, 1);
  assert.equal(adapter.releaseCount, 1);
});

test("capability resolver rejects partial or unrelated Steam exports", () => {
  assert.equal(isSteamSuspendStore(null), false);
  assert.equal(isSteamSuspendStore({ BlockSuspendAction() {} }), false);
  assert.equal(isSteamSuspendStore({
    BlockSuspendAction() {},
    OnSuspendRequest() {},
    RequestSleep() {},
  }), true);
  assert.equal(createSteamSuspendAdapter(() => ({}), () => ({ unpatch() {} })), null);
});

test("native blocker stops the fake Steam store before suspend preparation", () => {
  let blockerCount = 1;
  let prepareCount = 0;
  const warnings = [];
  const store = {
    BlockSuspendAction() {
      blockerCount += 1;
      let released = false;
      return () => {
        if (!released) {
          released = true;
          blockerCount -= 1;
        }
      };
    },
    OnSuspendRequest() {
      if (blockerCount > 0) {
        return;
      }
      prepareCount += 1;
    },
    RequestSleep() {
      this.OnSuspendRequest();
    },
  };
  const patchBefore = (object, property, handler) => {
    const original = object[property];
    const patched = function (...args) {
      handler(args);
      return original.apply(this, args);
    };
    object[property] = patched;
    return {
      unpatch() {
        if (object[property] === patched) {
          object[property] = original;
        }
      },
    };
  };
  const adapter = createSteamSuspendAdapter(() => store, patchBefore);
  assert.ok(adapter);
  const coordinator = new SleepPreflightCoordinator(adapter, (warning) => warnings.push(warning));

  coordinator.start();
  store.RequestSleep();
  assert.equal(blockerCount, 2);
  assert.equal(prepareCount, 0);
  assert.equal(warnings.length, 1);

  coordinator.stop();
  assert.equal(blockerCount, 1, "Re-Gear must preserve an unrelated existing blocker");
});
