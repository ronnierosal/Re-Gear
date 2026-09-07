#!/usr/bin/env node

const debuggerBase = process.argv[2] ?? "http://127.0.0.1:9222";
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
  if (!request) {
    return;
  }
  pending.delete(message.id);
  if (message.error) {
    request.reject(new Error(message.error.message));
  } else {
    request.resolve(message.result);
  }
});

await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

const expression = String.raw`(() => {
  const isReGear = (plugin) => plugin?.name === "Re-Gear" || plugin?.name === "Handheld Dock Mode";
  const hdmLoaded = Boolean(
    window.DeckyPluginLoader?.plugins?.some?.(
      isReGear,
    ),
  );
  const hdmDisabled = Boolean(
    window.DeckyPluginLoader?.deckyState?.publicState?.().disabledPlugins?.some?.(
      isReGear,
    ),
  );
  const reloadLocked = Boolean(window.DeckyPluginLoader?.reloadLock);
  const reloadQueueLength = window.DeckyPluginLoader?.pluginReloadQueue?.length ?? null;
  let webpackRequire;
  const chunk = window.webpackChunksteamui;
  if (!chunk?.push) {
    return { resolved: false, blockerCount: null, hdmLoaded, hdmDisabled, reloadLocked, reloadQueueLength };
  }
  chunk.push([[Symbol("hdm-read-only-probe")], {}, (value) => {
    webpackRequire = value;
  }]);
  if (!webpackRequire?.m) {
    return { resolved: false, blockerCount: null, hdmLoaded, hdmDisabled, reloadLocked, reloadQueueLength };
  }
  for (const id of Object.keys(webpackRequire.m)) {
    try {
      const loaded = webpackRequire(id);
      for (const module of [loaded?.default, loaded]) {
        if (!module || typeof module !== "object" || module === window) {
          continue;
        }
        for (const candidate of Object.values(module)) {
          if (
            candidate
            && typeof candidate === "object"
            && typeof candidate.BlockSuspendAction === "function"
            && typeof candidate.OnSuspendRequest === "function"
            && typeof candidate.RequestSleep === "function"
          ) {
            return {
              resolved: true,
              blockerCount: Number.isInteger(candidate.m_cSuspendBlockers)
                ? candidate.m_cSuspendBlockers
                : null,
              hdmLoaded,
              hdmDisabled,
              reloadLocked,
              reloadQueueLength,
            };
          }
        }
      }
    } catch {
      // Steam modules with unavailable side effects are unrelated to this probe.
    }
  }
  return { resolved: false, blockerCount: null, hdmLoaded, hdmDisabled, reloadLocked, reloadQueueLength };
})()`;

const evaluation = await call("Runtime.evaluate", {
  expression,
  awaitPromise: true,
  returnByValue: true,
});
socket.close();

const result = evaluation.result?.value;
if (!result?.resolved || !Number.isInteger(result.blockerCount)) {
  throw new Error("Steam suspend store or blocker count could not be resolved");
}
process.stdout.write(`${JSON.stringify(result)}\n`);
