import { useEffect, useState } from "react";
import { Button, Dropdown, Focusable, ModalRoot, showModal } from "@decky/ui";
import type { ControllerInputSource } from "../../controller-safe-disconnect";
import { loadMenuBinding, saveMenuBinding, menuBindingOptions, startMenuShortcut } from "../../menu-shortcut";
import type { MenuBinding } from "../../menu-shortcut";
import { ExpandedCommandCenter } from "./shell";
import { WholeDockControl } from "../../whole-dock-control";
import type { DockIntent } from "../../whole-dock-control-model";
import { ShortcutSettings } from "./shortcut-settings";

/** The two player-selectable dock routes. Reconnect and sleep stay unmounted.
 *
 * Selection is presentation only. dockIntentControl and every backend guard
 * still decide whether the chosen route is offered at all, so picking
 * "shutdown" here cannot make a shutdown happen that the same guards would
 * have refused. One control, one pending record, one poll: a second mounted
 * control would share that record and the two would disable each other. */
const dockIntentOptions: { label: string; data: DockIntent }[] = [
  { label: "Disconnect only", data: "disconnect_only" },
  { label: "Disconnect and shut down", data: "shutdown" },
];

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
    // Defaults to the route the 0.3.98 golden cycle actually ran. The control
    // was built for a changing intent prop -- it re-checks the intent after
    // every await and recovers a pending record's intent from storage -- so a
    // flip mid-confirmation aborts cleanly rather than dispatching the wrong route.
    const [dockIntent, setDockIntent] = useState<DockIntent>("disconnect_only");
    return <ExpandedCommandCenter onClose={close} native disconnectControl={
      <Focusable>
        <Dropdown menuLabel="Dock action" rgOptions={dockIntentOptions} selectedOption={dockIntent}
          onChange={option => { if (dockIntentOptions.some(item => item.data === option.data)) setDockIntent(option.data as DockIntent); }}/>
        <WholeDockControl intent={dockIntent} readCurrentSnapshot={readCurrentSnapshot}/>
      </Focusable>
    } primitives={{ Button: Button, Focusable }} settings={<Settings/>}/>;
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
