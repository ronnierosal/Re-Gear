import type { SnapshotPayload } from "./backend";

// SteamClient.Input.ControllerInputGamepadButton, not browser Gamepad indices.
export const VIEW_BUTTON = 9;
export const Y_BUTTON = 3;
export const SAFE_DISCONNECT_HOLD_MS = 3000;
const CONTEXT_TIMEOUT_MS = 2000;

type Subscription = { unregister(): void };
export interface ControllerInputSource {
  RegisterForControllerInputMessages(callback: (controller: number, button: number, pressed: boolean) => void): Subscription;
  RegisterForControllerListChanges?(callback: (...args: unknown[]) => void): Subscription;
  RegisterForActiveControllerChanges?(callback: (...args: unknown[]) => void): Subscription;
}
type Context = { snapshot: SnapshotPayload; journal: { code: string } };
type Dependencies = {
  input?: ControllerInputSource;
  readContext(): Promise<Context>;
  isBusy(): boolean;
  confirm(portable: boolean): void;
};

export function safeDisconnectContext(context: Context): boolean {
  const value = context?.snapshot;
  const snapshot = value?.snapshot;
  const observedAt = Date.parse(snapshot?.observed_at ?? "");
  const age = Date.now() - observedAt;
  return value?.delivery_schema_version === 2 && snapshot?.schema_version === 3
    && Number.isFinite(age) && age >= -5000 && age <= 15000
    && snapshot.game_state === "idle"
    && snapshot.gamescope?.running === true
    && snapshot.support_tier === "certified"
    && snapshot.disconnect_readiness?.applicable === true
    && Array.isArray(snapshot.gpus)
    && snapshot.gpus.some(gpu => gpu.role === "external" && gpu.present === true && gpu.confidence === "verified")
    && (value.inference?.mode === "portable" || value.inference?.mode === "docked_egpu")
    && context.journal?.code === "journal.idle";
}

/** Native event listener; only opens the ordinary confirmation, never executes. */
export function startControllerSafeDisconnect(deps: Dependencies): { available: boolean; stop(): void } {
  const subscriptions: Subscription[] = [];
  const controllers = new Map<number, Set<number>>();
  const latched = new Set<number>();
  let active = false;
  let reading = false;
  let epoch = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let owner: number | undefined;
  const exact = (id: number) => {
    const buttons = controllers.get(id);
    return buttons?.size === 2 && buttons.has(VIEW_BUTTON) && buttons.has(Y_BUTTON);
  };
  const cancel = () => { epoch++; clearTimeout(timer); timer = undefined; owner = undefined; };
  const reset = () => { cancel(); controllers.clear(); latched.clear(); };
  const stop = () => {
    active = false; reset();
    for (const subscription of subscriptions.splice(0)) {
      try { subscription.unregister(); } catch { /* Disabled callbacks remain inert. */ }
    }
  };
  const readFresh = async (): Promise<Context | null> => {
    if (reading) return null;
    reading = true;
    const request = Promise.resolve().then(() => deps.readContext()).then(
      value => { reading = false; return value; },
      () => { reading = false; return null; },
    );
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([
        request,
        new Promise<null>(resolve => { timeout = setTimeout(() => resolve(null), CONTEXT_TIMEOUT_MS); }),
      ]);
    } catch { return null; }
    finally { clearTimeout(timeout); }
  };
  const valid = (id: number, token: number) => active && epoch === token && exact(id) && !deps.isBusy();
  const begin = (id: number) => {
    cancel(); owner = id;
    const token = epoch;
    const initial = readFresh();
    timer = setTimeout(() => {
      timer = undefined;
      void (async () => {
        const before = await initial;
        if (!valid(id, token) || !before || !safeDisconnectContext(before)) return;
        const after = await readFresh();
        if (!valid(id, token) || !after || !safeDisconnectContext(after)) return;
        latched.add(id);
        deps.confirm(after.snapshot.inference.mode === "portable");
      })().catch(() => { /* No retry of an uncertain delivery. */ });
    }, SAFE_DISCONNECT_HOLD_MS);
  };
  const onInput = (id: number, button: number, pressed: boolean) => {
    if (!active) return;
    if (!Number.isInteger(id) || id < 0 || id > 255 || !Number.isInteger(button)
      || button < 0 || button > 255 || typeof pressed !== "boolean") { reset(); return; }
    if (!controllers.has(id)) {
      if (!pressed) return;
      if (controllers.size >= 8) { reset(); return; }
      controllers.set(id, new Set());
    }
    const buttons = controllers.get(id)!;
    if (pressed === buttons.has(button)) return; // Ignore repeated down/up delivery.
    if (pressed) buttons.add(button); else buttons.delete(button);
    if (!exact(id) && owner === id) cancel();
    if (buttons.size === 0) { controllers.delete(id); latched.delete(id); }
    if (exact(id) && !latched.has(id) && owner === undefined && !deps.isBusy()) begin(id);
  };
  try {
    const input = deps.input;
    if (typeof input?.RegisterForControllerInputMessages !== "function") return { available: false, stop };
    // Steam builds differ: the Ally exposes active-controller notifications,
    // while other builds expose controller-list notifications. Either cancels
    // all pending holds; never substitute per-button/analog state notifications.
    const registerChanges = typeof input.RegisterForControllerListChanges === "function"
      ? input.RegisterForControllerListChanges.bind(input)
      : typeof input.RegisterForActiveControllerChanges === "function"
        ? input.RegisterForActiveControllerChanges.bind(input) : undefined;
    if (!registerChanges) return { available: false, stop };
    for (const register of [
      () => registerChanges(reset),
      () => input.RegisterForControllerInputMessages(onInput),
    ]) {
      const subscription = register();
      if (typeof subscription?.unregister !== "function") { stop(); return { available: false, stop }; }
      subscriptions.push(subscription);
    }
    active = true;
    return { available: true, stop };
  } catch { stop(); return { available: false, stop }; }
}

export function steamControllerInput(host: unknown): ControllerInputSource | undefined {
  try {
    return (host as { SteamClient?: { Input?: ControllerInputSource } })?.SteamClient?.Input;
  } catch { return undefined; }
}
