import type { UnplugWarningState } from "./unplug-warning-coordinator";

/** Per-alert signal gain, NOT device volume or an acoustic safety threshold.
 * Native audibility, output route and autoplay support require separate proof.
 * No resume(), setSinkId(), device-volume access or automatic gain increase. */
export const UNPLUG_ALERT_GAIN = 0.12;
export const UNPLUG_ALERT_DURATION_SECONDS = 0.30;

type AudioPorts = {
  createContext: () => AudioContext;
  fallback: () => void;
};
type Signal = "idle" | "ready" | "unavailable" | "cleanup-unconfirmed";
type Graph = { gain: GainNode; tones: OscillatorNode[]; started: Set<OscillatorNode>; ended: Set<OscillatorNode> };
const REQUEST = /^[0-9a-f]{32}$/;

export function createUnplugWarningAudio(ports: AudioPorts) {
  let state: UnplugWarningState = { phase: "idle", requestId: null };
  let context: AudioContext | null = null;
  let graph: Graph | null = null;
  let generation = 0;
  let disposed = false;
  let signal: Signal = "idle";
  let cleanupFailed = false;
  let pendingCloses = 0;

  const failedCleanup = () => { cleanupFailed = true; signal = "cleanup-unconfirmed"; };
  const removeGraph = (current: Graph, stop: boolean) => {
    if (graph === current) graph = null;
    for (const tone of current.tones) {
      tone.onended = null;
      if (stop && current.started.has(tone) && !current.ended.has(tone)) {
        try { tone.stop(); } catch { failedCleanup(); }
      }
      try { tone.disconnect(); } catch { failedCleanup(); }
    }
    try { current.gain.disconnect(); } catch { failedCleanup(); }
  };
  const closeContext = (current: AudioContext) => {
    pendingCloses++;
    try {
      void current.close().then(
        () => { pendingCloses--; },
        () => { pendingCloses--; failedCleanup(); },
      );
    } catch { pendingCloses--; failedCleanup(); }
  };
  const clear = () => {
    const oldContext = context;
    context = null;
    if (graph) removeGraph(graph, true);
    if (oldContext) closeContext(oldContext);
  };
  const current = (token: number, request: string | null) => !disposed
    && generation === token && state.phase === "alarm" && state.requestId === request;
  const fallback = (token: number, request: string | null) => {
    if (!current(token, request) || cleanupFailed) return;
    signal = "unavailable";
    try { ports.fallback(); } catch { /* visual warning and coordinator survive */ }
  };

  return {
    observe(next: UnplugWarningState) {
      if (disposed) return;
      const valid = (next?.phase === "prompt" || next?.phase === "alarm")
        && typeof next.requestId === "string" && REQUEST.test(next.requestId);
      const accepted: UnplugWarningState = valid ? next : { phase: "idle", requestId: null };
      if (state.requestId !== accepted.requestId
          || (state.phase === "alarm" && accepted.phase !== "alarm")
          || !valid) {
        generation++;
        clear();
      }
      state = { ...accepted };
      if (!valid && !cleanupFailed) signal = "idle";
    },
    play() {
      const token = generation;
      const request = state.requestId;
      if (!current(token, request) || cleanupFailed || pendingCloses !== 0) return;
      let started = false;
      try {
        if (!context) {
          const created = ports.createContext();
          // Construction can synchronously trigger owner teardown in a host.
          if (!current(token, request)) { closeContext(created); return; }
          context = created;
        }
        const audio = context;
        if (audio.state !== "running" || !Number.isFinite(audio.currentTime)
            || audio.currentTime < 0) {
          clear(); fallback(token, request); return;
        }
        if (graph) removeGraph(graph, true);
        if (cleanupFailed) return;
        const at = audio.currentTime;
        const gain = audio.createGain();
        graph = { gain, tones: [], started: new Set(), ended: new Set() };
        const active = graph;
        gain.gain.setValueAtTime(0, at);
        gain.connect(audio.destination);
        for (const [offset, frequency] of [[0, 880], [0.18, 1174]] as const) {
          const tone = audio.createOscillator();
          active.tones.push(tone);
          tone.type = "sine";
          tone.frequency.setValueAtTime(frequency, at);
          tone.connect(gain);
          const begin = at + offset;
          gain.gain.setValueAtTime(0, begin);
          gain.gain.linearRampToValueAtTime(UNPLUG_ALERT_GAIN, begin + 0.01);
          gain.gain.setValueAtTime(UNPLUG_ALERT_GAIN, begin + 0.10);
          gain.gain.linearRampToValueAtTime(0, begin + 0.12);
          tone.onended = () => {
            active.ended.add(tone);
            if (active.ended.size === 2 && graph === active) removeGraph(active, false);
          };
          if (!current(token, request)) { clear(); return; }
          tone.start(begin);
          active.started.add(tone);
          started = true;
          tone.stop(begin + 0.12);
        }
        if (current(token, request)) signal = "ready"; // not evidence of audible output
      } catch {
        clear();
        // A partially submitted graph must never add a second fallback sound.
        if (!started) fallback(token, request);
        else if (!cleanupFailed) signal = "unavailable";
      }
    },
    read: () => ({ signal, requestId: state.requestId, cleanupPending: pendingCloses !== 0 }),
    dispose() {
      if (disposed) return;
      disposed = true;
      generation++;
      state = { phase: "idle", requestId: null };
      clear();
      if (!cleanupFailed) signal = "idle";
    },
  };
}
