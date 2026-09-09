import type { ControllerInputSource } from "./controller-safe-disconnect";

export type MenuBinding = "view-y" | "sticks" | "disabled";
export const menuBindingOptions = [
  { label: "View / Back + Y", data: "view-y" as MenuBinding },
  { label: "L3 + R3", data: "sticks" as MenuBinding },
  { label: "Disabled", data: "disabled" as MenuBinding },
];
const STORAGE_KEY = "regear.menu-shortcut.v1";
const validBinding = (value: unknown): value is MenuBinding =>
  value === "view-y" || value === "sticks" || value === "disabled";

export function loadMenuBinding(storage?: Pick<Storage, "getItem">): MenuBinding {
  try {
    const value = (storage ?? globalThis.localStorage)?.getItem(STORAGE_KEY);
    // Legacy start-select/bumpers choices migrate to the new default. Disabled stays disabled.
    return validBinding(value) ? value : "view-y";
  } catch { return "view-y"; }
}

export function saveMenuBinding(binding: MenuBinding, storage?: Pick<Storage, "setItem">): boolean {
  try {
    const target = storage ?? globalThis.localStorage;
    if (!validBinding(binding) || !target) return false;
    target.setItem(STORAGE_KEY, binding);
    return true;
  } catch { return false; }
}

/** Declaration-derived button codes; physical Ally delivery still needs validation.
 * This non-exclusive listener opens only a menu and cannot suppress game input. */
export function startMenuShortcut(deps: {
  input?: ControllerInputSource;
  readBinding(): MenuBinding;
  open(): void;
}): { available: boolean; reset(): void; stop(): void } {
  const subscriptions: { unregister(): void }[] = [];
  const controllers = new Map<number, Set<number>>();
  const latched = new Set<number>();
  let active = false;
  const reset = () => { controllers.clear(); latched.clear(); };
  const stop = () => {
    active = false;
    reset();
    for (const subscription of subscriptions.splice(0)) {
      try { subscription.unregister(); } catch { /* Callbacks remain inert. */ }
    }
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
    if (buttons.has(button) === pressed) return;
    if (pressed) buttons.add(button); else buttons.delete(button);
    if (buttons.size === 0) { controllers.delete(id); latched.delete(id); return; }
    // A release cannot turn a larger held combination into a new shortcut.
    if (!pressed || buttons.size !== 2 || latched.has(id)) return;
    let binding: MenuBinding;
    try { binding = deps.readBinding(); } catch { reset(); return; }
    const pair = (a: number, b: number) => buttons.has(a) && buttons.has(b);
    const matches = binding === "view-y" ? pair(9, 3)
      : binding === "sticks" && pair(25, 41);
    if (!matches) return;
    latched.add(id);
    try { deps.open(); } catch { /* Never retry uncertain menu delivery until release. */ }
  };
  try {
    const input = deps.input;
    if (typeof input?.RegisterForControllerInputMessages !== "function") {
      return { available: false, reset, stop };
    }
    const registrations: (() => { unregister(): void })[] = [];
    if (typeof input.RegisterForControllerListChanges === "function") {
      registrations.push(() => input.RegisterForControllerListChanges!(reset));
    }
    if (typeof input.RegisterForActiveControllerChanges === "function") {
      registrations.push(() => input.RegisterForActiveControllerChanges!(reset));
    }
    if (!registrations.length) return { available: false, reset, stop };
    registrations.push(() => input.RegisterForControllerInputMessages(onInput));
    for (const register of registrations) {
      const subscription = register();
      if (typeof subscription?.unregister !== "function") {
        stop(); return { available: false, reset, stop };
      }
      subscriptions.push(subscription);
    }
    active = true;
    return { available: true, reset, stop };
  } catch { stop(); return { available: false, reset, stop }; }
}
