import { useEffect, useState } from "react";
import { ModalRoot, showModal } from "@decky/ui";
import type { ControllerInputSource } from "../../controller-safe-disconnect";
import { loadMenuBinding, saveMenuBinding, menuBindingOptions, startMenuShortcut } from "../../menu-shortcut";
import type { MenuBinding } from "../../menu-shortcut";
import { ExpandedCommandCenter } from "./shell";

/** Native test adapter; only opens a demo and saves its launcher preference. */
export function createExpandedMenu(input: ControllerInputSource | undefined, host: Window) {
  const storage = (() => { try { return host.localStorage; } catch { return undefined; } })();
  let binding = loadMenuBinding(storage);
  let modal: ReturnType<typeof showModal> | null = null;
  let stopped = false;
  let generation = 0;
  let navigation: { unregister(): void } | undefined;
  const resets: { unregister(): void }[] = [];
  const pressed = new Set<string>();
  const detach = () => {
    try { navigation?.unregister(); } catch { /* Late callbacks check modal. */ }
    navigation = undefined;
    for (const lease of resets.splice(0)) { try { lease.unregister(); } catch { /* No state retained. */ } }
    pressed.clear();
  };
  const close = () => {
    const previous = modal;
    modal = null;
    generation++;
    detach();
    previous?.Close();
  };
  function View({ token }: { token: number }) {
    useEffect(() => () => { if (generation === token) { modal = null; generation++; detach(); } }, [token]);
    return <ExpandedCommandCenter onClose={close} native settings={<Settings/>}/>;
  }
  function Settings() {
    const [selected, setSelected] = useState(binding);
    const [error, setError] = useState("");
    function change(value: MenuBinding) {
      if (!saveMenuBinding(value, storage)) { setError("Could not save the shortcut. Your previous choice remains active."); return; }
      binding = value; shortcut.reset(); setSelected(value); setError("");
    }
    return <section className="rg-expanded-detail-page" style={{ marginBottom: 14 }}>
      <h3>Open Re-Gear</h3><p>Menu shortcut · saved on this Steam client</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {menuBindingOptions.map(option => <button className="rg-expanded-back" type="button" key={option.data} data-ec-control={`binding-${option.data}`} aria-pressed={selected === option.data}
          onClick={() => change(option.data)}>{selected === option.data ? "✓ " : ""}{option.label}</button>)}
      </div>
      <p>{shortcut.available ? "Press both buttons together. Release both before opening again." : "Controller input is unavailable. Use the Open expanded demo button in Quick Access."}</p>
      <p>Steam or the game may also respond to these buttons. Native button delivery is under validation.</p>
      {error && <p role="alert">{error}</p>}
    </section>;
  }
  const open = () => {
    if (stopped || modal) return;
    const token = ++generation;
    modal = showModal(<ModalRoot closeModal={close} bAllowFullSize bHideCloseIcon bDisableBackgroundDismiss bCancelDisabled className="rg-expanded-modal-root" modalClassName="rg-expanded-modal-frame">
      <style>{`.rg-expanded-modal-root,.rg-expanded-modal-frame{position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;max-width:none!important;max-height:none!important;padding:0!important;margin:0!important;background:transparent!important;box-shadow:none!important}`}</style>
      <View token={token}/>
    </ModalRoot>, host, { strTitle: "Re-Gear expanded demo", bNeverPopOut: true });
    // Raw Steam callback codes, not browser Gamepad indices. No event suppression
    // claim: the native lifecycle must still prove exclusive game-input focus.
    const keys: Record<number, string> = { 1: "Escape", 4: "ArrowUp", 5: "ArrowRight", 6: "ArrowDown", 7: "ArrowLeft", 30: "q", 31: "e" };
    try {
      for (const register of [input?.RegisterForControllerListChanges, input?.RegisterForActiveControllerChanges]) {
        if (register) { const lease = register.call(input, () => { if (generation === token) pressed.clear(); }); if (typeof lease?.unregister === "function") resets.push(lease); }
      }
      navigation = input?.RegisterForControllerInputMessages((controller, button, down) => {
        if (!modal || stopped || generation !== token || !Number.isInteger(controller) || !Number.isInteger(button) || typeof down !== "boolean") return;
        const key = `${controller}:${button}`;
        if (!down) { pressed.delete(key); return; }
        if (pressed.has(key)) return;
        if (pressed.size >= 64) { pressed.clear(); return; }
        pressed.add(key);
        const panel = host.document.querySelector<HTMLElement>("[data-ec-panel]");
        if (!panel) return;
        const active = host.document.activeElement as HTMLElement | null;
        const target = active && panel.contains(active) ? active : panel;
        if (button === 0) { if (target.tagName === "BUTTON") target.click(); return; }
        if (keys[button]) target.dispatchEvent(new KeyboardEvent("keydown", { key: keys[button], bubbles: true, cancelable: true }));
      });
    } catch { /* Touch and native modal UI remain available if subscription fails. */ }
  };
  const shortcut = startMenuShortcut({ input, readBinding: () => binding, open });
  return { open, stop() { stopped = true; shortcut.stop(); close(); } };
}
