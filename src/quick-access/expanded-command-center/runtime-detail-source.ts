import type { ReactNode } from "react";

export type RuntimeDetailId="egpu"|"egpu-config"|"diagnostics"|"display";
export type RuntimeDetailState={
  views:Record<RuntimeDetailId,ReactNode>;
  handheld:{available:boolean;reason:string;request():void};
  shutdown?:{available:boolean;reason:string;pending:boolean;message:string;request():void};
};
type Selection={root:RuntimeDetailId;current:RuntimeDetailId;token:number};

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
    requestHandheld(){if(!stopped&&state?.handheld.available)state.handheld.request();},
  };
  return {source,publish(next:RuntimeDetailState|null){if(!stopped){state=next;notify();}},stop(){stopped=true;state=null;selection=null;token++;notify();selectionListeners.forEach(fn=>fn());}};
}
export type RuntimeDetailSource=ReturnType<typeof createRuntimeDetailPublisher>["source"];
