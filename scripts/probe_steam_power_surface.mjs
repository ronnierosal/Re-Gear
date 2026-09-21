#!/usr/bin/env node
// Is there a Steam shutdown hook the way there is a sleep hook? Read-only.
//
// Sleep is interceptable because the suspend store exposes BlockSuspendAction:
// a counted lease Steam itself checks in OnSuspendRequest before it begins the
// preparation sequence (docs/ADR_STEAM_SLEEP_PREFLIGHT.md). Holding it is what
// stops a sleep; the patch only explains. The open question is whether any
// equivalent exists for shutdown -- something Steam checks, and that we could
// hold while a safe disconnect runs. Without one there is nothing to hold the
// machine against, and "intercepting" shutdown would be racing a power-off.
//
// This answers that by ENUMERATION ONLY. It records member names and their
// `typeof` for stores that look power-related, and never calls one: invoking a
// discovered shutdown method on a live handheld is exactly the accident this
// file must not be able to cause. A test pins that no call syntax appears here.
//
// Usage, with an SSH tunnel to Steam's CDP port:
//   ssh -N -L 19224:127.0.0.1:8080 -i ~/.ssh/hdm_ally_deploy_v2 deck@<ally>
//   node scripts/probe_steam_power_surface.mjs http://127.0.0.1:19224

const debuggerBase = process.argv[2] ?? "http://127.0.0.1:19224";
const targets = await fetch(`${debuggerBase}/json`).then((response) => response.json());
const target = targets.find((item) => item.title === "SharedJSContext");
if (!target?.webSocketDebuggerUrl) {
  throw new Error("SharedJSContext CDP target was not found");
}

const socket = new WebSocket(target.webSocketDebuggerUrl);
const pending = new Map();
let nextId = 0;
function call(method, params = {}) {
  const id = ++nextId;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  const request = pending.get(message.id);
  if (!request) return;
  pending.delete(message.id);
  if (message.error) request.reject(new Error(message.error.message));
  else request.resolve(message.result);
});
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

// Every identifier below is a NEEDLE to match against member names. None is
// invoked. Webpack ids and minified names are ephemeral and are never stored
// in implementation -- this is evidence gathering, not a resolver.
const expression = String.raw`(() => {
  const POWER = /suspend|sleep|shutdown|poweroff|power_off|restart|reboot|halt|quit/i;
  const BLOCKER = /block|inhibit|lease|hold|prevent/i;
  const out = { suspend_store: null, power_like: [], steamclient_system: null, notes: [] };

  // What SteamClient.System advertises, names and types only.
  try {
    const system = window.SteamClient?.System;
    if (system) {
      out.steamclient_system = Object.keys(system)
        .filter((key) => POWER.test(key))
        .map((key) => key + ":" + typeof system[key]);
    }
  } catch (error) { out.notes.push("SteamClient.System unreadable"); }

  let webpackRequire;
  const chunk = window.webpackChunksteamui;
  if (!chunk?.push) { out.notes.push("webpack chunk unavailable"); return out; }
  chunk.push([[Symbol("regear-power-surface-probe")], {}, (value) => { webpackRequire = value; }]);
  if (!webpackRequire?.m) { out.notes.push("webpack require unavailable"); return out; }

  const seen = new Set();
  for (const id of Object.keys(webpackRequire.m)) {
    let loaded;
    try { loaded = webpackRequire(id); } catch { continue; }
    for (const module of [loaded?.default, loaded]) {
      if (!module || typeof module !== "object" || module === window) continue;
      let values;
      try { values = Object.values(module); } catch { continue; }
      for (const candidate of values) {
        if (!candidate || typeof candidate !== "object" || seen.has(candidate)) continue;
        let keys;
        try { keys = Object.getOwnPropertyNames(Object.getPrototypeOf(candidate) ?? {}).concat(Object.keys(candidate)); }
        catch { continue; }
        seen.add(candidate);

        // The known sleep store, by the same capability shape the adapter uses.
        if (typeof candidate.BlockSuspendAction === "function"
            && typeof candidate.OnSuspendRequest === "function"
            && typeof candidate.RequestSleep === "function") {
          out.suspend_store = keys.filter((key) => POWER.test(key) || BLOCKER.test(key))
            .map((key) => { let kind; try { kind = typeof candidate[key]; } catch { kind = "unreadable"; } return key + ":" + kind; });
          continue;
        }
        // Anything else carrying several power-shaped members is worth recording.
        const powerKeys = keys.filter((key) => POWER.test(key));
        if (powerKeys.length >= 2) {
          out.power_like.push({
            power: powerKeys.map((key) => { let kind; try { kind = typeof candidate[key]; } catch { kind = "unreadable"; } return key + ":" + kind; }),
            blockers: keys.filter((key) => BLOCKER.test(key)),
          });
        }
      }
    }
  }
  out.power_like = out.power_like.slice(0, 40);
  return out;
})()`;

const evaluation = await call("Runtime.evaluate", {
  expression,
  awaitPromise: true,
  returnByValue: true,
});
socket.close();
process.stdout.write(`${JSON.stringify(evaluation.result?.value ?? evaluation, null, 1)}\n`);
