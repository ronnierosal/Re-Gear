import type { UtilityId } from "./utility-layout";
import type { UtilityReading } from "./utility-rail";

type Subscription = { unregister(): void };
type Device = { id: number; bHasOutput: boolean; flOutputVolume: number };
type Devices = { activeOutputDeviceId: number; vecDevices: Device[] };
export type UtilitySystem = {
  Display?: {
    RegisterForBrightnessChanges(callback: (state: { flBrightness: number }) => void): Subscription;
    SetBrightness(value: number): unknown;
  };
  Audio?: {
    GetDevices(): Promise<Devices>;
    SetDeviceVolume(id: number, direction: number, value: number): Promise<{ result: number }>;
    RegisterForDeviceVolumeChanged(callback: (...args: unknown[]) => void): Subscription;
    RegisterForDeviceAdded(callback: (...args: unknown[]) => void): Subscription;
    RegisterForDeviceRemoved(callback: (...args: unknown[]) => void): Subscription;
    RegisterForServiceConnectionStateChanges(callback: (...args: unknown[]) => void): Subscription;
  };
};
export type UtilityReadings = Partial<Record<UtilityId, UtilityReading>>;
const unknown = (): UtilityReading => ({ available: false, value: "Unavailable" });
const normalized = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
const reading = (value: number): UtilityReading => ({ available: true, percent: Math.round(value * 100), value: `${Math.round(value * 100)}%` });

/** Steam's legacy System.Audio uses AllOutput=1 and normalized 0..1 volumes.
 * Contract evidence: SteamTracking af2c67ec, chunk~2dcc5aaf7.js lines 88611,
 * 517134, 517188 and 517678; Display lines 522048 and 522159. No optimistic
 * hardware success, timer, backend mutation, or persisted output-device ID.
 */
export function createNativeUtilities(system: UtilitySystem) {
  let state: UtilityReadings = { brightness: unknown(), volume: unknown() };
  let generation = 0;
  let active = false;
  let audioRevision = 0;
  let subscriptions: Subscription[] = [];
  const listeners = new Set<() => void>();
  const publish = (id: "brightness" | "volume", value: UtilityReading) => {
    state = { ...state, [id]: value };
    listeners.forEach(listener => listener());
  };
  const current = (token: number) => active && generation === token;
  const output = (devices: Devices) => {
    const device = devices?.vecDevices?.find(item => item.id === devices.activeOutputDeviceId && item.bHasOutput);
    return device && Number.isInteger(device.id) && normalized(device.flOutputVolume) ? device : undefined;
  };
  async function refreshAudio() {
    const token = generation, revision = ++audioRevision;
    try {
      const devices = await system.Audio!.GetDevices();
      if (!current(token) || revision !== audioRevision) return;
      const device = output(devices);
      publish("volume", device ? reading(device.flOutputVolume) : unknown());
    } catch { if (current(token) && revision === audioRevision) publish("volume", unknown()); }
  }
  function stop() {
    active = false; generation++; audioRevision++;
    const old = subscriptions; subscriptions = [];
    for (const subscription of old) { try { subscription.unregister(); } catch { /* Continue cleanup of independent subscriptions. */ } }
    state = { brightness: unknown(), volume: unknown() };
    listeners.forEach(listener => listener());
  }
  function start() {
    if (active) return;
    active = true;
    const token = ++generation;
    const display = system.Display;
    if (typeof display?.SetBrightness === "function" && typeof display.RegisterForBrightnessChanges === "function") {
      try {
        subscriptions.push(display.RegisterForBrightnessChanges(value => {
          if (current(token)) publish("brightness", normalized(value?.flBrightness) ? reading(value.flBrightness) : unknown());
        }));
      } catch { publish("brightness", unknown()); }
    }
    const audio = system.Audio;
    if (typeof audio?.GetDevices === "function" && typeof audio.SetDeviceVolume === "function") {
      for (const method of ["RegisterForDeviceVolumeChanged", "RegisterForDeviceAdded", "RegisterForDeviceRemoved", "RegisterForServiceConnectionStateChanges"] as const) {
        if (typeof audio[method] === "function") {
          try { subscriptions.push(audio[method](() => { if (current(token)) void refreshAudio(); })); } catch { /* Explicit requests still resolve the current output afresh. */ }
        }
      }
      void refreshAudio();
    }
  }
  async function request(id: UtilityId, percent?: number) {
    if (!active || (id !== "brightness" && id !== "volume") || !state[id]?.available || typeof percent !== "number" || !Number.isFinite(percent) || percent < 0 || percent > 100) throw new Error("Control unavailable");
    const token = generation;
    if (id === "brightness") {
      await system.Display!.SetBrightness(percent / 100);
      // Only the native observation publishes the applied brightness.
      return;
    }
    // Resolve the current route for every explicit request, including after a
    // Bluetooth/headphone/HDMI change. Never write the cached device from open.
    const device = output(await system.Audio!.GetDevices());
    if (!current(token) || !device) throw new Error("Audio output unavailable");
    const result = await system.Audio!.SetDeviceVolume(device.id, 1, percent / 100);
    if (!current(token)) return;
    if (result?.result !== 1) throw new Error("Volume change refused");
    await refreshAudio();
  }
  return { start, stop, request, read: () => state, subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; } };
}
