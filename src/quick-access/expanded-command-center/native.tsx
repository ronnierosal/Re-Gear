import { useEffect, useState, useSyncExternalStore } from "react";
import { Button, Dropdown, Focusable, ModalRoot, showModal } from "@decky/ui";
import type { ControllerInputSource } from "../../controller-safe-disconnect";
import { loadMenuBinding, saveMenuBinding, menuBindingOptions, startMenuShortcut } from "../../menu-shortcut";
import type { MenuBinding } from "../../menu-shortcut";
import { ExpandedCommandCenter } from "./shell";
import type { TileSource, TileView } from "./tile-source";
import { ShortcutSettings } from "./shortcut-settings";

/** Native adapter. Opens the menu, saves its launcher preference, and passes
 * through readings published by the panel that owns snapshot polling.
 *
 * `source` is optional so the browser fixture and the tests keep working
 * unchanged. When it is absent the shell falls back to its synthetic sample
 * tiles, which is correct for a preview and must never happen in production --
 * the publisher supplies every tab, Unknown included, precisely so that
 * fallback is unreachable once wired.
 *
 * This adapter starts no timer and calls no backend function. It subscribes to
 * a view someone else owns; adding a read here would be a second source of
 * truth for state a player acts on.
 */
/** Stable per-source callbacks. useSyncExternalStore resubscribes whenever the
 * subscribe function's identity changes, so these are cached rather than built
 * per render; without that the menu would tear down and re-register its
 * subscription on every publish it received. */
const noSubscribe = () => () => {};
const noTiles = () => undefined;
const subscribers = new WeakMap<TileSource, (listener: () => void) => () => void>();
const readers = new WeakMap<TileSource, () => TileView | undefined>();
function subscribeTo(source?: TileSource) {
  if (!source) return noSubscribe;
  let cached = subscribers.get(source);
  if (!cached) { cached = (listener) => source.subscribe(listener); subscribers.set(source, cached); }
  return cached;
}
function readFrom(source?: TileSource) {
  if (!source) return noTiles;
  let cached = readers.get(source);
  if (!cached) { cached = () => source.read(); readers.set(source, cached); }
  return cached;
}

export function createExpandedMenu(input: ControllerInputSource | undefined, host: Window, canOpen: () => boolean = () => true, source?: TileSource) {
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
    // Live subscription, not a read at open.
    //
    // Reading once when the menu opened left whatever was true at that moment
    // on screen for as long as it stayed open, which is the aged-data-as-current
    // failure this bridge exists to prevent: a player can open the menu, watch
    // the eGPU drop, and still be looking at "Running".
    //
    // useSyncExternalStore compares by reference, so the source returns a stable
    // object between publishes; a fresh object per call would re-render without
    // end. The server snapshot is the same read: there is no server, and
    // returning a different value there would tear.
    const tiles = useSyncExternalStore(subscribeTo(source), readFrom(source), readFrom(source));
    return <ExpandedCommandCenter onClose={close} native primitives={{ Button: Button, Focusable }} settings={<Settings/>} tiles={tiles}/>;
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
