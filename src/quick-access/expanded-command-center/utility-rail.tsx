import { useRef, useState } from "react";
import type { ElementType, KeyboardEvent } from "react";
import { CommandCenterIcon } from "../command-center-icons";
import { defaultUtilityLayout } from "./utility-layout";
import type { UtilityId, UtilityPlacement } from "./utility-layout";

export type UtilityReading = { available:boolean; value:string; percent?:number; pending?:boolean; reason?:string };
export type UtilityRailProps = {
  side:"left"|"right";
  layout?:readonly UtilityPlacement[];
  readings?:Partial<Record<UtilityId,UtilityReading>>;
  onRequest?:(id:UtilityId, percent?:number)=>Promise<void>;
  Button?:ElementType;
  Focusable?:ElementType;
  directions?: Record<"up"|"down"|"left"|"right",number>;
  onReturnToGrid?:()=>void;
};

const labels:Record<UtilityId,string> = {
  brightness:"Brightness", volume:"Volume", mic:"Mic mute", recording:"Record",
  overlay:"Overlay", audio:"Audio output", wifi:"Wi-Fi",
};

const railStyles = `
.rg-utility-rail{display:flex;flex-direction:column;color:#f4f7fb;font-family:Arial,sans-serif;min-width:0}
.rg-utility-control{position:relative;min-width:0;margin:0;border:1px solid #315c75;border-radius:10px;background:#0b2232;padding:6px;text-align:center;font:inherit;color:inherit;overflow:hidden}
.rg-utility-control.gpfocus,.rg-utility-control:focus-visible,.rg-utility-control:focus-within{outline:2px solid #39d8ff;outline-offset:-2px;border-color:#39d8ff;background:#12364b}
.rg-utility-icon{display:grid;place-items:center;margin:0 auto 3px;color:#c9ecff}.rg-utility-icon svg{display:block;width:21px;height:21px}
.rg-utility-label{display:block;font-size:10px;font-weight:700;line-height:1.1}.rg-utility-value{display:block;font-size:8px;line-height:1.15;color:#87aabd;margin-top:2px}
.rg-utility-slider{display:flex;flex:0 0 auto;min-height:0;flex-direction:column;align-items:center;justify-content:center;gap:2px;background:transparent;border:0;border-radius:0;box-shadow:none;padding:3px 0;overflow:visible}
.rg-utility-slider+.rg-utility-slider{border-top:1px solid #294f68;padding-top:5px}.rg-utility-slider .rg-utility-icon{margin-bottom:0}.rg-utility-slider .rg-utility-icon svg{width:17px;height:17px}.rg-utility-slider input{writing-mode:vertical-lr;direction:rtl;width:17px;height:clamp(40px,7vh,56px);margin:1px 0;accent-color:#39d8ff}
.rg-utility-rail[data-utility-side=left]{gap:0;padding:4px 2px;border:1px solid #294f68;border-radius:10px;background:#071825e8}.rg-utility-rail[data-utility-side=left] .rg-utility-label{display:none}.rg-utility-rail[data-utility-side=left] .rg-utility-value{font-size:7px;margin-top:2px}
.rg-utility-rail[data-utility-side=right]{gap:5px;overflow:hidden}.rg-utility-rail[data-utility-side=right] .rg-utility-control{display:flex;flex:0 1 auto;flex-direction:column;align-items:center;justify-content:center;height:clamp(46px,9vh,62px);min-height:0;max-height:62px;padding:4px 2px}.rg-utility-rail[data-utility-side=right] .rg-utility-icon{width:25px;height:25px;border-radius:7px;border:1px solid #315c75;background:#0a2232}.rg-utility-rail[data-utility-side=right] .rg-utility-icon svg{width:16px;height:16px}.rg-utility-rail[data-utility-side=right] .rg-utility-label{font-size:8px}.rg-utility-rail[data-utility-side=right] .rg-utility-value{font-size:6px}
@media(max-height:520px){.rg-utility-slider input{height:34px;width:15px}.rg-utility-rail[data-utility-side=right]{gap:3px}.rg-utility-rail[data-utility-side=right] .rg-utility-control{height:42px;max-height:42px}}
`;

export function UtilityRail({side,layout=defaultUtilityLayout,readings={},onRequest,Button="button",Focusable="aside",directions,onReturnToGrid}:UtilityRailProps) {
  const busy=useRef(new Set<UtilityId>());
  const queued=useRef(new Map<UtilityId,number>());
  const [pending,setPending]=useState<UtilityId[]>([]);
  const [errors,setErrors]=useState<Partial<Record<UtilityId,string>>>({});
  const requested=useRef(new Map<UtilityId,number>());

  async function run(id:UtilityId,percent?:number){
    if(!onRequest||!readings[id]?.available||readings[id]?.pending)return;
    busy.current.add(id); setPending([...busy.current]); setErrors(c=>({...c,[id]:undefined}));
    try{ await onRequest(id,percent); }
    catch{ setErrors(c=>({...c,[id]:"Could not apply. Try again."})); }
    finally{
      const next=queued.current.get(id); queued.current.delete(id); busy.current.delete(id); setPending([...busy.current]);
      if(next!==undefined&&next!==percent) void run(id,next);
      else requested.current.delete(id);
    }
  }
  function request(id:UtilityId,percent?:number){
    if(!onRequest||!readings[id]?.available||readings[id]?.pending)return;
    if(percent!==undefined) requested.current.set(id,percent);
    if(busy.current.has(id)){ if(percent!==undefined) queued.current.set(id,percent); return; }
    void run(id,percent);
  }
  function move(event: {target: EventTarget|null; currentTarget: EventTarget|null; preventDefault():void;stopPropagation():void}, direction:string, id:UtilityId) {
    const wrapper=event.currentTarget as HTMLElement;
    const input=wrapper.querySelector<HTMLInputElement>('input');
    if(direction==='right') { event.preventDefault();event.stopPropagation();onReturnToGrid?.();return; }
    if(direction!=='up'&&direction!=='down') return;
    event.preventDefault();event.stopPropagation();
    if(input && (event.target===input || wrapper.ownerDocument?.activeElement===input) && !input.disabled) {
      const value=Math.max(0,Math.min(100,(requested.current.get(id)??Number(input.value))+(direction==='up'?1:-1)));
      request(id,value);
    } else {
      const wrappers=Array.from(wrapper.parentElement?.querySelectorAll<HTMLElement>('[data-utility-slider]')??[]);
      wrappers[wrappers.indexOf(wrapper)+(direction==='down'?1:-1)]?.focus();
    }
  }
  function navigate(event:KeyboardEvent<HTMLElement>){
    if(event.target instanceof HTMLInputElement || !["ArrowUp","ArrowDown"].includes(event.key)) return;
    const controls=Array.from(event.currentTarget.querySelectorAll<HTMLElement>("button:not(:disabled),input:not(:disabled)"));
    const index=controls.indexOf(document.activeElement as HTMLElement);
    const next=controls[index+(event.key==="ArrowDown"?1:-1)];
    if(next){ event.preventDefault(); event.stopPropagation(); next.focus(); }
  }

  return <Focusable flow-children="vertical" noFocusRing className="rg-utility-rail" data-utility-side={side} aria-label={`${side} quick controls`} onKeyDown={navigate}>
    <style>{railStyles}</style>
    {layout.filter(i=>i.side===side).map(({id})=>{
      const reading=readings[id], waiting=pending.includes(id)||reading?.pending;
      const isSlider=id==="brightness"||id==="volume";
      const valid=typeof reading?.percent==="number"&&Number.isFinite(reading.percent)&&reading.percent>=0&&reading.percent<=100;
      const disabled=!onRequest||!reading?.available||Boolean(reading?.pending)||(isSlider&&!valid);
      const status=errors[id]??(waiting?"Applying…":reading?.value??"Unavailable");
      const reason=reading?.reason??(!reading?.available?"No verified capability":undefined);
      return isSlider ? <Focusable key={id} tabIndex={0} data-utility-slider data-utility-id={id} data-ec-control={`utility-${id}`} className="rg-utility-control rg-utility-slider" title={reason} aria-label={labels[id]} aria-busy={waiting||undefined}
        onGamepadDirection={directions ? (event:CustomEvent<{button:number}>)=>move(event,Object.keys(directions).find(key=>directions[key as keyof typeof directions]===event.detail.button)??'',id) : undefined}
        onOKButton={(event:CustomEvent)=>{event.preventDefault();event.stopPropagation();(event.currentTarget as HTMLElement).querySelector<HTMLInputElement>('input:not(:disabled)')?.focus();}}
        onCancelButton={(event:CustomEvent)=>{const wrapper=event.currentTarget as HTMLElement;if((event.target as HTMLElement).tagName==='INPUT'||wrapper.ownerDocument?.activeElement===wrapper.querySelector('input')){event.preventDefault();event.stopPropagation();wrapper.focus();}}}
        onKeyDown={(event:KeyboardEvent<HTMLElement>)=>{if(event.key.startsWith('Arrow')) move(event,event.key.slice(5).toLowerCase(),id); else if(event.key==='Enter'){event.preventDefault();event.stopPropagation();event.currentTarget.querySelector<HTMLInputElement>('input:not(:disabled)')?.focus();} else if(event.key==='Escape'&&(event.target as HTMLElement).tagName==='INPUT'){event.preventDefault();event.stopPropagation();event.currentTarget.focus();}}}>
        <span className="rg-utility-icon"><UtilityIcon id={id}/></span>
        <span className="rg-utility-label">{labels[id]}</span>
        <input type="range" min={0} max={100} step={1} aria-label={labels[id]} aria-orientation="vertical" aria-valuetext={valid?status:"Unknown"} value={valid?reading!.percent:0} disabled={disabled} onChange={e=>request(id,Number(e.currentTarget.value))}/>
        <span className="rg-utility-value" role="status">{status}</span>
      </Focusable> : <Button key={id} type="button" data-utility-id={id} data-ec-control={`utility-${id}`} className="rg-utility-control" disabled={disabled||waiting} title={reason} aria-label={`${labels[id]}: ${status}`} aria-busy={waiting||undefined} onClick={()=>request(id)}>
        <span className="rg-utility-icon"><UtilityIcon id={id}/></span>
        <span className="rg-utility-label">{labels[id]}</span>
        <span className="rg-utility-value" role="status">{status}</span>
      </Button>;
    })}
  </Focusable>;
}

function UtilityIcon({id}:{id:UtilityId}){
  if(id==="overlay") return <CommandCenterIcon id="performance" size={24}/>;
  const paths:Partial<Record<UtilityId,string>>={
    brightness:"M32 12v7M32 45v7M12 32h7M45 32h7M18 18l5 5M41 41l5 5M46 18l-5 5M23 41l-5 5M32 23a9 9 0 1 1 0 18 9 9 0 0 1 0-18Z",
    volume:"M10 26h10l14-12v36L20 38H10ZM43 23a14 14 0 0 1 0 18M49 15a25 25 0 0 1 0 34",
    mic:"M25 11a7 7 0 0 1 14 0v20a7 7 0 0 1-14 0ZM18 28v3a14 14 0 0 0 28 0v-3M32 45v10M23 55h18",
    recording:"M32 18a14 14 0 1 1 0 28 14 14 0 0 1 0-28ZM32 24a8 8 0 1 1 0 16 8 8 0 0 1 0-16Z",
    audio:"M10 26h10l14-12v36L20 38H10ZM43 23a14 14 0 0 1 0 18M49 15a25 25 0 0 1 0 34",
    wifi:"M8 23a36 36 0 0 1 48 0M17 33a23 23 0 0 1 30 0M25 43a11 11 0 0 1 14 0M32 52h.01",
  };
  return <svg width={24} height={24} viewBox="0 0 64 64" fill="none" aria-hidden="true"><path d={paths[id]} stroke="currentColor" strokeWidth={3.5} strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
