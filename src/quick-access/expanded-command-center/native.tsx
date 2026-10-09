import { shutdownUnplugWaiting } from "../../whole-dock-control-model";
import { productionEgpuTiles } from "../../build-profile";
import type { BuildProfile } from "../../build-profile";
import {Tutorials} from './tutorials';
import {offlineTabTiles,offlineUnavailableActions} from "./offline-tab";
import type { RuntimeDetailSource } from "./runtime-detail-source";
import {version} from "../../../package.json";
import { createMenuVisibility } from "./menu-visibility";
import { testBuildTiles, unavailableTestActions } from "./test-build-actions";
import { displayTargetActionTile } from "./display-target-action";
import { createNativeUtilities } from "./native-utilities";
import type { UtilityReadings, UtilitySystem } from "./native-utilities";
import type { NonEgpuDetailRenderer } from "./non-egpu-detail-renderer";
import { useEffect, useState, useSyncExternalStore } from "react";
import type { ComponentProps } from "react";
import { callable } from "@decky/api";
import { Button, Dropdown, Focusable, ModalRoot, showModal, GamepadButton, findModuleExport } from "@decky/ui";
import type { ControllerInputSource } from "../../controller-safe-disconnect";
import { loadMenuBinding, saveMenuBinding, menuBindingOptions, startMenuShortcut } from "../../menu-shortcut";
import type { MenuBinding } from "../../menu-shortcut";
import { recoverTerminalDockReceipt, WholeDockControl, type DockSettlement } from "../../whole-dock-control";
import { createUnplugWarningCoordinator } from "../../unplug-warning-coordinator";
import { createUnplugWarningAudio } from "../../unplug-warning-audio";
import { parsePendingRecord, type DockIntent } from "../../whole-dock-control-model";
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
  { label: "Disconnect and sleep", data: "sleep" },
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
 * This adapter does not poll ordinary tile status. It owns only a read-only
 * pending-request watcher so an unplug warning survives a host-driven modal
 * close; all ordinary status remains supplied by the existing tile source.
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
const readDockTrial = callable<[string], any>("get_egpu_disconnect_status");
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

export function createExpandedMenu(input: ControllerInputSource | undefined, host: Window, canOpen: () => boolean = () => true, source?: TileSource, readCurrentSnapshot: () => unknown = () => null, renderDetail?: NonEgpuDetailRenderer, runtimeDetails?:RuntimeDetailSource, policy: BuildProfile = "development") {
  const production = policy === "production";
  const system = (host as Window & { SteamClient?: { System?: UtilitySystem } }).SteamClient?.System;
  const utilities = system ? createNativeUtilities(system) : undefined;
  const storage = (() => { try { return host.localStorage; } catch { return undefined; } })();
  let binding = loadMenuBinding(storage);
  const bindingListeners=new Set<()=>void>();
  const readBinding=()=>binding;
  const subscribeBinding=(listener:()=>void)=>{bindingListeners.add(listener);return()=>{bindingListeners.delete(listener);};};
  let modal: ReturnType<typeof showModal> | null = null;
  let operation: ReturnType<typeof showModal> | null = null;
  let operationKind:"active"|"status"|null=null;
  let operationGeneration=0;
  let pendingStatusTimer:ReturnType<typeof setTimeout>|null=null;
  let recoveryTimer:ReturnType<typeof setTimeout>|null=null;
  let recoveryAttempts=0;
  let ownerWarningTimer:ReturnType<typeof setTimeout>|null=null;
  let ownerWarningPollInFlight=false;
  let ownerWarningReadAfterClose=false;
  const setPendingTimeout = typeof host.setTimeout === "function"
    ? host.setTimeout.bind(host) : globalThis.setTimeout;
  const clearPendingTimeout = typeof host.clearTimeout === "function"
    ? host.clearTimeout.bind(host) : globalThis.clearTimeout;
  const setWarningInterval = typeof host.setInterval === "function"
    ? host.setInterval.bind(host) : globalThis.setInterval;
  const clearWarningInterval = typeof host.clearInterval === "function"
    ? host.clearInterval.bind(host) : globalThis.clearInterval;
  let warningAudio: ReturnType<typeof createUnplugWarningAudio> | undefined;
  const unplugWarning = createUnplugWarningCoordinator({
    schedule: setPendingTimeout,
    cancel: clearPendingTimeout,
    repeat: setWarningInterval,
    cancelRepeat: clearWarningInterval,
    playWarning: () => {
      const state = unplugWarning.read();
      if (stopped || state.phase !== "alarm") return;
      warningAudio ??= createUnplugWarningAudio({
        createContext: () => {
          const Constructor = (host as Window & { AudioContext?: typeof AudioContext }).AudioContext;
          if (typeof Constructor !== "function") throw new Error("Web Audio unavailable");
          return new Constructor();
        },
        fallback: () => playMenuFeedback("back"),
      });
      warningAudio.observe(state);
      warningAudio.play();
    },
  });
  let presentedDockSettlement: DockSettlement | null = null;
  const hideOperation=()=>{const previous=operation;operation=null;operationKind=null;operationGeneration++;previous?.Close();};
  const presentDockSettlement=(settlement:DockSettlement)=>{
    const record=parsePendingRecord(storage?.getItem("regear.whole-dock.pending-request"));
    if(record?.request===settlement.request&&record.intent===settlement.intent){
      presentedDockSettlement=settlement;
      // The active progress surface belongs to the Gamescope instance that
      // initiated the display handoff.  Its handle can survive after that
      // visible surface has gone away.  Once the correlated result arrives,
      // rebuild promptly on the replacement surface instead of waiting for
      // the coarse stale-handle fallback below.  A status surface must not
      // schedule itself again when it observes the same terminal result.
      if(operationKind==="active")schedulePendingStatusRebuild(1_500);
    }
  };
  const acknowledgeDockSettlement=()=>{
    if(!presentedDockSettlement)return;
    const record=parsePendingRecord(storage?.getItem("regear.whole-dock.pending-request"));
    if(record?.request===presentedDockSettlement.request&&record.intent===presentedDockSettlement.intent)
      storage?.removeItem("regear.whole-dock.pending-request");
    presentedDockSettlement=null;
  };
  const resolveAbsentDockReceipt=(settlement:DockSettlement)=>{
    const record=pendingDockRecord();
    if(record?.request!==settlement.request||record.intent!==settlement.intent)return;
    unplugWarning.retire(record.request);
    storage?.removeItem("regear.whole-dock.pending-request");
    if(presentedDockSettlement?.request===settlement.request)presentedDockSettlement=null;
    hideOperation();
  };
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
  const pendingDockRecord=()=>{
    try{return parsePendingRecord(storage?.getItem("regear.whole-dock.pending-request"));}
    catch{return null;}
  };
  const pendingDockIntent=()=>pendingDockRecord()?.intent??null;
  const warningBlocksDismiss=()=>{
    const warning=unplugWarning.read();
    const record=pendingDockRecord();
    return (warning.phase==="prompt"||warning.phase==="alarm")
      && warning.requestId===record?.request;
  };
  const warningSubscription=unplugWarning.subscribe(warning=>{
    warningAudio?.observe(warning);
    if((warning.phase==="prompt"||warning.phase==="alarm")&&warning.requestId===pendingDockRecord()?.request){
      scheduleOwnerWarningPoll();
      return;
    }
    if(warning.phase!=="cleared"||!warning.requestId)return;
    const record=pendingDockRecord();
    if(record?.request!==warning.requestId)return;
    storage?.removeItem("regear.whole-dock.pending-request");
    if(presentedDockSettlement?.request===warning.requestId)presentedDockSettlement=null;
    hideOperation();
  });
  const observePendingWarning=(status:any,record:ReturnType<typeof pendingDockRecord>)=>{
    if(!record||status?.schema_version!==1||status.request_id!==record.request)return;
    const deauthorized=status.software_down===true&&status.safe_to_unplug===false
      &&((status.code==="dock_teardown.software_down"&&status.ok===true&&status.busy===false)
        ||(record.intent==="shutdown"&&shutdownUnplugWaiting(status,record.request))
        ||(record.intent==="sleep"
          &&(status.code==="dock_power.unplug_required"
            ||status.code==="dock_power.unplug_request_expired")));
    if(status.busy===false&&!deauthorized&&status.physical_absence_verified!==true){
      unplugWarning.retire(record.request);
      return;
    }
    unplugWarning.observe({
      requestId:record.request,
      deauthorized,
      physicalAbsenceVerified:status.physical_absence_verified===true,
    });
  };
  const scheduleOwnerWarningPoll=(delay=2_000)=>{
    if(stopped||ownerWarningTimer!==null||ownerWarningPollInFlight)return;
    ownerWarningTimer=setPendingTimeout(()=>{ownerWarningTimer=null;void pollOwnerWarning();},delay);
  };
  const pollOwnerWarning=async()=>{
    if(stopped||ownerWarningPollInFlight)return;
    // A mounted WholeDockControl already owns the read cadence. The owner
    // takes over only after Decky tells us that surface closed.
    if(operation&&!ownerWarningReadAfterClose){scheduleOwnerWarningPoll();return;}
    ownerWarningReadAfterClose=false;
    const record=pendingDockRecord();
    if(!record)return;
    ownerWarningPollInFlight=true;
    try{
      const status=await readDockTrial("whole_dock_trial");
      if(stopped)return;
      const current=pendingDockRecord();
      if(!current||current.request!==record.request||current.intent!==record.intent)return;
      observePendingWarning(status,current);
      const warning=unplugWarning.read();
      if((warning.phase==="prompt"||warning.phase==="alarm"||warning.phase==="retired")
          &&warning.requestId===current.request&&!operation)resumePendingOperation();
    }catch{/* The durable receipt keeps the watcher eligible for the next read. */}
    finally{
      ownerWarningPollInFlight=false;
      if(!stopped&&pendingDockRecord())scheduleOwnerWarningPoll();
    }
  };
  function resumePendingOperation(){
    if(stopped||operation)return;
    const intent=pendingDockIntent();
    if(intent!=="disconnect"&&intent!=="disconnect_only"&&intent!=="sleep"&&intent!=="shutdown")return;
    const operationToken=++operationGeneration;
    const hide=()=>{if(operationGeneration===operationToken)hideOperation();};
    const hostClosed=()=>{
      if(operationGeneration!==operationToken)return;
      hide();
      if(!stopped&&warningBlocksDismiss()){
        resumePendingOperation();
        // Verify the first read after replacement even before its new child
        // has taken over polling. Subsequent owner reads remain single-flight.
        ownerWarningReadAfterClose=true;
        scheduleOwnerWarningPoll();
      }
    };
    const dismiss=()=>{if(warningBlocksDismiss())return;acknowledgeDockSettlement();hide();};
    const title=intent==="shutdown"?"Safe Disconnect + Shutdown status":intent==="sleep"?"Disconnect + Sleep status":"Safe Disconnect status";
    const opened=showModal(<EgpuConfirmModal strTitle={title} strOKButtonText="Hide" bAlertDialog onOK={dismiss} onCancel={dismiss} onEscKeypress={dismiss} className="rg-whole-dock-progress">
      <style>{`.rg-whole-dock-progress{position:fixed!important;left:50%!important;top:50%!important;right:auto!important;bottom:auto!important;margin:0!important;transform:translate(-50%,-50%)!important}`}</style>
      <WholeDockControl intent={intent} readCurrentSnapshot={readCurrentSnapshot} statusOnly onSettled={presentDockSettlement} onResolvedAbsent={resolveAbsentDockReceipt} unplugWarning={unplugWarning}/>
    </EgpuConfirmModal>,undefined,{fnOnClose:hostClosed,bNeverPopOut:true});
    if(operationGeneration!==operationToken){opened.Close();return;}operation=opened;operationKind="status";
    scheduleOwnerWarningPoll();
  }
  const schedulePendingStatusRebuild=(delay:number)=>{
    if(pendingStatusTimer!==null)clearPendingTimeout(pendingStatusTimer as never);
    pendingStatusTimer=setPendingTimeout(()=>{
      pendingStatusTimer=null;
      if(stopped||!pendingDockIntent())return;
      // A Gamescope display handoff can destroy the visible modal without
      // notifying this SharedJS owner. Replace only that stale presentation;
      // the reconstructed control is status-only and cannot replay the write.
      hideOperation();
      resumePendingOperation();
    },delay);
  };
  function disconnect(intent: DockIntent = "disconnect_only") {
    const allowed = !production || intent === "disconnect_only" || intent === "sleep" || intent === "shutdown";
    if(stopped||!modal||!allowed) return;
    if(warningBlocksDismiss()){
      // Re-activating the tile while the physical-unplug obligation is live
      // must not acknowledge its settlement or replace its exact receipt.
      if(!operation)resumePendingOperation();
      scheduleOwnerWarningPoll();
      return;
    }
    if(operationKind==="status"){
      const record=pendingDockRecord();
      const settled=presentedDockSettlement;
      if(!record){
        // The receipt was retired, but Gamescope did not notify this SharedJS
        // owner that its modal disappeared. Discard only the dead handle.
        presentedDockSettlement=null;
        hideOperation();
      } else if(settled?.request===record.request&&settled.intent===record.intent){
        // The previous result was rendered and correlated. This fresh explicit
        // press acknowledges it before starting a new request.
        acknowledgeDockSettlement();
        hideOperation();
      } else {
        // Never replace unresolved history with a new hardware write. Restore
        // its status and require another explicit press after it settles.
        hideOperation();
        resumePendingOperation();
        return;
      }
    }
    if(stopped||operation||!modal) return;
    // One explicit activation owns one request across React remounts. React can
    // retire the first control while its final freshness read is pending, so
    // keep the distinction between consumed and actually submitted here.
    let startState:"available"|"consumed"|"submitted"="available";
    const startRequest=Object.assign(
      ()=>{if(startState!=="available")return false;startState="consumed";return true;},
      {state:()=>startState,markSubmitted:()=>{if(startState==="consumed")startState="submitted";}}
    );
    const operationToken=++operationGeneration;
    const hide=()=>{if(operationGeneration===operationToken)hideOperation();};
    const hostClosed=()=>{
      if(operationGeneration!==operationToken)return;
      hide();
      if(!stopped&&warningBlocksDismiss()){
        resumePendingOperation();
        ownerWarningReadAfterClose=true;
        scheduleOwnerWarningPoll();
      }
    };
    // Hiding or destroying the progress surface is not acknowledgement of a
    // result. Gamescope tears this modal down during the very handoff the
    // operation performs, and treating that host-driven close as dismissal
    // erased the only durable receipt before the unplug popup could appear.
    // Only the later status-only surface may acknowledge the settlement.
    const dismiss=()=>{if(!warningBlocksDismiss())hide();};
    const title=intent==="shutdown"?"Safe Disconnect + Shutdown":intent==="sleep"?"Disconnect + Sleep":"Safe Disconnect";
    const opened=showModal(<EgpuConfirmModal strTitle={title} strOKButtonText="Hide" bAlertDialog onOK={dismiss} onCancel={dismiss} onEscKeypress={dismiss} className="rg-whole-dock-progress">
      <style>{`.rg-whole-dock-progress{position:fixed!important;left:50%!important;top:50%!important;right:auto!important;bottom:auto!important;margin:0!important;transform:translate(-50%,-50%)!important}`}</style>
      <WholeDockControl intent={intent} readCurrentSnapshot={readCurrentSnapshot} startRequest={startRequest} onSettled={presentDockSettlement} unplugWarning={unplugWarning}/>
    </EgpuConfirmModal>,undefined,{fnOnClose:hostClosed,bNeverPopOut:true});
    if(operationGeneration!==operationToken){opened.Close();return;}
    operation=opened;
    operationKind="active";
    scheduleOwnerWarningPoll();
    schedulePendingStatusRebuild(15_000);
  }
  function ShutdownStatus(){
    const state=useSyncExternalStore(runtimeDetails?.subscribe??noSubscribe,runtimeDetails?.read??noRuntimeDetails,runtimeDetails?.read??noRuntimeDetails);
    return <p role="status">{state?.shutdown?.message||"Checking shutdown readiness…"}</p>;
  }
  function shutdown(){
    if(production||stopped||operation||!modal||!runtimeDetails?.read()?.shutdown?.available)return;
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
    useEffect(() => () => { if (generation === token) { hideOperation();modal = null; generation++; utilities?.stop(); visibility.set(false);if(pendingDockIntent())scheduleOwnerWarningPoll(); } }, [token]);
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
    const displayTarget=displayTargetActionTile(runtimeState?.displayAction);
    const tiles=mappedTiles&&runtimeDetails?{...mappedTiles,egpu:mappedTiles.egpu?.map(tile=>tile.id==="switch-handheld"?displayTarget:tile),settings:mappedTiles.settings?.map(tile=>tile.id==="diagnostics"?{...tile,value:runtimeState?"Open":"Waiting",detail:"Status, recovery and support"}:tile.id==="about"?{...tile,value:version,detail:"Version and credits"}:tile.id==="quick-actions"?{...tile,value:"Customize",detail:"Focus a Quick Access button and tap Y"}:tile)}:mappedTiles;
    const productionTiles=production?productionEgpuTiles({quick:rawTiles?.quick,egpu:tiles?.egpu?.filter(tile=>tile.id==="display-target"||tile.id==="disconnect"||tile.id==="disconnect-sleep"||tile.id==="disconnect-shutdown")}):undefined;
    const unavailable={...unavailableTestActions,...(runtimeDetails?offlineUnavailableActions:{})};
    if(runtimeDetails){if(!runtimeState?.shutdown?.available)unavailable["portable-shutdown"]=runtimeState?.shutdown?.reason??"Current status unavailable";delete unavailable["switch-handheld"];if(runtimeState?.displayAction.available)delete unavailable["display-target"];else unavailable["display-target"]=runtimeState?.displayAction.reason??"Current display status unavailable";delete unavailable["disconnect-sleep"];}
    // Defaults to the route the 0.3.98 golden cycle actually ran. The control
    // was built for a changing intent prop -- it re-checks the intent after
    // every await and recovers a pending record's intent from storage -- so a
    // flip mid-confirmation aborts cleanly rather than dispatching the wrong route.
    const [dockIntent, setDockIntent] = useState<DockIntent>("disconnect_only");
    const utilityReadings = useSyncExternalStore(utilities?.subscribe ?? noSubscribe, utilities?.read ?? noUtilities, utilities?.read ?? noUtilities);
    return <ExpandedCommandCenter policy={policy} onClose={close} native onFeedback={playMenuFeedback} onDisconnect={disconnect} disconnectControl={
      <Focusable>
        {!production && <Dropdown menuLabel="Dock action" rgOptions={dockIntentOptions} selectedOption={dockIntent}
          onChange={option => { if (dockIntentOptions.some(item => item.data === option.data)) setDockIntent(option.data as DockIntent); }}/>}
        <WholeDockControl intent={production ? "disconnect_only" : dockIntent} readCurrentSnapshot={readCurrentSnapshot} onSettled={presentDockSettlement} unplugWarning={unplugWarning}/>
      </Focusable>
    } directions={{up:GamepadButton.DIR_UP,down:GamepadButton.DIR_DOWN,left:GamepadButton.DIR_LEFT,right:GamepadButton.DIR_RIGHT}} unavailableActions={unavailable} onAction={(_tab,tile)=>{if(tile.id==="display-target"){runtimeDetails?.requestDisplayTarget();return true;}if(tile.id==="disconnect-sleep"){disconnect("sleep");return true;}if(tile.id==="disconnect-shutdown"){disconnect("shutdown");return true;}if(production)return false;if(tile.id==="portable-shutdown"){shutdown();return true;}if(tile.id==="switch-handheld"){runtimeDetails?.requestHandheld();return true;}return false;}} layoutStorage={production ? undefined : storage} editButtons={production ? undefined : {y:GamepadButton.OPTIONS}} primitives={{ Button: NativeMenuButton, Focusable }} settings={<Settings/>} tiles={production ? productionTiles : runtimeDetails?{...tiles,egpu:[...(tiles?.egpu??[]),{id:"portable-shutdown",title:"Shutdown",value:runtimeState?.shutdown?.pending?"Pending":runtimeState?.shutdown?.available?"Ready":"Unavailable",detail:runtimeState?.shutdown?.reason??"Current status unavailable"}],offline:offlineTabTiles,settings:[...(tiles?.settings??[]).filter(tile=>tile.id==='diagnostics'),{id:'reset-layout',title:'Reset Layout',value:'Configure',detail:'Restore default card positions'},{id:'tutorials',title:'Tutorials',value:'Open',detail:'Connection, disconnect and help'},{id:'about',title:'About',value:version,detail:'Version and credits'}]}:tiles} renderDetail={production ? ((tab,tile)=>tab==="egpu"&&(tile.id==="egpu"||tile.id==="disconnect") ? renderDetail?.(tab,tile) : null) : runtimeDetails?((tab,tile)=>tab==='settings'&&tile.id==='tutorials'?<Tutorials/>:renderDetail?.(tab,tile)):renderDetail} catalogReadings={production ? undefined : rawTiles} utilityReadings={utilityReadings} onUtilityRequest={utilities ? (id, percent) => {
      if (generation !== token || stopped) return Promise.reject(new Error("Menu closed"));
      if (production && id !== "brightness" && id !== "volume") throw new Error("Control unavailable");
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
    // A player may hide the status surface before the terminal read arrives.
    // Keep the durable receipt and restore that surface on the next explicit
    // Command Center open; this is presentation only and never dispatches.
    resumePendingOperation();
    if (operation) return;
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
  // Gamescope may replace the entire Decky/React surface while the backend
  // continues a guarded dock request. Reconstruct only its read-only status
  // surface from the durable request record; never replay the action.
  resumePendingOperation();
  if(pendingDockIntent())scheduleOwnerWarningPoll();
  // Decky can accept a modal before the replacement Gamescope surface is
  // visible. One deferred reconstruction makes the pending receipt visible
  // without polling or resubmitting the operation.
  if(pendingDockIntent())schedulePendingStatusRebuild(1_500);
  // A full Steam/Gamescope replacement can lose the WebKit receipt even while
  // the backend retains the exact terminal result. Recover presentation only:
  // the helper performs one read and can write a receipt, but never dispatches
  // a disconnect or completion action.
  const recoverMissingDockReceipt=()=>{
    if(stopped||pendingDockIntent())return;
    void recoverTerminalDockReceipt(storage).then(settlement=>{
      if(stopped)return;
      if(!settlement){
        if(++recoveryAttempts<160&&!pendingDockIntent())
          recoveryTimer=setPendingTimeout(()=>{recoveryTimer=null;recoverMissingDockReceipt();},2_000);
        return;
      }
      const record=pendingDockRecord();
      if(record?.intent!==settlement.intent||record.request!==settlement.request)return;
      resumePendingOperation();
      scheduleOwnerWarningPoll();
      schedulePendingStatusRebuild(1_500);
    });
  };
  recoverMissingDockReceipt();
  return { open, disconnect, Settings, visibility: visibility.source, available: shortcut.available, stop() { stopped = true; warningSubscription(); warningAudio?.dispose(); unplugWarning.stop(); if(recoveryTimer!==null)clearPendingTimeout(recoveryTimer as never);recoveryTimer=null;if(pendingStatusTimer!==null)clearPendingTimeout(pendingStatusTimer as never);pendingStatusTimer=null;if(ownerWarningTimer!==null)clearPendingTimeout(ownerWarningTimer as never);ownerWarningTimer=null;shortcut.stop(); close(); } };
}
