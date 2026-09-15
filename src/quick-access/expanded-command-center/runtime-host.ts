import { createElement,useEffect,useState,type ComponentType } from "react";

export type RuntimeOwner = { active:boolean; generation:number; stopped:boolean };
export type RuntimeRouter = {
  addGlobalComponent(name:string,component:ComponentType):void;
  removeGlobalComponent(name:string):void;
};

/** One plugin-lifetime owner in Decky's existing Steam React tree, not QAM. */
export function registerRuntimeHost(router:RuntimeRouter,name:string,component:ComponentType,owner:RuntimeOwner){
  let stopped=false;
  let mounted=false;
  function GlobalRuntime(){
    const [owns,setOwns]=useState(false);
    useEffect(()=>{
      if(stopped||owner.stopped||mounted)return;
      mounted=true;setOwns(true);
      return()=>{mounted=false;owner.active=false;owner.generation++;};
    },[]);
    return owns&&!stopped&&!owner.stopped?createElement(component):null;
  }
  try{router.addGlobalComponent(name,GlobalRuntime);}
  catch(error){stopped=true;owner.stopped=true;owner.active=false;owner.generation++;try{router.removeGlobalComponent(name);}catch{}throw error;}
  return ()=>{
    if(stopped)return;
    stopped=true;
    // React may commit removal later. Invalidate pending reads synchronously.
    owner.stopped=true;owner.active=false;owner.generation++;
    router.removeGlobalComponent(name);
  };
}
