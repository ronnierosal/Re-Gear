import { useEffect,useSyncExternalStore } from "react";
import { ButtonItem,Focusable } from "@decky/ui";
import type { RuntimeDetailId,RuntimeDetailSource } from "./runtime-detail-source";
import type { Tab,Tile } from "./model";

export function RuntimeDetail({source,kind}:{source:RuntimeDetailSource;kind:RuntimeDetailId}){
  const state=useSyncExternalStore(source.subscribe,source.read,source.read);
  const selection=useSyncExternalStore(source.subscribeSelection,source.readSelection,source.readSelection);
  useEffect(()=>source.enter(kind),[source,kind]);
  const current=selection?.root===kind?selection.current:kind;
  const back=()=>source.navigate(kind);
  return <Focusable flow-children="vertical" noFocusRing {...(current!==kind?{onCancelButton:(event:CustomEvent)=>{event.preventDefault();event.stopPropagation();back();}}:{})}>
    {current!==kind&&<ButtonItem layout="below" onClick={back}>Back</ButtonItem>}
    {state?state.views[current]:<p role="status">Current status unavailable. Waiting for the runtime.</p>}
  </Focusable>;
}
export function runtimeDetailKind(tab:Tab,id:string):RuntimeDetailId|null{
  if(tab==="settings"&&id==="diagnostics")return "diagnostics";
  if((tab==="quick"||tab==="egpu")&&id==="egpu")return "egpu";
  if(tab==="quick"&&id==="display")return "display";
  return null;
}
export function createRuntimeDetailRenderer(source:RuntimeDetailSource){
  return (tab:Tab,tile:Tile)=>{const kind=runtimeDetailKind(tab,tile.id);return kind?<RuntimeDetail source={source} kind={kind}/>:null;};
}
