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
  brightness:"Brightness",volume:"Volume",mic:"Mic mute",recording:"Recording",
  overlay:"Performance overlay",audio:"Audio output",wifi:"Wi-Fi",
};
const railStyles = `
.rg-utility-rail{display:flex;flex-direction:column;gap:8px;color:#f4f7fb;font-family:Arial,sans-serif;width:108px;min-width:0}
.rg-utility-control{border:1px solid #326987;border-radius:13px;background:linear-gradient(145deg,#143850,#0a2237 48%,#071a2b);padding:6px;min-width:0;text-align:center;font:inherit;color:inherit}
.rg-utility-control button{font:inherit;color:inherit}
.rg-utility-control.gpfocus,.rg-utility-control:focus-visible,.rg-utility-control input:focus-visible{outline:3px solid #39d8ff;outline-offset:2px}
.rg-utility-control:disabled{cursor:default;color:#91b3cd}
.rg-utility-label{display:block;font-size:12px;line-height:1.3;overflow-wrap:normal;word-break:normal}
.rg-utility-value{display:block;font-size:11px;line-height:1.3;color:#a8cbe5;margin-top:5px;overflow-wrap:normal;word-break:normal}
.rg-utility-slider{display:flex;flex-direction:column;align-items:center;gap:8px}
.rg-utility-slider input{writing-mode:vertical-lr;direction:rtl;width:30px;height:70px;accent-color:#39d8ff}
`;

/** Reusable presentation, deliberately not mounted by the production shell yet.
 * The application owns reads, confirmations, persistence and hardware dispatch.
 * Recording's adapter must dismiss Command Center before requesting capture. */
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
    {!onRequest && <span className="rg-utility-value">Support unverified</span>}
    {layout.filter(item => item.side === side).map(({id}) => {
      const reading = readings[id];
      const waiting = pending.includes(id) || reading?.pending;
      const isSlider = id === "brightness" || id === "volume";
      const validPercent = typeof reading?.percent === "number" && Number.isFinite(reading.percent) && reading.percent >= 0 && reading.percent <= 100;
      const disabled = !onRequest || !reading?.available || waiting || (isSlider && !validPercent);
      const status = errors[id] ?? (waiting ? "Applying…" : reading?.value ?? "Unavailable");
      const reason = reading?.reason ?? (!reading?.available ? "No verified capability" : undefined);
      return isSlider ? <label key={id} className="rg-utility-control rg-utility-slider" title={reason}>
        <span className="rg-utility-label">{labels[id]}</span>
        <input type="range" min={0} max={100} step={1} aria-label={labels[id]} aria-orientation="vertical"
          aria-valuetext={validPercent ? status : "Unknown"} value={validPercent ? reading!.percent : 0} disabled={disabled}
          onChange={event => void request(id,Number(event.currentTarget.value))}/>
        <span className="rg-utility-value" role="status">{status}</span>

      </label> : <Button key={id} type="button" className="rg-utility-control" disabled={disabled} title={reason}
        aria-label={`${labels[id]}: ${status}`} onClick={() => void request(id)}>
        <UtilityIcon id={id}/>
        <span className="rg-utility-label">{labels[id]}</span>
        <span className="rg-utility-value" role="status">{status}</span>

      </Button>;
    })}
  </Focusable>;
}


function UtilityIcon({id}: {id: UtilityId}) {
  if(id === "overlay") return <CommandCenterIcon id="performance" size={24}/>;
  const paths: Partial<Record<UtilityId,string>> = {
    mic:"M25 11a7 7 0 0 1 14 0v20a7 7 0 0 1-14 0ZM18 28v3a14 14 0 0 0 28 0v-3M32 45v10M23 55h18",
    recording:"M12 12h40v40H12ZM25 25h14v14H25Z",
    audio:"M10 26h10l14-12v36L20 38H10ZM43 23a14 14 0 0 1 0 18M49 15a25 25 0 0 1 0 34",
    wifi:"M8 23a36 36 0 0 1 48 0M17 33a23 23 0 0 1 30 0M25 43a11 11 0 0 1 14 0M32 52h.01",
  };
  return <svg width={24} height={24} viewBox="0 0 64 64" fill="none" aria-hidden="true"><path d={paths[id]} stroke="currentColor" strokeWidth={3.5} strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
