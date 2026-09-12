import { useRef, useState } from "react";
import type { ElementType, KeyboardEvent } from "react";
import { CommandCenterIcon } from "../command-center-icons";
import { defaultUtilityLayout } from "./utility-layout";
import type { UtilityId, UtilityPlacement } from "./utility-layout";

export type UtilityReading = {
  /** Only verified capabilities with current readings may be enabled. */
  available: boolean;
  value: string;
  percent?: number;
  pending?: boolean;
  reason?: string;
};
const labels: Record<UtilityId,string> = {
  brightness:"Brightness",volume:"Volume",mic:"Mic mute",recording:"Record",
  overlay:"Overlay",audio:"Audio output",wifi:"Wi-Fi",
};
const railStyles = `
.rg-utility-rail{display:flex;flex-direction:column;gap:8px;color:#f4f7fb;font-family:Arial,sans-serif;min-width:0}
.rg-utility-control{position:relative;min-width:0;margin:0;border:1px solid #315c75;border-radius:12px;background:linear-gradient(150deg,#102a3b,#071a29);padding:8px;text-align:center;font:inherit;color:inherit;box-shadow:inset 0 1px 0 #ffffff08;overflow:hidden}
.rg-utility-control button{font:inherit;color:inherit}
.rg-utility-control.gpfocus,.rg-utility-control:focus-visible,.rg-utility-control:focus-within{outline:2px solid #39d8ff;outline-offset:-2px;border-color:#39d8ff;box-shadow:0 0 0 1px #39d8ff22,inset 0 1px 0 #ffffff10}
.rg-utility-control:disabled{cursor:default;color:#91b3cd;opacity:.78}
.rg-utility-icon{display:grid;place-items:center;margin:0 auto 5px;color:#c4e7f8}.rg-utility-icon svg{display:block;width:24px;height:24px}
.rg-utility-label{display:block;font-size:12px;font-weight:650;line-height:1.2;overflow-wrap:normal;word-break:normal}
.rg-utility-value{display:block;font-size:10px;line-height:1.25;color:#8fb6cf;margin-top:5px;overflow-wrap:normal;word-break:normal}
.rg-utility-slider{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;background:transparent;border:0;border-radius:0;box-shadow:none;padding:5px 3px;overflow:visible}
.rg-utility-slider+.rg-utility-slider{border-top:1px solid #294f68;padding-top:10px}
.rg-utility-slider .rg-utility-icon{margin-bottom:0}
.rg-utility-slider input{writing-mode:vertical-lr;direction:rtl;width:24px;height:clamp(54px,13vh,88px);margin:2px 0;accent-color:#39d8ff}
.rg-utility-rail[data-utility-side=left]{gap:5px;padding:8px 6px;border:1px solid #294f68;border-radius:13px;background:#071825d9;box-shadow:inset 0 1px 0 #ffffff08}
.rg-utility-rail[data-utility-side=right]{gap:7px}
.rg-utility-rail[data-utility-side=right] .rg-utility-control{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:clamp(60px,15vh,96px);padding:8px 5px}
.rg-utility-rail[data-utility-side=right] .rg-utility-icon{margin-bottom:5px}
.rg-utility-rail[data-utility-side=right] .rg-utility-value{font-size:9px;margin-top:3px;max-width:100%}
@media(max-height:520px){
  .rg-utility-control{border-radius:10px;padding:5px}.rg-utility-icon svg{width:20px;height:20px}.rg-utility-label{font-size:10px}.rg-utility-value{font-size:8px;margin-top:2px}
  .rg-utility-slider{gap:2px;padding:3px 2px}.rg-utility-slider+.rg-utility-slider{padding-top:6px}.rg-utility-slider input{height:52px;width:20px}
  .rg-utility-rail[data-utility-side=right]{gap:5px}.rg-utility-rail[data-utility-side=right] .rg-utility-control{min-height:58px;padding:4px}
}
`;

/** Reusable presentation. Reads, persistence and hardware dispatch stay owned by
 * the application; unavailable controls remain visible rather than pretending a
 * capability exists. Recording's adapter must dismiss Command Center first. */
export function UtilityRail({side, layout = defaultUtilityLayout, readings = {}, onRequest, Button = "button", Focusable = "aside"}: {
  side: "left" | "right";
  layout?: readonly UtilityPlacement[];
  readings?: Partial<Record<UtilityId,UtilityReading>>;
  onRequest?: (id: UtilityId, percent?: number) => Promise<void>;
  Button?: ElementType;
  Focusable?: ElementType;
}) {
  const busy = useRef(new Set<UtilityId>());
  const [pending,setPending] = useState<UtilityId[]>([]);
  const [errors,setErrors] = useState<Partial<Record<UtilityId,string>>>({});
  async function request(id: UtilityId, percent?: number) {
    if (!onRequest || !readings[id]?.available || readings[id]?.pending || busy.current.has(id)) return;
    busy.current.add(id); setPending([...busy.current]);
    setErrors(current => ({...current,[id]:undefined}));
    try { await onRequest(id,percent); }
    catch { setErrors(current => ({...current,[id]:"Could not apply. Try again."})); }
    finally { busy.current.delete(id); setPending([...busy.current]); }
  }
  // Range inputs keep their native arrow behavior. Arrow keys on actions move
  // through this rail; the shell retains cross-region/controller navigation.
  function navigate(event: KeyboardEvent<HTMLElement>) {
    if (event.target instanceof HTMLInputElement || !["ArrowUp","ArrowDown"].includes(event.key)) return;
    const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("button:not(:disabled),input:not(:disabled)"));
    const index = controls.indexOf(document.activeElement as HTMLElement);
    const next = controls[index + (event.key === "ArrowDown" ? 1 : -1)];
    if (next) { event.preventDefault(); event.stopPropagation(); next.focus(); }
  }
  return <Focusable flow-children="vertical" noFocusRing className="rg-utility-rail" data-utility-side={side} aria-label={`${side} quick controls`} onKeyDown={navigate}>
    <style>{railStyles}</style>
    {layout.filter(item => item.side === side).map(({id}) => {
      const reading = readings[id];
      const waiting = pending.includes(id) || reading?.pending;
      const isSlider = id === "brightness" || id === "volume";
      const validPercent = typeof reading?.percent === "number" && Number.isFinite(reading.percent) && reading.percent >= 0 && reading.percent <= 100;
      const disabled = !onRequest || !reading?.available || waiting || (isSlider && !validPercent);
      const status = errors[id] ?? (waiting ? "Applying…" : reading?.value ?? "Unavailable");
      const reason = reading?.reason ?? (!reading?.available ? "No verified capability" : undefined);
      return isSlider ? <label key={id} data-utility-id={id} className="rg-utility-control rg-utility-slider" title={reason}>
        <span className="rg-utility-icon"><UtilityIcon id={id}/></span>
        <span className="rg-utility-label">{labels[id]}</span>
        <input type="range" min={0} max={100} step={1} aria-label={labels[id]} aria-orientation="vertical"
          aria-valuetext={validPercent ? status : "Unknown"} value={validPercent ? reading!.percent : 0} disabled={disabled}
          onChange={event => void request(id,Number(event.currentTarget.value))}/>
        <span className="rg-utility-value" role="status">{status}</span>
      </label> : <Button key={id} type="button" data-utility-id={id} className="rg-utility-control" disabled={disabled} title={reason}
        aria-label={`${labels[id]}: ${status}`} onClick={() => void request(id)}>
        <span className="rg-utility-icon"><UtilityIcon id={id}/></span>
        <span className="rg-utility-label">{labels[id]}</span>
        <span className="rg-utility-value" role="status">{status}</span>
      </Button>;
    })}
  </Focusable>;
}

function UtilityIcon({id}: {id: UtilityId}) {
  if(id === "overlay") return <CommandCenterIcon id="performance" size={24}/>;
  const paths: Partial<Record<UtilityId,string>> = {
    brightness:"M32 12v7M32 45v7M12 32h7M45 32h7M18 18l5 5M41 41l5 5M46 18l-5 5M23 41l-5 5M32 23a9 9 0 1 1 0 18 9 9 0 0 1 0-18Z",
    volume:"M10 26h10l14-12v36L20 38H10ZM43 23a14 14 0 0 1 0 18M49 15a25 25 0 0 1 0 34",
    mic:"M25 11a7 7 0 0 1 14 0v20a7 7 0 0 1-14 0ZM18 28v3a14 14 0 0 0 28 0v-3M32 45v10M23 55h18",
    recording:"M32 18a14 14 0 1 1 0 28 14 14 0 0 1 0-28ZM32 24a8 8 0 1 1 0 16 8 8 0 0 1 0-16Z",
    audio:"M10 26h10l14-12v36L20 38H10ZM43 23a14 14 0 0 1 0 18M49 15a25 25 0 0 1 0 34",
    wifi:"M8 23a36 36 0 0 1 48 0M17 33a23 23 0 0 1 30 0M25 43a11 11 0 0 1 14 0M32 52h.01",
  };
  return <svg width={24} height={24} viewBox="0 0 64 64" fill="none" aria-hidden="true"><path d={paths[id]} stroke="currentColor" strokeWidth={3.5} strokeLinecap="round" strokeLinejoin="round"/></svg>;
}