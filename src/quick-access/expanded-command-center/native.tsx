import { useEffect, useState } from "react";
import { Button, Dropdown, Focusable, ModalRoot, showModal } from "@decky/ui";
import type { ControllerInputSource } from "../../controller-safe-disconnect";
import { loadMenuBinding, saveMenuBinding, menuBindingOptions, startMenuShortcut } from "../../menu-shortcut";
import type { MenuBinding } from "../../menu-shortcut";
import { ExpandedCommandCenter } from "./shell";
import { WholeDockControl } from "../../whole-dock-control";
import { ShortcutSettings } from "./shortcut-settings";

/** Native menu adapter: preview tiles plus the explicitly guarded dock control. */
export function createExpandedMenu(input: ControllerInputSource | undefined, host: Window, canOpen: () => boolean = () => true, readCurrentSnapshot: () => unknown = () => null) {
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
    return <ExpandedCommandCenter onClose={close} native disconnectControl={<WholeDockControl readCurrentSnapshot={readCurrentSnapshot}/>} primitives={{ Button: Button, Focusable }} settings={<Settings/>}/>;
  }
  function Settings() {
    const [selected, setSelected] = useState(binding);
    const [error, setError] = useState("");
    function change(value: MenuBinding) {
      if (!saveMenuBinding(value, storage)) { setError("Could not save the shortcut. Your previous choice remains active."); return; }
      binding = value; shortcut.reset(); setSelected(value); setError("");
    }
    return <ShortcutSettings available={shortcut.available} error={error} control={
      <Dropdown menuLabel="Open Re-Gear" rgOptions={menuBindingOptions} selectedOption={selected}
        onChange={option => { if (menuBindingOptions.some(item => item.data === option.data)) change(option.data as MenuBinding); }} />
    }/>;
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
