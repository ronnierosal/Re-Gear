import { useEffect, useState } from "react";
import { DialogButton, Focusable, ModalRoot, showModal } from "@decky/ui";
import type { ControllerInputSource } from "../../controller-safe-disconnect";
import { loadMenuBinding, saveMenuBinding, menuBindingOptions, startMenuShortcut } from "../../menu-shortcut";
import type { MenuBinding } from "../../menu-shortcut";
import { ExpandedCommandCenter } from "./shell";

/** Native test adapter; only opens a demo and saves its launcher preference. */
export function createExpandedMenu(input: ControllerInputSource | undefined, host: Window, canOpen: () => boolean = () => true) {
  const storage = (() => { try { return host.localStorage; } catch { return undefined; } })();
  let binding = loadMenuBinding(storage);
  let modal: ReturnType<typeof showModal> | null = null;
  let stopped = false;
  let generation = 0;
  const close = () => {
    const previous = modal;
    modal = null;
    generation++;
    previous?.Close();
  };
  function View({ token }: { token: number }) {
    useEffect(() => () => { if (generation === token) { modal = null; generation++; } }, [token]);
    return <ExpandedCommandCenter onClose={close} native primitives={{ Button: DialogButton, Focusable }} settings={<Settings/>}/>;
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
      <Focusable flow-children="horizontal" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {menuBindingOptions.map(option => <DialogButton className="rg-expanded-back" key={option.data} data-ec-control={`binding-${option.data}`} aria-pressed={selected === option.data}
          onClick={() => change(option.data)}>{selected === option.data ? "✓ " : ""}{option.label}</DialogButton>)}
      </Focusable>
      <p>{shortcut.available ? "Press both buttons together. Release both before opening again." : "Controller input is unavailable. Use the Open expanded demo button in Quick Access."}</p>
      <p>Steam or the game may also respond to these buttons. Native button delivery is under validation.</p>
      {error && <p role="alert">{error}</p>}
    </section>;
  }
  const open = () => {
    if (stopped || modal || !canOpen()) return;
    const token = ++generation;
    modal = showModal(<ModalRoot closeModal={close} bAllowFullSize bHideCloseIcon bDisableBackgroundDismiss className="rg-expanded-modal-root" modalClassName="rg-expanded-modal-frame">
      <style>{`.rg-expanded-modal-root,.rg-expanded-modal-frame{position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;max-width:none!important;max-height:none!important;padding:0!important;margin:0!important;background:transparent!important;box-shadow:none!important}`}</style>
      <View token={token}/>
    </ModalRoot>, host, { strTitle: "Re-Gear expanded demo", bNeverPopOut: true });

  };
  const shortcut = startMenuShortcut({ input, readBinding: () => binding, open });
  return { open, available: shortcut.available, stop() { stopped = true; shortcut.stop(); close(); } };
}
