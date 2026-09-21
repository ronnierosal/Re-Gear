import {Tutorials} from './tutorials';
import {offlineTabTiles,offlineUnavailableActions} from "./offline-tab";
import type { RuntimeDetailSource } from "./runtime-detail-source";
import {version} from "../../../package.json";
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
import type { DockIntent } from "../../whole-dock-control-model";
import { EgpuConfirmModal } from "../../egpu-confirm-modal";
import { ExpandedCommandCenter } from "./shell";
import type { TileSource, TileView } from "./tile-source";
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
const noRuntimeDetails=()=>null;
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

export function createExpandedMenu(input: ControllerInputSource | undefined, host: Window, canOpen: () => boolean = () => true, source?: TileSource, readCurrentSnapshot: () => unknown = () => null, renderDetail?: NonEgpuDetailRenderer, runtimeDetails?:RuntimeDetailSource) {
  const system = (host as Window & { SteamClient?: { System?: UtilitySystem } }).SteamClient?.System;
  const utilities = system ? createNativeUtilities(system) : undefined;
  const storage = (() => { try { return host.localStorage; } catch { return undefined; } })();
  let binding = loadMenuBinding(storage);
  const bindingListeners=new Set<()=>void>();
  const readBinding=()=>binding;
  const subscribeBinding=(listener:()=>void)=>{bindingListeners.add(listener);return()=>{bindingListeners.delete(listener);};};
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
  function disconnect(intent: DockIntent = "disconnect_only") {
    if(stopped||operation||!modal) return;
    // One explicit activation owns one consumable request across React remounts.
    let consumed=false;
    const startRequest=()=>{if(consumed)return false;consumed=true;return true;};
    const operationToken=++operationGeneration;
    const hide=()=>{if(operationGeneration===operationToken)hideOperation();};
    const title=intent==="shutdown"?"Safe Disconnect + Shutdown":"Safe Disconnect";
    const opened=showModal(<EgpuConfirmModal strTitle={title} strOKButtonText="Hide" bAlertDialog onOK={hide} onCancel={hide} onEscKeypress={hide} className="rg-whole-dock-progress">
      <style>{`.rg-whole-dock-progress{position:fixed!important;left:50%!important;top:50%!important;right:auto!important;bottom:auto!important;margin:0!important;transform:translate(-50%,-50%)!important}`}</style>
      <WholeDockControl intent={intent} readCurrentSnapshot={readCurrentSnapshot} startRequest={startRequest}/>
    </EgpuConfirmModal>,undefined,{fnOnClose:hide,bNeverPopOut:true});
    if(operationGeneration!==operationToken){opened.Close();return;}
    operation=opened;
  }
  function ShutdownStatus(){
    const state=useSyncExternalStore(runtimeDetails?.subscribe??noSubscribe,runtimeDetails?.read??noRuntimeDetails,runtimeDetails?.read??noRuntimeDetails);
    return <p role="status">{state?.shutdown?.message||"Checking shutdown readiness…"}</p>;
  }
  function shutdown(){
    if(stopped||operation||!modal||!runtimeDetails?.read()?.shutdown?.available)return;
    const operationToken=++operationGeneration;
    const hide=()=>{if(operationGeneration===operationToken)hideOperation();};
    // Dispatch only on explicit activation, never on mount/reopen.
    runtimeDetails.requestShutdown();
    const opened=showModal(<EgpuConfirmModal strTitle="Shutdown" strOKButtonText="Hide" bAlertDialog onOK={hide} onCancel={hide} onEscKeypress={hide} className="rg-whole-dock-progress">
      <style>{`.rg-whole-dock-progress{position:fixed!important;left:50%!important;top:50%!important;right:auto!important;bottom:auto!important;margin:0!important;transform:translate(-50%,-50%)!important}`}</style>
      <ShutdownStatus/>
    </EgpuConfirmModal>,undefined,{fnOnClose:hide,bNeverPopOut:true});
    if(operationGeneration!==operationToken){opened.Close();return;}operation=opened;
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
    const runtimeState=useSyncExternalStore(runtimeDetails?.subscribe??noSubscribe,runtimeDetails?.read??noRuntimeDetails,runtimeDetails?.read??noRuntimeDetails);
    const mappedTiles = rawTiles ? testBuildTiles(rawTiles) : undefined;
    const tiles=mappedTiles&&runtimeDetails?{...mappedTiles,egpu:mappedTiles.egpu?.map(tile=>tile.id==="switch-handheld"?{...tile,value:runtimeState?.handheld.available?"Ready":"Unavailable",detail:runtimeState?.handheld.reason??"Current display status unavailable",tone:runtimeState?.handheld.available?"quiet" as const:"unavailable" as const}:tile),settings:mappedTiles.settings?.map(tile=>tile.id==="diagnostics"?{...tile,value:runtimeState?"Open":"Waiting",detail:"Status, recovery and support"}:tile.id==="about"?{...tile,value:version,detail:"Version and credits"}:tile.id==="quick-actions"?{...tile,value:"Customize",detail:"Focus a Quick Access button and tap Y"}:tile)}:mappedTiles;
    const unavailable={...unavailableTestActions,...(runtimeDetails?offlineUnavailableActions:{})};
    if(runtimeDetails){if(!runtimeState?.shutdown?.available)unavailable["portable-shutdown"]=runtimeState?.shutdown?.reason??"Current status unavailable";if(runtimeState?.handheld.available)delete unavailable["switch-handheld"];else unavailable["switch-handheld"]=runtimeState?.handheld.reason??"Current display status unavailable";if(runtimeState?.sleepConnected?.available)delete unavailable["disconnect-sleep"];else unavailable["disconnect-sleep"]=runtimeState?.sleepConnected?.reason??"Current status unavailable";}
    // Defaults to the route the 0.3.98 golden cycle actually ran. The control
    // was built for a changing intent prop -- it re-checks the intent after
    // every await and recovers a pending record's intent from storage -- so a
    // flip mid-confirmation aborts cleanly rather than dispatching the wrong route.
    const [dockIntent, setDockIntent] = useState<DockIntent>("disconnect_only");
    const utilityReadings = useSyncExternalStore(utilities?.subscribe ?? noSubscribe, utilities?.read ?? noUtilities, utilities?.read ?? noUtilities);
    return <ExpandedCommandCenter onClose={close} native onFeedback={playMenuFeedback} onDisconnect={disconnect} disconnectControl={
      <Focusable>
        <Dropdown menuLabel="Dock action" rgOptions={dockIntentOptions} selectedOption={dockIntent}
          onChange={option => { if (dockIntentOptions.some(item => item.data === option.data)) setDockIntent(option.data as DockIntent); }}/>
        <WholeDockControl intent={dockIntent} readCurrentSnapshot={readCurrentSnapshot}/>
      </Focusable>
    } directions={{up:GamepadButton.DIR_UP,down:GamepadButton.DIR_DOWN,left:GamepadButton.DIR_LEFT,right:GamepadButton.DIR_RIGHT}} unavailableActions={unavailable} onAction={(_tab,tile)=>{if(tile.id==="disconnect-sleep"){runtimeDetails?.requestSleepConnected();return true;}if(tile.id==="disconnect-shutdown"){disconnect("shutdown");return true;}if(tile.id==="portable-shutdown"){shutdown();return true;}if(tile.id==="switch-handheld"){runtimeDetails?.requestHandheld();return true;}return false;}} layoutStorage={storage} editButtons={{y:GamepadButton.OPTIONS}} primitives={{ Button: NativeMenuButton, Focusable }} settings={<Settings/>} tiles={runtimeDetails?{...tiles,egpu:[...(tiles?.egpu??[]),{id:"portable-shutdown",title:"Shutdown",value:runtimeState?.shutdown?.pending?"Pending":runtimeState?.shutdown?.available?"Ready":"Unavailable",detail:runtimeState?.shutdown?.reason??"Current status unavailable"}],offline:offlineTabTiles,settings:[...(tiles?.settings??[]).filter(tile=>tile.id==='diagnostics'),{id:'reset-layout',title:'Reset Layout',value:'Configure',detail:'Restore default card positions'},{id:'tutorials',title:'Tutorials',value:'Open',detail:'Connection, disconnect and help'},{id:'about',title:'About',value:version,detail:'Version and credits'}]}:tiles} renderDetail={runtimeDetails?((tab,tile)=>tab==='settings'&&tile.id==='tutorials'?<Tutorials/>:renderDetail?.(tab,tile)):renderDetail} catalogReadings={rawTiles} utilityReadings={utilityReadings} onUtilityRequest={utilities ? (id, percent) => {
      if (generation !== token || stopped) return Promise.reject(new Error("Menu closed"));
      return utilities.request(id, percent);
    } : undefined}/>;
  }
  function Settings() {
    const selected=useSyncExternalStore(subscribeBinding,readBinding,readBinding);
    const [error, setError] = useState("");
    function change(value: MenuBinding) {
      if(stopped)return;
      if (!saveMenuBinding(value, storage)) { setError("Could not save the shortcut. Your previous choice remains active."); return; }
      binding = value; shortcut.reset(); bindingListeners.forEach(listener=>listener()); setError("");
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
    </ModalRoot>, undefined, { strTitle: "Re-Gear Command Center", bNeverPopOut: true });
    if (generation !== token || stopped) { opened.Close(); return; }
    modal = opened;
    visibility.set(true);
    } catch { utilities?.stop(); visibility.set(false); } finally { opening = false; }
  };
  const shortcut = startMenuShortcut({ input, readBinding: () => binding, open });
  return { open, disconnect, Settings, visibility: visibility.source, available: shortcut.available, stop() { stopped = true; shortcut.stop(); close(); } };
}
