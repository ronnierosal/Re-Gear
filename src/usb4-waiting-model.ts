/** Pure presentation facts. No requests, device identity, or security actions. */
export const USB4_WAITING_TEXT = "An attached USB4 device is waiting for system authorization. Re-Gear cannot approve devices on this handheld. Inspect the system device prompt and verify the attached device before deciding what to do.";
export const USB4_WAITING_UNAVAILABLE = "USB4 authorization status is unverified. Re-Gear cannot approve devices on this handheld.";

export type Usb4WaitingObservation = {
  state: "none" | "unauthorized" | "authorized" | "unknown" | "ambiguous";
  noticeKey: string | null;
};

/** Produced by the index-owned direct-request lifetime, never a cache. */
export type Usb4WaitingReceipt = Readonly<{
  payload: unknown;
  requestStartedAtMs: number;
  receivedAtMs: number;
  expiresAtMs: number;
  generation: number;
  supportedLifetime: boolean;
}>;

function ownFields(value: unknown): PropertyDescriptorMap | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) return null;
  return Object.getOwnPropertyDescriptors(value);
}

function validKey(value: unknown): value is string {
  return typeof value === "string" && value.length === 35 && /^uw-[0-9a-f]{32}$/.test(value);
}

export function validUsb4WaitingReceipt(value: unknown, nowMs: number): value is Usb4WaitingReceipt {
  try {
    const fields = ownFields(value);
    const keys = ["payload", "requestStartedAtMs", "receivedAtMs", "expiresAtMs", "generation", "supportedLifetime"];
    if (!fields || !Object.isFrozen(value) || Reflect.ownKeys(value as object).length !== keys.length
      || Reflect.ownKeys(value as object).some(key => !keys.includes(key as string))
      || keys.some(key => !fields[key] || !("value" in fields[key]))) return false;
    const started = fields.requestStartedAtMs.value, received = fields.receivedAtMs.value;
    const expires = fields.expiresAtMs.value, generation = fields.generation.value;
    const snapshot = ownFields(ownFields(fields.payload.value)?.snapshot?.value);
    if (snapshot?.schema_version?.value !== 3 || typeof snapshot.observed_at?.value !== "string") return false;
    const observed = Date.parse(snapshot.observed_at.value);
    return [nowMs, started, received, expires, observed].every(n => typeof n === "number" && Number.isFinite(n))
      && received >= started && received <= nowMs && observed <= received
      && nowMs >= started && nowMs - started < 10000 && nowMs >= observed && nowMs - observed < 10000
      && expires === Math.min(started + 10000, observed + 10000) && nowMs < expires
      && Number.isInteger(generation) && generation >= 0
      && typeof fields.supportedLifetime.value === "boolean";
  } catch { return false; }
}

/** Both facts must belong to this response. Freshness/lifetime is owned by index. */
export function usb4WaitingObservation(value: unknown): Usb4WaitingObservation | null {
  try {
    const payload = ownFields(value);
    const admission = ownFields(payload?.runtime_admission?.value);
    if (admission?.schema_version?.value !== 1
      || admission.sleep_interceptor_admission?.value !== "observation-only"
      || admission.mode?.value !== "observation-only"
      || admission.mutation_allowed?.value !== false) return null;
    const waiting = payload?.usb4_waiting?.value;
    const fields = ownFields(waiting);
    if (!fields || fields.schema_version?.value !== 1
      || Reflect.ownKeys(waiting as object).length !== 3
      || Reflect.ownKeys(waiting as object).some(key => !["schema_version", "state", "notice_key"].includes(key as string))) return null;
    const state = fields.state?.value;
    const noticeKey = fields.notice_key?.value;
    if (state === "unauthorized") return validKey(noticeKey) ? { state, noticeKey } : null;
    if (["none", "authorized", "unknown", "ambiguous"].includes(state) && noticeKey === null)
      return { state, noticeKey };
    return null;
  } catch { return null; }
}

/** No eviction/reset: replayed keys cannot become new prompts in this lifetime. */
export function createUsb4WaitingMemory() {
  const shown = new Set<string>();
  return {
    claim(key: string): boolean {
      if (!validKey(key) || shown.has(key) || shown.size >= 64) return false;
      shown.add(key);
      return true;
    },
    get size() { return shown.size; },
    get saturated() { return shown.size >= 64; },
  };
}
