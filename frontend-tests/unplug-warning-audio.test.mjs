import assert from "node:assert/strict";
import test from "node:test";
import { createUnplugWarningAudio, UNPLUG_ALERT_GAIN, UNPLUG_ALERT_DURATION_SECONDS } from "../src/unplug-warning-audio.ts";
import { createUnplugWarningCoordinator } from "../src/unplug-warning-coordinator.ts";

const REQUEST = "a".repeat(32), OTHER = "b".repeat(32);
function harness(options = {}) {
  const contexts = [], calls = [], timers = new Map();
  let now = 0, next = 1, fallback = 0, audio;
  const context = () => {
    options.construct?.(audio);
    if (options.missing) throw new Error("no Web Audio");
    const result = { state: options.state ?? "running", currentTime: 1,
      destination: {}, tones: [], gains: [], closed: 0,
      close() { this.closed++; return options.deferredClose ?? (options.closeFailure ? Promise.reject(new Error("close")) : Promise.resolve()); },
      createGain() {
        const gain = { values: [], connected: true, gain: {
          setValueAtTime(value, time) { gain.values.push(["set", value, time]); },
          linearRampToValueAtTime(value, time) { gain.values.push(["ramp", value, time]); },
        }, connect() {}, disconnect() { gain.connected = false; } };
        result.gains.push(gain); return gain;
      },
      createOscillator() {
        if (options.secondToneFailure && result.tones.length === 1) throw new Error("second");
        const tone = { connected: true, onended: null, starts: [], stops: [], type: "", frequency: {
          setValueAtTime(value, time) { calls.push(["frequency", value, time]); },
        }, connect() {}, disconnect() { tone.connected = false; },
        start(time) { tone.starts.push(time); },
        stop(time) { tone.stops.push(time); if (options.stopFailure && time === undefined) throw new Error("stop"); },
        end() { tone.onended?.(); },
        };
        result.tones.push(tone); return tone;
      },
    };
    contexts.push(result); return result;
  };
  audio = createUnplugWarningAudio({ createContext: context, fallback() { fallback++; } });
  const schedule = (run, delay, interval = false) => {
    const id = next++; timers.set(id, { run, at: now + delay, delay, interval }); return id;
  };
  const coordinator = createUnplugWarningCoordinator({
    schedule: (run, delay) => schedule(run, delay), cancel: id => timers.delete(id),
    repeat: (run, delay) => schedule(run, delay, true), cancelRepeat: id => timers.delete(id),
    playWarning: () => audio.play(),
  });
  coordinator.subscribe(state => audio.observe(state));
  const advance = ms => {
    const end = now + ms;
    for (;;) {
      const due = [...timers].filter(([, t]) => t.at <= end).sort((a,b) => a[1].at-b[1].at)[0];
      if (!due) break;
      const [id,t] = due; now = t.at;
      if (t.interval) t.at += t.delay; else timers.delete(id);
      t.run();
    }
    now = end;
  };
  return { audio, coordinator, contexts, calls, advance, fallback: () => fallback,
    start() { coordinator.observe({ requestId: REQUEST, deauthorized: true }); },
    alarm() { this.start(); advance(3000); },
  };
}

test("real coordinator creates no audio before three seconds, bounded two-tone graph afterward", () => {
  const h = harness(); h.start(); h.advance(2999); assert.equal(h.contexts.length, 0);
  h.advance(1); const c = h.contexts[0];
  assert.equal(c.tones.length, 2); assert.equal(h.fallback(), 0);
  assert.deepEqual(c.tones.map(t => t.starts), [[1], [1.18]]);
  assert.ok(Math.abs(c.tones[0].stops[0] - 1.12) < 1e-12);
  assert.ok(Math.abs(c.tones[1].stops[0] - (1 + UNPLUG_ALERT_DURATION_SECONDS)) < 1e-12);
  assert.equal(Math.max(...c.gains[0].values.map(v => v[1])), UNPLUG_ALERT_GAIN);
  assert.equal(h.audio.read().signal, "ready");
});
test("repeat uses constant per-alert gain, one context and no growing graph", () => {
  const h = harness(); h.alarm(); const c = h.contexts[0];
  const first = [...c.tones]; h.advance(2000);
  assert.equal(h.contexts.length, 1); assert.equal(c.tones.length, 4);
  assert.ok(first.every(t => !t.connected && t.stops.length === 2));
  assert.ok(c.gains.every(g => Math.max(...g.values.map(v => v[1])) === UNPLUG_ALERT_GAIN));
});
test("natural completion disconnects nodes without closing the reusable context", () => {
  const h = harness(); h.alarm(); const c = h.contexts[0];
  c.tones.forEach(t => t.end()); assert.ok(c.tones.every(t => !t.connected));
  assert.equal(c.closed, 0); h.advance(2000);
  assert.ok(c.tones.slice(0,2).every(t => t.stops.length === 1));
});
for (const end of ["absence", "retire", "stop", "dispose"]) {
  test(`${end} stops exact active nodes and prevents late playback`, () => {
    const h = harness(); h.alarm(); const c = h.contexts[0];
    if (end === "absence") h.coordinator.observe({ requestId: REQUEST, physicalAbsenceVerified: true });
    if (end === "retire") h.coordinator.retire(REQUEST);
    if (end === "stop") h.coordinator.stop();
    if (end === "dispose") h.audio.dispose();
    h.advance(20000); h.audio.play();
    assert.equal(c.closed, 1); assert.equal(c.tones.length, 2);
    assert.ok(c.tones.every(t => !t.connected && t.stops.length === 2));
    assert.equal(h.fallback(), 0);
  });
}
test("foreign absence or retirement cannot cancel the exact alarm", () => {
  const h = harness(); h.alarm();
  h.coordinator.observe({ requestId: OTHER, physicalAbsenceVerified: true });
  h.coordinator.retire(OTHER); h.advance(2000);
  assert.equal(h.contexts[0].closed, 0); assert.equal(h.contexts[0].tones.length, 4);
});
test("replacement request closes old audio and waits its own initial deadline", async () => {
  const h = harness(); h.alarm(); h.coordinator.observe({ requestId: OTHER, deauthorized: true });
  assert.equal(h.contexts[0].closed, 1); await Promise.resolve();
  h.advance(2999); assert.equal(h.contexts.length, 1);
  h.advance(1); assert.equal(h.contexts.length, 2); assert.equal(h.audio.read().requestId, OTHER);
});
for (const state of ["suspended", "closed", "interrupted"]) {
  test(`${state} does not resume, select a route or change device volume; falls back`, () => {
    const h = harness({state}); h.alarm();
    assert.equal(h.contexts[0].tones.length, 0); assert.equal(h.contexts[0].closed, 1);
    assert.equal(h.fallback(), 1); assert.equal(h.audio.read().signal, "unavailable");
  });
}
test("missing API preserves existing feedback and visual warning", () => {
  const h = harness({missing:true}); h.alarm(); h.advance(2000);
  assert.equal(h.fallback(), 2); assert.equal(h.coordinator.read().phase, "alarm");
});
for (const result of ["resolve", "reject"]) {
  test(`replacement cannot create a graph while prior context close is pending: ${result}`, async () => {
    let finish;
    const deferredClose = new Promise((resolve, reject) => {
      finish = result === "resolve" ? resolve : () => reject(new Error("late close"));
    });
    const h = harness({deferredClose}); h.alarm();
    h.coordinator.observe({requestId:OTHER,deauthorized:true}); h.advance(3000);
    assert.equal(h.contexts.length, 1, "replacement must not overlap unresolved old context closure");
    assert.equal(h.audio.read().cleanupPending, true);
    assert.equal(h.fallback(), 0);
    finish(); await Promise.resolve();
    assert.equal(h.audio.read().cleanupPending, false);
    h.advance(2000);
    assert.equal(h.contexts.length, result === "resolve" ? 2 : 1);
    if (result === "reject") assert.equal(h.audio.read().signal, "cleanup-unconfirmed");
  });
}
test("owner teardown during context construction closes it without playback or fallback", () => {
  const h = harness({ construct: audio => audio.dispose() }); h.alarm();
  assert.equal(h.contexts[0].closed, 1); assert.equal(h.contexts[0].tones.length, 0);
  assert.equal(h.fallback(), 0);
});
test("partial graph failure releases nodes and never doubles audio with fallback", () => {
  const h = harness({secondToneFailure:true}); h.alarm(); const c = h.contexts[0];
  assert.equal(c.closed, 1); assert.ok(c.tones.every(t => !t.connected));
  assert.equal(h.fallback(), 0); assert.equal(h.audio.read().signal, "unavailable");
});
test("failed stop is explicit cleanup uncertainty and cannot start more audio", () => {
  const h = harness({stopFailure:true}); h.alarm(); h.coordinator.retire(REQUEST);
  assert.equal(h.audio.read().signal, "cleanup-unconfirmed");
  h.coordinator.observe({requestId:OTHER,deauthorized:true}); h.advance(10000);
  assert.equal(h.contexts.length, 1); assert.equal(h.fallback(), 0);
});
test("late close failure remains truthful and prevents further playback", async () => {
  const h = harness({closeFailure:true}); h.alarm(); h.coordinator.retire(REQUEST);
  await Promise.resolve(); assert.equal(h.audio.read().signal, "cleanup-unconfirmed");
  h.coordinator.observe({requestId:OTHER,deauthorized:true}); h.advance(10000);
  assert.equal(h.contexts.length, 1);
});
test("disposed engine cannot be rearmed by remount, duplicate dispose or stale observations", () => {
  const h = harness(); h.alarm(); h.audio.dispose(); h.audio.dispose();
  h.audio.observe({phase:"alarm",requestId:OTHER}); h.audio.play();
  assert.equal(h.contexts[0].closed, 1); assert.equal(h.contexts.length, 1);
});
test("malformed request or state never creates a context", () => {
  const h = harness();
  for (const value of [null, {}, {phase:"alarm",requestId:"not-a-request"}, {phase:"cleared",requestId:REQUEST}]) {
    h.audio.observe(value); h.audio.play();
  }
  assert.equal(h.contexts.length, 0); assert.equal(h.fallback(), 0);
});
