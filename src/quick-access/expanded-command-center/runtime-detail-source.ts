import type { ReactNode } from "react";

export type RuntimeDetailId="egpu"|"egpu-config"|"diagnostics"|"display";
export type RuntimeDetailState={
  views:Record<RuntimeDetailId,ReactNode>;
  displayAction:{target:"ally"|"tv"|null;available:boolean;reason:string;egpuConnected?:boolean|null;request():void};
  shutdown?:{available:boolean;reason:string;pending:boolean;message:string;request():void};
  sleepConnected?:{available:boolean;reason:string;request():void};
};
type Selection={root:RuntimeDetailId;current:RuntimeDetailId;token:number};

// Read only own data fields. An accessor, inherited field or nonplain shape is
// not snapshot evidence, and must not execute while composing a status label.
function ownData(value: unknown, name: string): unknown {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return undefined;
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) return undefined;
  const descriptor = Object.getOwnPropertyDescriptor(value, name);
  return descriptor && "value" in descriptor ? descriptor.value : undefined;
}

/** Attachment + current link only; never rendering, display or unplug authority. */
export function egpuConnectionEvidence(payload: unknown, fresh: boolean): boolean | null {
  if (fresh !== true) return null;
  try {
    const snapshot = ownData(payload, "snapshot");
    if (ownData(snapshot, "schema_version") !== 3) return null;
    const link = ownData(snapshot, "egpu_link");
    if (ownData(link, "applicable") !== true || ownData(link, "error") !== "") return null;
    const state = ownData(link, "state"), confidence = ownData(link, "confidence");
    // This negative is only a verified link reading, not cable/USB4 absence.
    if (state === "down") return confidence === "verified" ? false : null;
    if (state !== "up" || (confidence !== "observed" && confidence !== "verified")) return null;
    const speed = ownData(link, "speed_gtps"), width = ownData(link, "width_lanes");
    if (typeof speed !== "number" || !Number.isFinite(speed) || speed <= 0
      || typeof width !== "number" || !Number.isInteger(width) || width <= 0) return null;
    const profiles = ownData(ownData(payload, "diagnostics"), "hardware_profiles");
    if (ownData(snapshot, "support_tier") !== "certified" || ownData(profiles, "schema_version") !== 1
      || ownData(ownData(profiles, "egpu"), "status") !== "exact") return null;
    const gpus = ownData(snapshot, "gpus");
    if (!Array.isArray(gpus) || gpus.length === 0 || gpus.length > 128) return null;
    let external = 0;
    for (let i = 0; i < gpus.length; i++) {
      const descriptor = Object.getOwnPropertyDescriptor(gpus, String(i));
      if (!descriptor || !("value" in descriptor)) return null;
      const gpu = descriptor.value, role = ownData(gpu, "role");
      if (role !== "internal" && role !== "external") return null;
      const present = ownData(gpu, "present"), grade = ownData(gpu, "confidence");
      if (typeof present !== "boolean" || (grade !== "observed" && grade !== "verified")) return null;
      if (role === "external") {
        if (present !== true || grade !== "verified") return null;
        external++;
      }
    }
    return external === 1 ? true : null;
  } catch { return null; }
}

/** Live nodes and existing callbacks only. Never collects or persists state. */
export function createRuntimeDetailPublisher(){
  let state:RuntimeDetailState|null=null,selection:Selection|null=null,token=0,stopped=false;
  const listeners=new Set<()=>void>(),selectionListeners=new Set<()=>void>();
  const notify=()=>listeners.forEach(fn=>fn());
  const source={
    read:()=>state,
    subscribe:(fn:()=>void)=>{listeners.add(fn);return()=>{listeners.delete(fn);};},
    readSelection:()=>selection,
    subscribeSelection:(fn:()=>void)=>{selectionListeners.add(fn);return()=>{selectionListeners.delete(fn);};},
    enter(root:RuntimeDetailId){
      if(stopped)return()=>{};
      const ticket=++token;selection={root,current:root,token:ticket};selectionListeners.forEach(fn=>fn());
      return()=>{if(selection?.token===ticket){selection=null;selectionListeners.forEach(fn=>fn());}};
    },
    navigate(current:RuntimeDetailId){if(selection&&!stopped){selection={...selection,current};selectionListeners.forEach(fn=>fn());}},
    requestShutdown(){if(!stopped&&state?.shutdown?.available)state.shutdown.request();},
    requestDisplayTarget(){if(!stopped&&state?.displayAction.available)state.displayAction.request();},
    requestHandheld(){if(!stopped&&state?.displayAction.target==="ally"&&state.displayAction.available)state.displayAction.request();},
    requestSleepConnected(){if(!stopped&&state?.sleepConnected?.available)state.sleepConnected.request();},
  };
  return {source,publish(next:RuntimeDetailState|null){if(!stopped){state=next;notify();}},stop(){stopped=true;state=null;selection=null;token++;notify();selectionListeners.forEach(fn=>fn());}};
}
export type RuntimeDetailSource=ReturnType<typeof createRuntimeDetailPublisher>["source"];
