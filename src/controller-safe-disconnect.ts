import type { SnapshotPayload } from "./backend";

// SteamClient.Input.ControllerInputGamepadButton, not browser Gamepad indices.
// Only these two indices are established. Do not add a button here from the
// order of the enum or from a browser gamepad mapping: a wrong index binds a
// shortcut to whatever button that number happens to be.
export const VIEW_BUTTON = 9;
export const Y_BUTTON = 3;
export const SAFE_DISCONNECT_HOLD_MS = 3000;
const CONTEXT_TIMEOUT_MS = 2000;
const MAX_BUTTON_CODE = 255;

/** Player-facing actions a chord may select. Delivery is separate: see deliverableActions. */
export type ShortcutAction = "display_switch" | "egpu_safe_disconnect";

export type ShortcutBinding = {
  readonly buttons: readonly number[];
  readonly action: ShortcutAction;
  readonly holdMs?: number;
};

export type RefusedBinding = { readonly binding: ShortcutBinding; readonly code: string };

/** The one action this listener performs today; the other has no runtime yet. */
export const DELIVERABLE_ACTIONS: readonly ShortcutAction[] = ["display_switch"];

/** Back/View + Y, the chord with delivered behavior. Extra chords are configuration. */
export const DEFAULT_SHORTCUT_BINDINGS: readonly ShortcutBinding[] = [
  { buttons: [VIEW_BUTTON, Y_BUTTON], action: "display_switch" },
];

export type WatchedBinding = { readonly buttons: readonly number[]; readonly action: ShortcutAction; readonly holdMs: number };

/**
 * Split configured chords into the ones worth watching and the refused ones.
 * Mirrors backend/hdm/domain/controller_shortcut_bindings.py: a single-button
 * chord fires during ordinary play, duplicates are ambiguous so the first wins,
 * and a chord for an action nothing delivers is refused rather than watched and
 * silently dropped at the end of a three second hold.
 */
export function planShortcutBindings(
  bindings: readonly ShortcutBinding[],
  deliverable: readonly ShortcutAction[] = DELIVERABLE_ACTIONS,
): { watched: WatchedBinding[]; refused: RefusedBinding[] } {
  const watched: WatchedBinding[] = [];
  const refused: RefusedBinding[] = [];
  const seen = new Set<string>();
  for (const binding of bindings) {
    const buttons = binding?.buttons;
    const holdMs = binding?.holdMs ?? SAFE_DISCONNECT_HOLD_MS;
    const codes = Array.isArray(buttons) ? [...new Set(buttons)] : [];
    const key = [...codes].sort((left, right) => left - right).join("+");
    const code = !Array.isArray(buttons)
      || codes.some(value => !Number.isInteger(value) || value < 0 || value > MAX_BUTTON_CODE)
      ? "controller_binding.invalid_button"
      : codes.length < 2 ? "controller_binding.single_button_chord"
      : !Number.isFinite(holdMs) || holdMs < 500 || holdMs > 10000 ? "controller_binding.hold_out_of_range"
      : seen.has(key) ? "controller_binding.duplicate_chord"
      : !deliverable.includes(binding.action) ? "controller_binding.action_not_deliverable"
      : "";
    if (code) { refused.push({ binding, code }); continue; }
    seen.add(key);
    watched.push({ buttons: codes, action: binding.action, holdMs });
  }
  return { watched, refused };
}

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
  confirm(target: "tv" | "ally"): void;
  /** Configured chords. Omitted means the shipped Back/View + Y default. */
  bindings?: readonly ShortcutBinding[];
  /** Actions this host can actually perform; anything else is refused, never watched. */
  deliverableActions?: readonly ShortcutAction[];
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
    && (value.inference?.mode === "portable" || value.inference?.mode === "tv_docked")
    && context.journal?.code === "journal.idle";
}

/** Native event listener; only opens the ordinary confirmation, never executes. */
export function startControllerSafeDisconnect(deps: Dependencies): {
  available: boolean;
  watching: readonly WatchedBinding[];
  refused: readonly RefusedBinding[];
  stop(): void;
} {
  const subscriptions: Subscription[] = [];
  const controllers = new Map<number, Set<number>>();
  const latched = new Set<number>();
  const { watched, refused } = planShortcutBindings(
    deps.bindings ?? DEFAULT_SHORTCUT_BINDINGS,
    deps.deliverableActions ?? DELIVERABLE_ACTIONS,
  );
  let active = false;
  let reading = false;
  let epoch = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let owner: number | undefined;
  let held: WatchedBinding | undefined;
  /** The one chord whose buttons are exactly what this controller holds now. */
  const match = (id: number): WatchedBinding | undefined => {
    const buttons = controllers.get(id);
    if (!buttons) return undefined;
    return watched.find(binding =>
      binding.buttons.length === buttons.size && binding.buttons.every(code => buttons.has(code)));
  };
  const cancel = () => { epoch++; clearTimeout(timer); timer = undefined; owner = undefined; held = undefined; };
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
  // The held chord must still be the matched one. Comparing against the exact
  // binding, not merely "some chord matches", is what stops a longer chord from
  // inheriting a hold already running for a shorter one it contains.
  const valid = (id: number, token: number, binding: WatchedBinding) =>
    active && epoch === token && match(id) === binding && !deps.isBusy();
  const begin = (id: number, binding: WatchedBinding) => {
    cancel(); owner = id; held = binding;
    const token = epoch;
    const initial = readFresh();
    timer = setTimeout(() => {
      timer = undefined;
      void (async () => {
        const before = await initial;
        if (!valid(id, token, binding) || !before || !safeDisconnectContext(before)) return;
        const after = await readFresh();
        if (!valid(id, token, binding) || !after || !safeDisconnectContext(after)) return;
        if (before.snapshot.inference.mode !== after.snapshot.inference.mode) return;
        if (binding.action !== "display_switch") return; // Nothing else is delivered.
        latched.add(id);
        deps.confirm(after.snapshot.inference.mode === "portable" ? "tv" : "ally");
      })().catch(() => { /* No retry of an uncertain delivery. */ });
    }, binding.holdMs);
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
    if (owner === id && match(id) !== held) cancel();
    if (buttons.size === 0) { controllers.delete(id); latched.delete(id); }
    const current = match(id);
    if (current && !latched.has(id) && owner === undefined && !deps.isBusy()) begin(id, current);
  };
  const unavailable = { available: false as const, watching: watched, refused, stop };
  try {
    const input = deps.input;
    // Registering input callbacks with nothing to watch would leave a listener
    // that can never act, so refuse before subscribing rather than after.
    if (!watched.length) return unavailable;
    if (typeof input?.RegisterForControllerInputMessages !== "function") return unavailable;
    // Steam builds differ: the Ally exposes active-controller notifications,
    // while other builds expose controller-list notifications. Either cancels
    // all pending holds; never substitute per-button/analog state notifications.
    const registerChanges = typeof input.RegisterForControllerListChanges === "function"
      ? input.RegisterForControllerListChanges.bind(input)
      : typeof input.RegisterForActiveControllerChanges === "function"
        ? input.RegisterForActiveControllerChanges.bind(input) : undefined;
    if (!registerChanges) return unavailable;
    for (const register of [
      () => registerChanges(reset),
      () => input.RegisterForControllerInputMessages(onInput),
    ]) {
      const subscription = register();
      if (typeof subscription?.unregister !== "function") { stop(); return unavailable; }
      subscriptions.push(subscription);
    }
    active = true;
    return { available: true, watching: watched, refused, stop };
  } catch { stop(); return unavailable; }
}

export function steamControllerInput(host: unknown): ControllerInputSource | undefined {
  try {
    return (host as { SteamClient?: { Input?: ControllerInputSource } })?.SteamClient?.Input;
  } catch { return undefined; }
}
