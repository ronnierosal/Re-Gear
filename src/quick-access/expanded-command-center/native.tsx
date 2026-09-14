import { createMenuVisibility } from "./menu-visibility";
import { testBuildTiles, unavailableTestActions } from "./test-build-actions";
import { createNativeUtilities } from "./native-utilities";
import type { UtilityReadings, UtilitySystem } from "./native-utilities";
import type { NonEgpuDetailRenderer } from "./non-egpu-detail-renderer";
import { useEffect, useState, useSyncExternalStore } from "react";
import type { ComponentProps } from "react";
import { Button, Dropdown, Focusable, ModalRoot, showModal, GamepadButton, findModuleExport } from "@decky/ui";
import type { ControllerInputSource } from "../../controller-safe-disconnect";
import { loadMenuBinding, saveMenuBinding, menuBindingOptions, startMenuShortcut } from "../../menu-shortcut";
import type { MenuBinding } from "../../menu-shortcut";
import { WholeDockControl } from "../../whole-dock-control";
import { EgpuConfirmModal } from "../../egpu-confirm-modal";
import { ExpandedCommandCenter } from "./shell";
import type { TileSource, TileView } from "./tile-source";
import { ShortcutSettings } from "./shortcut-settings";

/** Named Steam navigation feedback; no guessed enums or separate audio player. */
export function createMenuFeedback(find:(predicate:(candidate:any)=>boolean)=>any){
  let dispatcher:any, sounds:any;
  return (kind:"select"|"back")=>{
    try{
      dispatcher??=find(candidate=>typeof candidate?.PlayNavSound==="function");
      sounds??=find(candidate=>typeof candidate?.IntoGameDetail==="number"&&typeof candidate?.DefaultOk==="number"&&typeof candidate?.BasicNav==="number");
      if(dispatcher&&sounds)dispatcher.PlayNavSound(kind==="select"?sounds.IntoGameDetail:sounds.DefaultOk);
    }catch{/* Missing or changed sound support must never block an action. */}
  };
}
const playMenuFeedback=createMenuFeedback(predicate=>findModuleExport(predicate));
export function NativeMenuButton(props:ComponentProps<typeof Button>&{"aria-disabled"?:boolean|"true"|"false"}){
  return <Button {...props} onOKButton={props.onOKButton??(event=>{
    event.preventDefault();event.stopPropagation();
    if(props.disabled||props["aria-disabled"]===true||props["aria-disabled"]==="true")return true;
    playMenuFeedback("select");(event.currentTarget as HTMLElement|null)?.click();return true;
  })}/>;
}

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
const emptyUtilities: UtilityReadings = {};
const noUtilities = () => emptyUtilities;
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

export function createExpandedMenu(input: ControllerInputSource | undefined, host: Window, canOpen: () => boolean = () => true, source?: TileSource, readCurrentSnapshot: () => unknown = () => null, renderDetail?: NonEgpuDetailRenderer) {
  const system = (host as Window & { SteamClient?: { System?: UtilitySystem } }).SteamClient?.System;
  const utilities = system ? createNativeUtilities(system) : undefined;
  const storage = (() => { try { return host.localStorage; } catch { return undefined; } })();
  let binding = loadMenuBinding(storage);
  let modal: ReturnType<typeof showModal> | null = null;
  let operation: ReturnType<typeof showModal> | null = null;
  let operationGeneration=0;
  const hideOperation=()=>{const previous=operation;operation=null;operationGeneration++;previous?.Close();};
  const visibility = createMenuVisibility();
  let opening = false;
  let stopped = false;
  let generation = 0;
  const close = () => {
    hideOperation();
    const previous = modal;
    modal = null;
    generation++;
    utilities?.stop();
    visibility.set(false);
    previous?.Close();
  };
  function disconnect() {
    if(stopped||operation||!modal) return;
    // One explicit activation owns one consumable request across React remounts.
    let consumed=false;
    const startRequest=()=>{if(consumed)return false;consumed=true;return true;};
    const operationToken=++operationGeneration;
    const hide=()=>{if(operationGeneration===operationToken)hideOperation();};
    const opened=showModal(<EgpuConfirmModal strTitle="Safe Disconnect" strOKButtonText="Hide" bAlertDialog onOK={hide} onCancel={hide} onEscKeypress={hide} className="rg-whole-dock-progress">
      <style>{`.rg-whole-dock-progress{position:fixed!important;left:50%!important;top:50%!important;right:auto!important;bottom:auto!important;margin:0!important;transform:translate(-50%,-50%)!important}`}</style>
      <WholeDockControl intent="disconnect_only" readCurrentSnapshot={readCurrentSnapshot} startRequest={startRequest}/>
    </EgpuConfirmModal>,host,{fnOnClose:hide,bNeverPopOut:true});
    if(operationGeneration!==operationToken){opened.Close();return;}
    operation=opened;
  }
  function View({ token }: { token: number }) {
    useEffect(() => () => { if (generation === token) { hideOperation();modal = null; generation++; utilities?.stop(); visibility.set(false); } }, [token]);
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
    const rawTiles = useSyncExternalStore(subscribeTo(source), readFrom(source), readFrom(source));
    const tiles = rawTiles ? testBuildTiles(rawTiles) : undefined;
    const utilityReadings = useSyncExternalStore(utilities?.subscribe ?? noSubscribe, utilities?.read ?? noUtilities, utilities?.read ?? noUtilities);
    return <ExpandedCommandCenter onClose={close} native onFeedback={playMenuFeedback} onDisconnect={disconnect} disconnectControl={<WholeDockControl intent="disconnect_only" readCurrentSnapshot={readCurrentSnapshot}/>} directions={{up:GamepadButton.DIR_UP,down:GamepadButton.DIR_DOWN,left:GamepadButton.DIR_LEFT,right:GamepadButton.DIR_RIGHT}} unavailableActions={unavailableTestActions} layoutStorage={storage} editButtons={{y:GamepadButton.OPTIONS}} primitives={{ Button: NativeMenuButton, Focusable }} settings={<Settings/>} tiles={tiles} renderDetail={renderDetail} utilityReadings={utilityReadings} onUtilityRequest={utilities ? (id, percent) => {
      if (generation !== token || stopped) return Promise.reject(new Error("Menu closed"));
      return utilities.request(id, percent);
    } : undefined}/>;
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
    if (stopped || opening || modal || !canOpen()) return;
    const token = ++generation;
    opening = true;
    try {
    utilities?.start();
    const opened = showModal(<ModalRoot closeModal={close} bAllowFullSize bHideCloseIcon bDisableBackgroundDismiss className="rg-expanded-modal-root" modalClassName="rg-expanded-modal-frame">
      <style>{`.rg-expanded-modal-root,.rg-expanded-modal-frame{position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;max-width:none!important;max-height:none!important;padding:0!important;margin:0!important;background:transparent!important;box-shadow:none!important}`}</style>
      <View token={token}/>
    </ModalRoot>, host, { strTitle: "Re-Gear expanded demo", bNeverPopOut: true });
    if (generation !== token || stopped) { opened.Close(); return; }
    modal = opened;
    visibility.set(true);
    } catch { utilities?.stop(); visibility.set(false); } finally { opening = false; }
  };
  const shortcut = startMenuShortcut({ input, readBinding: () => binding, open });
  return { open, visibility: visibility.source, available: shortcut.available, stop() { stopped = true; shortcut.stop(); close(); } };
}
